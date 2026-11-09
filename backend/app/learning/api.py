"""HTTP routes for the tutor, lessons, learning path and progress.

Every query on learner data filters on the authenticated learner, and another learner's
row answers 404. LLM calls happen with no transaction open and before any write, so a
failed call can't leave anything partly stored.
"""

import hashlib
import secrets
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.assessment.models import AttemptQuestion, ExamAttempt
from app.db import get_session
from app.learning import lessons as lesson_service
from app.learning import llm, plan, tutor
from app.learning.lessons import LessonContent
from app.learning.models import (
    Conversation,
    ConversationMessage,
    Learner,
    LearningPlan,
    Lesson,
    LessonProgress,
    TopicProgress,
)
from app.learning.retrieval import (
    Topic,
    in_scope,
    load_topics,
    scope_version_id,
)
from app.learning.schemas import (
    MAX_ID,
    AzureExampleOut,
    CheckOutcome,
    CheckQuestion,
    CheckResult,
    CheckSubmit,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    CountOut,
    Dashboard,
    DomainCount,
    DomainOut,
    Exchange,
    LearnerCreated,
    LessonCreate,
    LessonOut,
    LessonProgressOut,
    LessonProgressUpdate,
    LessonSummary,
    MessageCreate,
    MessageOut,
    NextLesson,
    PlanExplanation,
    PlanInputs,
    PlanItem,
    PlanOut,
    PlanSummary,
    PlanUpdate,
    SkillOut,
    SubskillOut,
    SyllabusOut,
    SyllabusRef,
    TopicProgressOut,
    TopicProgressUpdate,
    WeakArea,
)
from app.sandbox.models import LabProgress, LabValidation
from app.syllabus.models import (
    SyllabusDomain,
    SyllabusSkill,
    SyllabusVersion,
)
from app.syllabus.parser import EXAM_CODE

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]
IdPath = Annotated[int, Path(ge=1, le=MAX_ID)]
VersionQuery = Annotated[int | None, Query(ge=1, le=MAX_ID)]

_NO_SYLLABUS = "No syllabus has been ingested yet. Run: python -m app.syllabus.ingest"


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


def _hash_token(token: str) -> str:
    # A random 256-bit token can't be guessed from its hash, so this needs no salt.
    return hashlib.sha256(token.encode()).hexdigest()


def current_learner(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> Learner:
    scheme, _, token = (authorization or "").partition(" ")
    learner = (
        session.scalar(select(Learner).where(Learner.token_hash == _hash_token(token)))
        if scheme.lower() == "bearer" and token
        else None
    )
    if not learner:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing or unknown learner token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return learner


LearnerDep = Annotated[Learner, Depends(current_learner)]


def _get_or_create[Row: (LessonProgress, TopicProgress, LearningPlan)](
    session: Session, model: type[Row], keys: dict[str, int], **defaults: Any
) -> Row:
    """Survives a concurrent insert: the unique constraint decides, the loser re-reads."""
    row = session.scalar(select(model).filter_by(**keys))
    if row:
        return row
    try:
        with session.begin_nested():
            row = model(**keys, **defaults)
            session.add(row)
        return row
    except IntegrityError:
        return session.scalars(select(model).filter_by(**keys)).one()


# --- Syllabus versions ---


def _latest_version(session: Session) -> SyllabusVersion:
    version = session.scalar(
        select(SyllabusVersion)
        .where(SyllabusVersion.exam_code == EXAM_CODE)
        .order_by(SyllabusVersion.version_number.desc())
        .limit(1)
    )
    if not version:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_SYLLABUS)
    return version


def _version_numbered(session: Session, number: int) -> SyllabusVersion:
    version = session.scalar(
        select(SyllabusVersion).where(
            SyllabusVersion.exam_code == EXAM_CODE,
            SyllabusVersion.version_number == number,
        )
    )
    if not version:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No syllabus version {number}")
    return version


def _active_version(
    session: Session, learner: Learner, number: int | None = None
) -> SyllabusVersion:
    """The version asked for, else the newest the learner has a plan on, else the newest
    they have progress or a practice attempt on, else the latest ingested.

    A newly ingested syllabus therefore never moves a learner who has started: they stay
    on their version until they choose to create a plan on the new one.
    """
    if number is not None:
        return _version_numbered(session, number)
    models: tuple[type[LearningPlan | TopicProgress | ExamAttempt], ...] = (
        LearningPlan,
        TopicProgress,
        ExamAttempt,
    )
    for model in models:
        pinned = session.scalar(
            select(SyllabusVersion)
            .join(model, model.syllabus_version_id == SyllabusVersion.id)
            .where(model.learner_id == learner.id)
            .order_by(SyllabusVersion.version_number.desc())
            .limit(1)
        )
        if pinned:
            return pinned
    return _latest_version(session)


def _version_number_of(session: Session, version_id: int) -> int:
    return session.scalars(
        select(SyllabusVersion.version_number).where(SyllabusVersion.id == version_id)
    ).one()


# --- Learners ---


@router.post("/learners", status_code=status.HTTP_201_CREATED)
def create_learner(session: SessionDep) -> LearnerCreated:
    """Returns the token once. Only its hash is stored, so it can't be recovered."""
    token = secrets.token_urlsafe(32)
    learner = Learner(token_hash=_hash_token(token), created_at=_now())
    session.add(learner)
    session.commit()
    return LearnerCreated(id=learner.id, token=token)


@router.get("/syllabus")
def get_syllabus(
    session: SessionDep, learner: LearnerDep, version: VersionQuery = None
) -> SyllabusOut:
    row = session.scalars(
        select(SyllabusVersion)
        .where(SyllabusVersion.id == _active_version(session, learner, version).id)
        .options(
            selectinload(SyllabusVersion.domains)
            .selectinload(SyllabusDomain.skills)
            .selectinload(SyllabusSkill.subskills)
        )
    ).one()
    return SyllabusOut(
        version_number=row.version_number,
        latest_version_number=_latest_version(session).version_number,
        exam_code=row.exam_code,
        effective_date=row.effective_date,
        source_url=row.source_url,
        domains=[
            DomainOut(
                id=domain.id,
                position=domain.position,
                name=domain.name,
                weight_min=domain.weight_min,
                weight_max=domain.weight_max,
                skills=[
                    SkillOut(
                        id=skill.id,
                        position=skill.position,
                        name=skill.name,
                        subskills=[
                            SubskillOut(id=s.id, position=s.position, text=s.text)
                            for s in skill.subskills
                        ],
                    )
                    for skill in domain.skills
                ],
            )
            for domain in row.domains
        ],
    )


# --- Tutor ---


def _message_out(message: ConversationMessage) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        references=[SyllabusRef(**ref) for ref in message.syllabus_refs],
        llm_model=message.llm_model,
        llm_provider=message.llm_provider,
        created_at=message.created_at,
    )


def _conversation_fields(
    session: Session, conversation: Conversation
) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "scope_level": conversation.scope_level,
        "scope_id": conversation.scope_id,
        "version_number": _version_number_of(session, conversation.syllabus_version_id),
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def _own_conversation(
    session: Session, learner: Learner, conversation_id: int, lock: bool = False
) -> Conversation:
    query = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.learner_id == learner.id
    )
    conversation = session.scalar(query.with_for_update() if lock else query)
    if not conversation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


def _stored_exchange(
    session: Session, conversation_id: int, client_message_id: str
) -> Exchange | None:
    question = session.scalar(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.client_message_id == client_message_id,
        )
    )
    if not question:
        return None
    answer = session.scalars(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.id > question.id,
        )
        .order_by(ConversationMessage.id)
        .limit(1)
    ).one()
    return Exchange(
        user_message=_message_out(question), assistant_message=_message_out(answer)
    )


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    body: ConversationCreate, session: SessionDep, learner: LearnerDep
) -> ConversationOut:
    if body.scope_level and body.scope_id:
        version_id = scope_version_id(session, body.scope_level, body.scope_id)
        if version_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus topic not found")
    else:
        version_id = _active_version(session, learner).id
    now = _now()
    conversation = Conversation(
        learner_id=learner.id,
        syllabus_version_id=version_id,
        scope_level=body.scope_level,
        scope_id=body.scope_id,
        title=body.title or None,
        created_at=now,
        updated_at=now,
    )
    session.add(conversation)
    session.commit()
    return ConversationOut(**_conversation_fields(session, conversation))


@router.get("/conversations")
def list_conversations(
    session: SessionDep, learner: LearnerDep
) -> list[ConversationOut]:
    conversations = session.scalars(
        select(Conversation)
        .where(Conversation.learner_id == learner.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )
    return [
        ConversationOut(**_conversation_fields(session, conversation))
        for conversation in conversations
    ]


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: IdPath, session: SessionDep, learner: LearnerDep
) -> ConversationDetail:
    conversation = _own_conversation(session, learner, conversation_id)
    messages = session.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.id)
    )
    return ConversationDetail(
        **_conversation_fields(session, conversation),
        messages=[_message_out(message) for message in messages],
    )


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: IdPath,
    body: MessageCreate,
    session: SessionDep,
    learner: LearnerDep,
) -> Exchange:
    """Idempotent on client_message_id. Stores both messages, or neither."""
    conversation = _own_conversation(session, learner, conversation_id)
    stored = _stored_exchange(session, conversation.id, body.client_message_id)
    if stored:
        return stored

    history = list(
        session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.id.desc())
            .limit(tutor.HISTORY_MESSAGES)
        )
    )[::-1]
    topics = load_topics(session, conversation.syllabus_version_id)
    references = tutor.select_references(
        topics,
        body.content,
        in_scope(topics, conversation.scope_level, conversation.scope_id),
        tutor.previous_references(history),
    )
    prompt = tutor.build_messages(history, references, body.content)
    # Don't hold a database connection through a slow model call.
    session.commit()

    llm.reserve(learner.id)
    reply = llm.complete(prompt)
    answer = llm.clean_model_text(reply.text, len(references))
    if not answer:
        raise llm.invalid_output("The AI model returned an empty response. Try again.")

    # Serializes sends per conversation, so exchanges can't interleave.
    conversation = _own_conversation(session, learner, conversation_id, lock=True)
    stored = _stored_exchange(session, conversation.id, body.client_message_id)
    if stored:
        return stored
    now = _now()
    question_row = ConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content=body.content,
        syllabus_refs=[],
        client_message_id=body.client_message_id,
        created_at=now,
    )
    session.add(question_row)
    session.flush()
    answer_row = ConversationMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        syllabus_refs=references,
        llm_model=reply.model,
        llm_provider=reply.provider,
        created_at=now,
    )
    session.add(answer_row)
    conversation.updated_at = now
    conversation.title = conversation.title or body.content[:80]
    session.commit()
    return Exchange(
        user_message=_message_out(question_row),
        assistant_message=_message_out(answer_row),
    )


# --- Progress writes ---


def _set_topic_status(
    session: Session, learner: Learner, version_id: int, subskill_id: int, new: str
) -> TopicProgress:
    """Idempotent: repeating a status changes nothing, including its timestamps."""
    now = _now()
    row = _get_or_create(
        session,
        TopicProgress,
        {"learner_id": learner.id, "subskill_id": subskill_id},
        syllabus_version_id=version_id,
        status="not_started",
        updated_at=now,
    )
    if row.status == new:
        return row
    row.status = new
    row.updated_at = now
    if new == "not_started":
        row.started_at = row.completed_at = None
    else:
        row.started_at = row.started_at or now
        row.completed_at = (row.completed_at or now) if new == "completed" else None
    return row


def _start_topics(
    session: Session, learner: Learner, version_id: int, topics: Sequence[Topic]
) -> None:
    """Opening a lesson marks new topics started but never un-completes finished ones."""
    existing: dict[int, str] = {
        row[0]: row[1]
        for row in session.execute(
            select(TopicProgress.subskill_id, TopicProgress.status).where(
                TopicProgress.learner_id == learner.id,
                TopicProgress.syllabus_version_id == version_id,
            )
        )
    }
    for topic in topics:
        if existing.get(topic.subskill_id, "not_started") == "not_started":
            _set_topic_status(
                session, learner, version_id, topic.subskill_id, "in_progress"
            )


@router.put("/progress/topics/{subskill_id}")
def set_topic_progress(
    subskill_id: IdPath,
    body: TopicProgressUpdate,
    session: SessionDep,
    learner: LearnerDep,
) -> TopicProgressOut:
    version_id = scope_version_id(session, "subskill", subskill_id)
    if version_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus topic not found")
    row = _set_topic_status(session, learner, version_id, subskill_id, body.status)
    session.commit()
    return TopicProgressOut(
        subskill_id=row.subskill_id,
        version_number=_version_number_of(session, version_id),
        status=row.status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        updated_at=row.updated_at,
    )


# --- Lessons ---


def _check_outcome(lesson: Lesson, progress: LessonProgress) -> CheckOutcome | None:
    """Answers appear only with the learner's own stored result, never before it."""
    if progress.check_answers is None:
        return None
    assert progress.check_score is not None and progress.check_total is not None
    return CheckOutcome(
        score=progress.check_score,
        total=progress.check_total,
        passed=lesson_service.passed(progress.check_score, progress.check_total),
        attempts=progress.check_attempts,
        submitted_at=progress.check_submitted_at,
        results=[
            CheckResult(
                chosen_index=chosen,
                correct_index=check["correct_index"],
                is_correct=chosen == check["correct_index"],
                explanation=check["explanation"],
            )
            for chosen, check in zip(
                progress.check_answers,
                lesson.content["comprehension_checks"],
                strict=True,
            )
        ],
    )


def _lesson_out(
    session: Session, lesson: Lesson, progress: LessonProgress, reused: bool = False
) -> LessonOut:
    content = LessonContent.model_validate(lesson.content)
    return LessonOut(
        id=lesson.id,
        title=content.title,
        scope_level=lesson.scope_level,
        scope_id=lesson.scope_id,
        depth=lesson.depth,
        learning_objectives=content.learning_objectives,
        explanation=content.explanation,
        azure_examples=[
            AzureExampleOut(title=example.title, scenario=example.scenario)
            for example in content.azure_examples
        ],
        key_takeaways=content.key_takeaways,
        checks=[
            CheckQuestion(question=check.question, options=check.options)
            for check in content.comprehension_checks
        ],
        references=[SyllabusRef(**ref) for ref in lesson.syllabus_refs],
        version_number=_version_number_of(session, lesson.syllabus_version_id),
        llm_model=lesson.llm_model,
        llm_provider=lesson.llm_provider,
        created_at=lesson.created_at,
        reused=reused,
        progress=LessonProgressOut(
            status=progress.status,
            started_at=progress.started_at,
            completed_at=progress.completed_at,
            check=_check_outcome(lesson, progress),
        ),
    )


def _start_lesson(session: Session, learner: Learner, lesson: Lesson) -> LessonProgress:
    progress = _get_or_create(
        session,
        LessonProgress,
        {"learner_id": learner.id, "lesson_id": lesson.id},
        status="in_progress",
        started_at=_now(),
        check_attempts=0,
    )
    topics = in_scope(
        load_topics(session, lesson.syllabus_version_id),
        lesson.scope_level,
        lesson.scope_id,
    )
    _start_topics(session, learner, lesson.syllabus_version_id, topics)
    return progress


def _find_lesson(
    session: Session, version_id: int, body: LessonCreate
) -> Lesson | None:
    return session.scalar(
        select(Lesson).where(
            Lesson.syllabus_version_id == version_id,
            Lesson.scope_level == body.scope_level,
            Lesson.scope_id == body.scope_id,
            Lesson.depth == body.depth,
        )
    )


def _opened_lesson(
    session: Session, learner: Learner, lesson_id: int, lock: bool = False
) -> tuple[Lesson, LessonProgress]:
    """A lesson is reachable by id only after this learner has opened it."""
    query = (
        select(Lesson, LessonProgress)
        .join(LessonProgress, LessonProgress.lesson_id == Lesson.id)
        .where(Lesson.id == lesson_id, LessonProgress.learner_id == learner.id)
    )
    # Locking serializes this learner's concurrent writes, so timestamps and attempts stay true.
    row = session.execute(
        query.with_for_update(of=LessonProgress) if lock else query
    ).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return row[0], row[1]


@router.post("/lessons")
def open_lesson(
    body: LessonCreate, session: SessionDep, learner: LearnerDep
) -> LessonOut:
    """Return the stored lesson for this topic and depth, generating it the first time."""
    version_id = scope_version_id(session, body.scope_level, body.scope_id)
    if version_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus topic not found")

    lesson = _find_lesson(session, version_id, body)
    reused = lesson is not None
    if not lesson:
        topics = in_scope(
            load_topics(session, version_id), body.scope_level, body.scope_id
        )
        # Don't hold a database connection through a slow model call.
        session.commit()
        llm.reserve(learner.id)
        content, reply = lesson_service.generate(body.scope_level, topics, body.depth)
        new_lesson = Lesson(
            syllabus_version_id=version_id,
            scope_level=body.scope_level,
            scope_id=body.scope_id,
            depth=body.depth,
            content=content,
            syllabus_refs=[topic.reference("lesson_scope") for topic in topics],
            llm_model=reply.model,
            llm_provider=reply.provider,
            created_at=_now(),
        )
        try:
            with session.begin_nested():
                session.add(new_lesson)
            lesson = new_lesson
        except IntegrityError:
            # Someone generated the same lesson meanwhile. Everyone gets the one stored.
            lesson = _find_lesson(session, version_id, body)
            assert lesson is not None
            reused = True

    progress = _start_lesson(session, learner, lesson)
    session.commit()
    return _lesson_out(session, lesson, progress, reused)


@router.get("/lessons")
def list_lessons(
    session: SessionDep, learner: LearnerDep, version: VersionQuery = None
) -> list[LessonSummary]:
    """Lessons this learner has opened on this version, most recent first."""
    active = _active_version(session, learner, version)
    rows = session.execute(
        select(Lesson, LessonProgress)
        .join(LessonProgress, LessonProgress.lesson_id == Lesson.id)
        .where(
            LessonProgress.learner_id == learner.id,
            Lesson.syllabus_version_id == active.id,
        )
        .order_by(LessonProgress.started_at.desc(), Lesson.id.desc())
    )
    return [
        LessonSummary(
            id=lesson.id,
            title=lesson.content["title"],
            scope_level=lesson.scope_level,
            scope_id=lesson.scope_id,
            depth=lesson.depth,
            version_number=active.version_number,
            status=progress.status,
            check_score=progress.check_score,
            check_total=progress.check_total,
        )
        for lesson, progress in rows
    ]


@router.get("/lessons/{lesson_id}")
def get_lesson(
    lesson_id: IdPath, session: SessionDep, learner: LearnerDep
) -> LessonOut:
    lesson, progress = _opened_lesson(session, learner, lesson_id)
    return _lesson_out(session, lesson, progress, reused=True)


@router.put("/lessons/{lesson_id}/progress")
def set_lesson_progress(
    lesson_id: IdPath,
    body: LessonProgressUpdate,
    session: SessionDep,
    learner: LearnerDep,
) -> LessonOut:
    """Idempotent. Applies to every objective the lesson covers."""
    lesson, progress = _opened_lesson(session, learner, lesson_id, lock=True)
    if progress.status != body.status:
        progress.status = body.status
        progress.completed_at = _now() if body.status == "completed" else None
    for topic in in_scope(
        load_topics(session, lesson.syllabus_version_id),
        lesson.scope_level,
        lesson.scope_id,
    ):
        _set_topic_status(
            session, learner, lesson.syllabus_version_id, topic.subskill_id, body.status
        )
    session.commit()
    return _lesson_out(session, lesson, progress, reused=True)


@router.post("/lessons/{lesson_id}/checks")
def submit_checks(
    lesson_id: IdPath, body: CheckSubmit, session: SessionDep, learner: LearnerDep
) -> LessonOut:
    """Graded here, not by the model. Resubmitting the same answers changes nothing."""
    lesson, progress = _opened_lesson(session, learner, lesson_id, lock=True)
    checks = lesson.content["comprehension_checks"]
    if len(body.answers) != len(checks) or any(
        answer >= len(check["options"])
        for answer, check in zip(body.answers, checks, strict=True)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Answer every question with one of its options",
        )
    if progress.check_answers != body.answers:
        progress.check_answers = body.answers
        progress.check_score = lesson_service.grade(lesson.content, body.answers)
        progress.check_total = len(checks)
        progress.check_attempts += 1
        progress.check_submitted_at = _now()
    session.commit()
    return _lesson_out(session, lesson, progress, reused=True)


# --- Learning path ---


def _own_plan(
    session: Session, learner: Learner, version_id: int
) -> LearningPlan | None:
    return session.scalar(
        select(LearningPlan).where(
            LearningPlan.learner_id == learner.id,
            LearningPlan.syllabus_version_id == version_id,
        )
    )


def _plan_inputs(row: LearningPlan) -> PlanInputs:
    return PlanInputs(
        familiarity={int(key): value for key, value in row.familiarity.items()},
        weekly_hours=row.weekly_hours,
        exam_date=row.exam_date,
    )


def _plan_view(session: Session, learner: Learner, version: SyllabusVersion) -> PlanOut:
    latest = _latest_version(session).version_number
    row = _own_plan(session, learner, version.id)
    if not row:
        return PlanOut(
            version_number=version.version_number,
            latest_version_number=latest,
            inputs=None,
            summary=None,
            items=[],
        )
    topics = load_topics(session, version.id)
    states = plan.load_states(session, learner.id, version.id, topics)
    items, summary = plan.schedule(
        plan.recommend(topics, row.familiarity, states),
        row.weekly_hours,
        row.exam_date,
        _today(),
    )
    return PlanOut(
        version_number=version.version_number,
        latest_version_number=latest,
        inputs=_plan_inputs(row),
        summary=PlanSummary(
            remaining_topics=summary.remaining_topics,
            remaining_minutes=summary.remaining_minutes,
            weeks_needed=summary.weeks_needed,
            projected_finish=summary.projected_finish,
            exam_date=summary.exam_date,
            days_until_exam=summary.days_until_exam,
            on_track=summary.on_track,
            required_weekly_hours=summary.required_weekly_hours,
        ),
        items=[
            PlanItem(
                topic=SyllabusRef(**item.recommendation.topic.reference()),
                status=states[item.recommendation.topic.subskill_id].status,
                kind=item.recommendation.kind,
                minutes=item.recommendation.minutes,
                reason=item.recommendation.reason,
                week=item.week,
                week_start=item.week_start,
                after_exam=item.after_exam,
            )
            for item in items
        ],
    )


@router.get("/plan")
def get_plan(
    session: SessionDep, learner: LearnerDep, version: VersionQuery = None
) -> PlanOut:
    return _plan_view(session, learner, _active_version(session, learner, version))


@router.put("/plan")
def save_plan(body: PlanUpdate, session: SessionDep, learner: LearnerDep) -> PlanOut:
    """Create or adjust the plan. Only inputs change, so progress can't be lost."""
    version = _active_version(session, learner, body.version_number)
    skill_ids = set(
        session.scalars(
            select(SyllabusSkill.id)
            .join(SyllabusDomain)
            .where(SyllabusDomain.version_id == version.id)
        )
    )
    if set(body.familiarity) - skill_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Familiarity lists a skill outside this syllabus version",
        )
    if body.exam_date and body.exam_date < _today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The exam date is in the past"
        )
    now = _now()
    row = _get_or_create(
        session,
        LearningPlan,
        {"learner_id": learner.id, "syllabus_version_id": version.id},
        familiarity={},
        weekly_hours=body.weekly_hours,
        created_at=now,
        updated_at=now,
    )
    row.familiarity = {str(key): value for key, value in body.familiarity.items()}
    row.weekly_hours = body.weekly_hours
    row.exam_date = body.exam_date
    row.updated_at = now
    session.commit()
    return _plan_view(session, learner, version)


@router.delete("/plan", status_code=status.HTTP_204_NO_CONTENT)
def clear_plan(session: SessionDep, learner: LearnerDep) -> None:
    """Remove the learner's plan inputs, for every syllabus version. Progress stays."""
    session.execute(delete(LearningPlan).where(LearningPlan.learner_id == learner.id))
    session.commit()


@router.post("/plan/explanation")
def explain_plan(
    session: SessionDep, learner: LearnerDep, version: VersionQuery = None
) -> PlanExplanation:
    """Narrates the computed plan. Not stored, and nothing else depends on it."""
    active = _active_version(session, learner, version)
    row = _own_plan(session, learner, active.id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Create a learning plan first")
    topics = load_topics(session, active.id)
    states = plan.load_states(session, learner.id, active.id, topics)
    items, summary = plan.schedule(
        plan.recommend(topics, row.familiarity, states),
        row.weekly_hours,
        row.exam_date,
        _today(),
    )
    session.commit()
    llm.reserve(learner.id)
    reply = llm.complete(plan.explanation_messages(items, summary))
    return PlanExplanation(
        text=llm.clean_model_text(reply.text, 0),
        llm_model=reply.model,
        llm_provider=reply.provider,
    )


# --- Dashboard ---


def _count_out(count: plan.Count) -> dict[str, int]:
    return {
        "completed": count.completed,
        "in_progress": count.in_progress,
        "total": count.total,
        "percent": count.percent,
    }


@router.delete("/progress", status_code=status.HTTP_204_NO_CONTENT)
def clear_progress(session: SessionDep, learner: LearnerDep) -> None:
    """Forget this learner's study, practice and lab results. Plan inputs, tutor chats
    and sandbox resources stay; lessons and questions are shared, so they stay too."""
    mine = AttemptQuestion.attempt_id.in_(
        select(ExamAttempt.id).where(ExamAttempt.learner_id == learner.id)
    )
    session.execute(delete(AttemptQuestion).where(mine))
    for model in (
        ExamAttempt,
        LessonProgress,
        TopicProgress,
        LabProgress,
        LabValidation,
    ):
        session.execute(delete(model).where(model.learner_id == learner.id))
    session.commit()


@router.delete("/conversations", status_code=status.HTTP_204_NO_CONTENT)
def clear_memory(session: SessionDep, learner: LearnerDep) -> None:
    """Delete every tutor conversation, which is all the tutor remembers."""
    mine = ConversationMessage.conversation_id.in_(
        select(Conversation.id).where(Conversation.learner_id == learner.id)
    )
    session.execute(delete(ConversationMessage).where(mine))
    session.execute(delete(Conversation).where(Conversation.learner_id == learner.id))
    session.commit()


@router.get("/dashboard")
def get_dashboard(
    session: SessionDep, learner: LearnerDep, version: VersionQuery = None
) -> Dashboard:
    active = _active_version(session, learner, version)
    topics = load_topics(session, active.id)
    states = plan.load_states(session, learner.id, active.id, topics)
    row = _own_plan(session, learner, active.id)
    familiarity = row.familiarity if row else None
    recommendations = plan.recommend(topics, familiarity or {}, states)

    domains: dict[int, list[Topic]] = {}
    for topic in topics:
        domains.setdefault(topic.domain_id, []).append(topic)

    lesson_rows = list(
        session.scalars(
            select(LessonProgress)
            .join(Lesson, LessonProgress.lesson_id == Lesson.id)
            .where(
                LessonProgress.learner_id == learner.id,
                Lesson.syllabus_version_id == active.id,
            )
        )
    )
    checked = [progress for progress in lesson_rows if progress.check_total is not None]
    next_up = recommendations[0] if recommendations else None
    return Dashboard(
        version_number=active.version_number,
        latest_version_number=_latest_version(session).version_number,
        has_plan=row is not None,
        overall=CountOut(**_count_out(plan.count(topics, states))),
        domains=[
            DomainCount(
                domain_id=domain_id,
                position=members[0].domain_position,
                name=members[0].domain_name,
                weight_min=members[0].weight_min,
                weight_max=members[0].weight_max,
                **_count_out(plan.count(members, states)),
            )
            for domain_id, members in domains.items()
        ],
        weak_areas=[
            WeakArea(topic=SyllabusRef(**topic.reference()), reason=reason)
            for topic, reason in plan.weak_areas(topics, familiarity, states)
        ],
        next_lesson=NextLesson(
            topic=SyllabusRef(**next_up.topic.reference()),
            kind=next_up.kind,
            minutes=next_up.minutes,
            reason=next_up.reason,
        )
        if next_up
        else None,
        lessons_completed=sum(p.status == "completed" for p in lesson_rows),
        checks_submitted=len(checked),
        checks_passed=sum(
            lesson_service.passed(p.check_score or 0, p.check_total or 0)
            for p in checked
        ),
        last_activity_at=session.scalar(
            select(func.max(TopicProgress.updated_at)).where(
                TopicProgress.learner_id == learner.id,
                TopicProgress.syllabus_version_id == active.id,
            )
        ),
    )
