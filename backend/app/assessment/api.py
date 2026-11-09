"""HTTP routes for the question bank, practice quizzes, mock exams and analytics.

The rules of the learning API apply: every attempt query filters on the authenticated
learner and another learner's attempt answers 404, and model calls happen with no
transaction open and before any write.

Grading uses only stored rows: the browser sends an option index, never a score or a
verdict. Every write to an attempt locks its row and changes state with conditional
updates, so concurrent or repeated requests can't grade twice or change a graded answer.
Deadlines are stored server time: an overdue mock exam is submitted, as of its deadline,
by whichever request touches it next, so a restart loses nothing.
"""

import math
import os
import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Path, status
from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assessment import generation, scoring
from app.assessment.models import (
    AttemptQuestion,
    ExamAttempt,
    LearnSource,
    ObjectiveSource,
    Question,
    QuestionGeneration,
)
from app.assessment.schemas import (
    MAX_QUESTIONS,
    Analytics,
    AnswerSubmit,
    AttemptCreate,
    AttemptItem,
    AttemptOut,
    AttemptSummary,
    BankObjective,
    BankOut,
    DomainPerformance,
    Feedback,
    GenerateRequest,
    GenerateResult,
    Recommendation,
    Rejection,
    SkillPerformance,
    SourceOut,
    SourceRef,
)
from app.learning.api import (
    IdPath,
    LearnerDep,
    SessionDep,
    VersionQuery,
    _active_version,
    _latest_version,
    _version_number_of,
)
from app.learning.models import Learner
from app.learning.retrieval import Topic, in_scope, load_topics, scope_version_id
from app.learning.schemas import SyllabusRef

router = APIRouter(prefix="/api")
PositionPath = Annotated[int, Path(ge=1, le=MAX_QUESTIONS)]

# Learner tokens are free to create, so the global limit is the real ceiling on model
# spend; the per-learner one stops one browser using all of it. 0 turns generation off.
LEARNER_HOURLY_LIMIT_ENV = "QUESTION_GENERATION_LEARNER_HOURLY_LIMIT"
GLOBAL_HOURLY_LIMIT_ENV = "QUESTION_GENERATION_HOURLY_LIMIT"
DEFAULT_LEARNER_HOURLY_LIMIT = 10
DEFAULT_GLOBAL_HOURLY_LIMIT = 60
MAX_ACTIVE_PER_OBJECTIVE = 40


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    # SQLite hands back zoneless datetimes. Everything is stored in UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _rowcount(result: Any) -> int:
    return cast(CursorResult[Any], result).rowcount


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _limit(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _over_limit(session: Session, request: QuestionGeneration) -> str | None:
    """Counts committed requests up to and including this one, refused ones excepted.

    The row is committed before counting, so concurrent requests see each other and the
    limit can be undershot by a race, never exceeded.
    """
    since = _aware(request.created_at) - timedelta(hours=1)
    counted = select(func.count()).where(
        QuestionGeneration.id <= request.id,
        QuestionGeneration.created_at > since,
        QuestionGeneration.status != "refused",
    )
    learner_limit = _limit(LEARNER_HOURLY_LIMIT_ENV, DEFAULT_LEARNER_HOURLY_LIMIT)
    global_limit = _limit(GLOBAL_HOURLY_LIMIT_ENV, DEFAULT_GLOBAL_HOURLY_LIMIT)
    mine = session.scalar(
        counted.where(QuestionGeneration.learner_id == request.learner_id)
    )
    if (mine or 0) > learner_limit:
        return f"You can generate questions {learner_limit} times an hour."
    if (session.scalar(counted) or 0) > global_limit:
        return "Question generation has reached its hourly limit. Try again later."
    return None


# --- Question bank ---


def _current_sources(
    session: Session, subskill_ids: list[int]
) -> dict[int, list[LearnSource]]:
    """Per objective, the newest stored text of each attached page."""
    newest: dict[int, dict[str, LearnSource]] = defaultdict(dict)
    for subskill_id, source in session.execute(
        select(ObjectiveSource.subskill_id, LearnSource)
        .join(LearnSource, LearnSource.id == ObjectiveSource.source_id)
        .where(ObjectiveSource.subskill_id.in_(subskill_ids))
        .order_by(LearnSource.id)
    ):
        newest[subskill_id][source.url] = source
    return {key: list(by_url.values()) for key, by_url in newest.items()}


def _active_counts(session: Session, version_id: int) -> dict[int, dict[str, int]]:
    counts: dict[int, dict[str, int]] = defaultdict(dict)
    for subskill_id, difficulty, number in session.execute(
        select(Question.subskill_id, Question.difficulty, func.count())
        .where(Question.syllabus_version_id == version_id, Question.status == "active")
        .group_by(Question.subskill_id, Question.difficulty)
    ):
        counts[subskill_id][difficulty] = number
    return counts


@router.get("/questions/bank")
def get_bank(
    session: SessionDep, learner: LearnerDep, version: VersionQuery = None
) -> BankOut:
    """What can be practised: sources and question counts per objective. No answers."""
    active = _active_version(session, learner, version)
    topics = load_topics(session, active.id)
    sources = _current_sources(session, [topic.subskill_id for topic in topics])
    counts = _active_counts(session, active.id)
    return BankOut(
        version_number=active.version_number,
        latest_version_number=_latest_version(session).version_number,
        total_questions=sum(sum(c.values()) for c in counts.values()),
        objectives=[
            BankObjective(
                topic=SyllabusRef(**topic.reference()),
                sources=[
                    SourceOut(
                        id=s.id, title=s.title, url=s.url, retrieved_at=s.retrieved_at
                    )
                    for s in sources.get(topic.subskill_id, [])
                ],
                questions=sum(counts[topic.subskill_id].values()),
                by_difficulty=counts[topic.subskill_id],
            )
            for topic in topics
        ],
    )


@router.post("/questions/generate")
def generate_questions(
    body: GenerateRequest, session: SessionDep, learner: LearnerDep
) -> GenerateResult:
    """Adds only questions that pass every check. A failed model call stores nothing."""
    version_id = scope_version_id(session, "subskill", body.subskill_id)
    if version_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus topic not found")
    [topic] = in_scope(load_topics(session, version_id), "subskill", body.subskill_id)
    sources = [
        generation.SourceText(s.id, s.title, s.url, s.content)
        for s in _current_sources(session, [topic.subskill_id]).get(
            topic.subskill_id, []
        )[-generation.MAX_SOURCES :]
    ]
    if not sources:
        raise _conflict(
            "No Microsoft Learn page is attached to this objective, so its questions "
            "couldn't be verified. Attach one with: python -m app.assessment.sources "
            f"add --subskill {topic.subskill_id} <learn.microsoft.com URL>"
        )
    active = sum(_active_counts(session, version_id)[topic.subskill_id].values())
    if active >= MAX_ACTIVE_PER_OBJECTIVE:
        raise _conflict(
            f"This objective already has {active} questions, the most the bank keeps "
            "per objective."
        )
    existing = generation.Existing(
        frozenset(
            session.scalars(
                select(Question.fingerprint).where(
                    Question.syllabus_version_id == version_id
                )
            )
        ),
        tuple(
            generation.stem_terms(scenario, stem)
            for scenario, stem in session.execute(
                select(Question.scenario, Question.stem).where(
                    Question.subskill_id == topic.subskill_id
                )
            )
        ),
    )
    log = QuestionGeneration(
        learner_id=learner.id,
        subskill_id=topic.subskill_id,
        status="running",
        created_at=_now(),
    )
    session.add(log)
    # Committed before counting and before the model call, which also means no
    # database connection is held through slow model calls.
    session.commit()
    refusal = _over_limit(session, log)
    if refusal:
        log.status, log.finished_at = "refused", _now()
        session.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            refusal,
            headers={"Retry-After": "3600"},
        )
    session.commit()

    try:
        accepted, rejected, reply = generation.generate(
            topic, sources, body.count, body.difficulty, body.kind, existing
        )
    except Exception:
        # The call may still have cost money, so it keeps counting toward the limits.
        log.status, log.finished_at = "failed", _now()
        session.commit()
        raise
    now = _now()
    stored = 0
    for item in accepted:
        candidate = item.candidate
        try:
            with session.begin_nested():
                session.add(
                    Question(
                        syllabus_version_id=version_id,
                        domain_id=topic.domain_id,
                        skill_id=topic.skill_id,
                        subskill_id=topic.subskill_id,
                        kind=body.kind,
                        difficulty=body.difficulty,
                        scenario=candidate.scenario,
                        stem=candidate.stem,
                        options=candidate.options,
                        correct_index=candidate.correct_index,
                        explanation=candidate.explanation,
                        source_id=item.source_id,
                        source_excerpt=candidate.source_excerpt,
                        fingerprint=item.fingerprint,
                        status="active",
                        llm_model=reply.model,
                        llm_provider=reply.provider,
                        created_at=now,
                    )
                )
            stored += 1
        except IntegrityError:
            # The same question was stored meanwhile by another request.
            rejected.append(generation.Rejected(candidate.stem[:120], "duplicate"))
    log.status, log.finished_at = "completed", now
    log.accepted, log.rejected = stored, len(rejected)
    session.commit()
    return GenerateResult(
        accepted=stored,
        rejected=[Rejection(stem=r.stem, reason=r.reason) for r in rejected],
        active_questions=sum(
            _active_counts(session, version_id)[topic.subskill_id].values()
        ),
        llm_model=reply.model,
        llm_provider=reply.provider,
    )


# --- Attempts ---


def _own_attempt(
    session: Session, learner: Learner, attempt_id: int, lock: bool = False
) -> ExamAttempt:
    query = select(ExamAttempt).where(
        ExamAttempt.id == attempt_id, ExamAttempt.learner_id == learner.id
    )
    if lock:
        # Locked reads must see the row as it is now, not as this session last saw it.
        query = query.with_for_update().execution_options(populate_existing=True)
    attempt = session.scalar(query)
    if not attempt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return attempt


def _expired(attempt: ExamAttempt, now: datetime) -> bool:
    return (
        attempt.status == "in_progress"
        and attempt.deadline_at is not None
        and now >= _aware(attempt.deadline_at)
    )


def _finalize(
    session: Session, attempt: ExamAttempt, reason: str, now: datetime
) -> None:
    """Submit and grade. The status change is conditional, so only one request wins."""
    submitted_at = (
        _aware(attempt.deadline_at)
        if reason == "time_expired" and attempt.deadline_at
        else now
    )
    won = session.execute(
        update(ExamAttempt)
        .where(ExamAttempt.id == attempt.id, ExamAttempt.status == "in_progress")
        .values(status="submitted", submitted_at=submitted_at, submit_reason=reason)
        .execution_options(synchronize_session=False)
    )
    if _rowcount(won) == 0:
        return
    score = 0
    for row, correct_index in session.execute(
        select(AttemptQuestion, Question.correct_index)
        .join(Question, Question.id == AttemptQuestion.question_id)
        .where(AttemptQuestion.attempt_id == attempt.id)
        .execution_options(populate_existing=True)
    ):
        # Practice answers were graded as they came. Unanswered mock questions are wrong.
        if attempt.mode == "mock":
            row.is_correct = row.chosen_index == correct_index
        score += row.is_correct is True
    session.execute(
        update(ExamAttempt)
        .where(ExamAttempt.id == attempt.id)
        .values(score=score)
        .execution_options(synchronize_session=False)
    )


def _settle(session: Session, learner: Learner, attempt: ExamAttempt) -> ExamAttempt:
    """Submit an overdue mock exam before anyone sees it."""
    now = _now()
    if _expired(attempt, now):
        attempt = _own_attempt(session, learner, attempt.id, lock=True)
        if _expired(attempt, now):
            _finalize(session, attempt, "time_expired", now)
        session.commit()
    return attempt


def _settle_all(session: Session, learner: Learner) -> None:
    for attempt in session.scalars(
        select(ExamAttempt).where(
            ExamAttempt.learner_id == learner.id,
            ExamAttempt.status == "in_progress",
            ExamAttempt.deadline_at.is_not(None),
        )
    ).all():
        _settle(session, learner, attempt)


def _summary_fields(
    attempt: ExamAttempt, answered: int, version_number: int
) -> dict[str, Any]:
    submitted = attempt.status == "submitted" and attempt.score is not None
    percent = (
        attempt.score * 100 // attempt.question_count
        if submitted and attempt.score is not None
        else None
    )
    return {
        "id": attempt.id,
        "mode": attempt.mode,
        "selection": attempt.selection,
        "scope_level": attempt.scope_level,
        "scope_id": attempt.scope_id,
        "version_number": version_number,
        "status": attempt.status,
        "question_count": attempt.question_count,
        "answered_count": answered,
        "score": attempt.score if submitted else None,
        "percent": percent,
        "passed": percent >= scoring.PASS_PERCENT
        if percent is not None and attempt.mode == "mock"
        else None,
        "started_at": attempt.started_at,
        "deadline_at": attempt.deadline_at,
        "submitted_at": attempt.submitted_at,
        "submit_reason": attempt.submit_reason,
    }


def _attempt_out(session: Session, attempt: ExamAttempt) -> AttemptOut:
    session.refresh(attempt)
    now = _now()
    topics = {
        t.subskill_id: t for t in load_topics(session, attempt.syllabus_version_id)
    }
    submitted = attempt.status == "submitted"
    items = []
    for row, question, source in session.execute(
        select(AttemptQuestion, Question, LearnSource)
        .join(Question, Question.id == AttemptQuestion.question_id)
        .join(LearnSource, LearnSource.id == Question.source_id)
        .where(AttemptQuestion.attempt_id == attempt.id)
        .order_by(AttemptQuestion.position)
        .execution_options(populate_existing=True)
    ):
        # Answers are shown only once the server has graded them.
        graded = submitted or (
            attempt.mode == "practice" and row.is_correct is not None
        )
        items.append(
            AttemptItem(
                position=row.position,
                kind=question.kind,
                difficulty=question.difficulty,
                scenario=question.scenario,
                stem=question.stem,
                options=question.options,
                chosen_index=row.chosen_index,
                feedback=Feedback(
                    chosen_index=row.chosen_index,
                    correct_index=question.correct_index,
                    is_correct=row.is_correct is True,
                    explanation=question.explanation,
                    source=SourceRef(
                        title=source.title,
                        url=source.url,
                        excerpt=question.source_excerpt,
                    ),
                    topic=SyllabusRef(**topics[question.subskill_id].reference()),
                )
                if graded
                else None,
            )
        )
    remaining = None
    if attempt.status == "in_progress" and attempt.deadline_at:
        remaining = max(
            0, math.ceil((_aware(attempt.deadline_at) - now).total_seconds())
        )
    return AttemptOut(
        **_summary_fields(
            attempt,
            sum(item.chosen_index is not None for item in items),
            _version_number_of(session, attempt.syllabus_version_id),
        ),
        difficulty=attempt.difficulty,
        time_limit_seconds=attempt.time_limit_seconds,
        server_time=now,
        remaining_seconds=remaining,
        pass_percent=scoring.PASS_PERCENT,
        items=items,
    )


def _by_client_id(
    session: Session, learner: Learner, client_attempt_id: str
) -> ExamAttempt | None:
    return session.scalar(
        select(ExamAttempt).where(
            ExamAttempt.learner_id == learner.id,
            ExamAttempt.client_attempt_id == client_attempt_id,
        )
    )


def _last_results(
    session: Session, learner_id: int, version_id: int
) -> dict[int, bool]:
    """This learner's latest graded result per question on this version."""
    rows = session.execute(
        select(AttemptQuestion.question_id, AttemptQuestion.is_correct)
        .join(ExamAttempt, ExamAttempt.id == AttemptQuestion.attempt_id)
        .where(
            ExamAttempt.learner_id == learner_id,
            ExamAttempt.syllabus_version_id == version_id,
            AttemptQuestion.is_correct.is_not(None),
        )
        .order_by(AttemptQuestion.id)
    )
    return {question_id: bool(correct) for question_id, correct in rows}


def _graded(session: Session, learner_id: int, version_id: int) -> list[scoring.Graded]:
    rows = session.execute(
        select(Question.subskill_id, AttemptQuestion.is_correct)
        .join(Question, Question.id == AttemptQuestion.question_id)
        .join(ExamAttempt, ExamAttempt.id == AttemptQuestion.attempt_id)
        .where(
            ExamAttempt.learner_id == learner_id,
            ExamAttempt.syllabus_version_id == version_id,
            AttemptQuestion.is_correct.is_not(None),
        )
    )
    return [scoring.Graded(subskill_id, bool(correct)) for subskill_id, correct in rows]


@router.post("/attempts", status_code=status.HTTP_201_CREATED)
def create_attempt(
    body: AttemptCreate, session: SessionDep, learner: LearnerDep
) -> AttemptOut:
    """Idempotent on client_attempt_id: a repeated start returns the same attempt."""
    existing = _by_client_id(session, learner, body.client_attempt_id)
    if existing:
        return _attempt_out(session, _settle(session, learner, existing))

    if body.scope_level and body.scope_id:
        version_id = scope_version_id(session, body.scope_level, body.scope_id)
        if version_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus topic not found")
    else:
        version_id = _active_version(session, learner, body.version_number).id
    topics = load_topics(session, version_id)
    scope = (
        in_scope(topics, body.scope_level, body.scope_id)
        if body.scope_level
        else topics
    )
    scope_ids = {topic.subskill_id for topic in scope}

    query = select(Question.id, Question.subskill_id, Question.domain_id).where(
        Question.syllabus_version_id == version_id, Question.status == "active"
    )
    if body.difficulty:
        query = query.where(Question.difficulty == body.difficulty)
    history = _last_results(session, learner.id, version_id)
    candidates = [
        scoring.Candidate(question_id, subskill_id, domain_id, history.get(question_id))
        for question_id, subskill_id, domain_id in session.execute(query)
        if subskill_id in scope_ids
    ]
    rng = random.SystemRandom()
    if body.mode == "mock":
        if len(candidates) < body.question_count:
            raise _conflict(
                f"The question bank has {len(candidates)} questions for this syllabus "
                f"version, fewer than the {body.question_count} asked for. Choose "
                "fewer, or generate more questions first."
            )
        domain_weights = {topic.domain_id: scoring.weight(topic) for topic in topics}
        chosen = scoring.exam_selection(
            candidates, domain_weights, body.question_count, rng
        )
        selection = "exam"
    elif body.adaptive:
        by_subskill = scoring.tallies(
            _graded(session, learner.id, version_id),
            {topic.subskill_id: topic.subskill_id for topic in topics},
        )
        weights = {topic.subskill_id: scoring.weight(topic) for topic in topics}
        chosen = scoring.adaptive_order(candidates, by_subskill, weights, rng)
        selection = "adaptive"
    else:
        chosen = scoring.topic_order(candidates, rng)
        selection = "topic"
    chosen = chosen[: body.question_count]
    if not chosen:
        raise _conflict(
            "No practice questions are available for this choice yet. Generate some "
            "for its objectives first."
        )

    now = _now()
    limit = body.time_limit_minutes * 60 if body.time_limit_minutes else None
    attempt = ExamAttempt(
        learner_id=learner.id,
        syllabus_version_id=version_id,
        client_attempt_id=body.client_attempt_id,
        mode=body.mode,
        selection=selection,
        scope_level=body.scope_level,
        scope_id=body.scope_id,
        difficulty=body.difficulty,
        question_count=len(chosen),
        time_limit_seconds=limit,
        started_at=now,
        deadline_at=now + timedelta(seconds=limit) if limit else None,
        status="in_progress",
    )
    try:
        with session.begin_nested():
            session.add(attempt)
            session.flush()
            session.add_all(
                AttemptQuestion(
                    attempt_id=attempt.id, position=position, question_id=c.question_id
                )
                for position, c in enumerate(chosen, 1)
            )
    except IntegrityError:
        # The same start arrived twice at once. Everyone gets the stored attempt.
        stored = _by_client_id(session, learner, body.client_attempt_id)
        if not stored:
            raise
        attempt = stored
    session.commit()
    return _attempt_out(session, attempt)


@router.get("/attempts")
def list_attempts(
    session: SessionDep, learner: LearnerDep, version: VersionQuery = None
) -> list[AttemptSummary]:
    _settle_all(session, learner)
    active = _active_version(session, learner, version)
    return _summaries(session, learner, active.id, active.version_number)


def _summaries(
    session: Session, learner: Learner, version_id: int, version_number: int
) -> list[AttemptSummary]:
    answered = {
        attempt_id: number
        for attempt_id, number in session.execute(
            select(AttemptQuestion.attempt_id, func.count())
            .join(ExamAttempt, ExamAttempt.id == AttemptQuestion.attempt_id)
            .where(
                ExamAttempt.learner_id == learner.id,
                AttemptQuestion.chosen_index.is_not(None),
            )
            .group_by(AttemptQuestion.attempt_id)
        )
    }
    attempts = session.scalars(
        select(ExamAttempt)
        .where(
            ExamAttempt.learner_id == learner.id,
            ExamAttempt.syllabus_version_id == version_id,
        )
        .order_by(ExamAttempt.started_at.desc(), ExamAttempt.id.desc())
    )
    return [
        AttemptSummary(
            **_summary_fields(attempt, answered.get(attempt.id, 0), version_number)
        )
        for attempt in attempts
    ]


@router.get("/attempts/{attempt_id}")
def get_attempt(
    attempt_id: IdPath, session: SessionDep, learner: LearnerDep
) -> AttemptOut:
    attempt = _own_attempt(session, learner, attempt_id)
    return _attempt_out(session, _settle(session, learner, attempt))


@router.put("/attempts/{attempt_id}/answers/{position}")
def answer_question(
    attempt_id: IdPath,
    position: PositionPath,
    body: AnswerSubmit,
    session: SessionDep,
    learner: LearnerDep,
) -> AttemptOut:
    """Practice: graded at once, and final. Mock: saved, changeable until submission."""
    attempt = _own_attempt(session, learner, attempt_id, lock=True)
    now = _now()
    if _expired(attempt, now):
        _finalize(session, attempt, "time_expired", now)
        session.commit()
        raise _conflict("Time is up, so the exam was submitted with the saved answers.")
    if attempt.status != "in_progress":
        raise _conflict("This attempt has been submitted, so its answers can't change.")
    found = session.execute(
        select(AttemptQuestion, Question.options, Question.correct_index)
        .join(Question, Question.id == AttemptQuestion.question_id)
        .where(
            AttemptQuestion.attempt_id == attempt.id,
            AttemptQuestion.position == position,
        )
    ).first()
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    row, options, correct_index = found
    if body.chosen_index >= len(options):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose one of the question's options",
        )

    target = update(AttemptQuestion).where(AttemptQuestion.id == row.id)
    if attempt.mode == "practice":
        if row.chosen_index is None:
            changed = session.execute(
                target.where(AttemptQuestion.chosen_index.is_(None))
                .values(
                    chosen_index=body.chosen_index,
                    answered_at=now,
                    is_correct=body.chosen_index == correct_index,
                )
                .execution_options(synchronize_session=False)
            )
            if _rowcount(changed) == 0:
                session.rollback()
                session.refresh(row)
        if row.chosen_index is not None and row.chosen_index != body.chosen_index:
            raise _conflict(
                "This question is already answered. Practice answers are final."
            )
        unanswered = session.scalar(
            select(func.count()).where(
                AttemptQuestion.attempt_id == attempt.id,
                AttemptQuestion.chosen_index.is_(None),
            )
        )
        if unanswered == 0:
            _finalize(session, attempt, "completed", now)
    else:
        changed = session.execute(
            target.where(AttemptQuestion.is_correct.is_(None))
            .values(chosen_index=body.chosen_index, answered_at=now)
            .execution_options(synchronize_session=False)
        )
        if _rowcount(changed) == 0:
            raise _conflict(
                "This attempt has been submitted, so its answers can't change."
            )
    session.commit()
    return _attempt_out(session, attempt)


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(
    attempt_id: IdPath, session: SessionDep, learner: LearnerDep
) -> AttemptOut:
    """Idempotent: submitting again returns the stored result unchanged."""
    attempt = _own_attempt(session, learner, attempt_id, lock=True)
    if attempt.status == "in_progress":
        now = _now()
        _finalize(
            session,
            attempt,
            "time_expired" if _expired(attempt, now) else "learner",
            now,
        )
    session.commit()
    return _attempt_out(session, attempt)


# --- Analytics ---


def _area(tally: scoring.Tally) -> dict[str, Any]:
    return {
        "answered": tally.answered,
        "correct": tally.correct,
        "percent": tally.percent,
        "standing": scoring.standing(tally),
    }


@router.get("/analytics")
def get_analytics(
    session: SessionDep, learner: LearnerDep, version: VersionQuery = None
) -> Analytics:
    """Computed on every read from graded answers, so it always matches them."""
    _settle_all(session, learner)
    active = _active_version(session, learner, version)
    topics = load_topics(session, active.id)
    graded = _graded(session, learner.id, active.id)
    by_subskill = scoring.tallies(
        graded, {t.subskill_id: t.subskill_id for t in topics}
    )
    by_skill = scoring.tallies(graded, {t.subskill_id: t.skill_id for t in topics})
    by_domain = scoring.tallies(graded, {t.subskill_id: t.domain_id for t in topics})
    overall = scoring.Tally(len(graded), sum(row.is_correct for row in graded))
    readiness_percent, readiness = scoring.readiness(topics, graded)
    available = {
        subskill_id: sum(counts.values())
        for subskill_id, counts in _active_counts(session, active.id).items()
    }
    attempts = _summaries(session, learner, active.id, active.version_number)
    mocks = [a.percent for a in attempts if a.mode == "mock" and a.percent is not None]

    domains: dict[int, Topic] = {}
    skills: dict[int, Topic] = {}
    for topic in topics:
        domains.setdefault(topic.domain_id, topic)
        skills.setdefault(topic.skill_id, topic)
    return Analytics(
        version_number=active.version_number,
        latest_version_number=_latest_version(session).version_number,
        answered=overall.answered,
        correct=overall.correct,
        percent=overall.percent,
        readiness_percent=readiness_percent,
        readiness=readiness,
        pass_percent=scoring.PASS_PERCENT,
        mock_exams_taken=len(mocks),
        latest_mock_percent=mocks[0] if mocks else None,
        best_mock_percent=max(mocks) if mocks else None,
        domains=[
            DomainPerformance(
                domain_id=domain_id,
                position=t.domain_position,
                name=t.domain_name,
                weight_min=t.weight_min,
                weight_max=t.weight_max,
                **_area(by_domain.get(domain_id, scoring.Tally())),
            )
            for domain_id, t in domains.items()
        ],
        skills=[
            SkillPerformance(
                skill_id=skill_id,
                domain_id=t.domain_id,
                code=f"{t.domain_position}.{t.skill_position}",
                name=t.skill_name,
                **_area(by_skill.get(skill_id, scoring.Tally())),
            )
            for skill_id, t in skills.items()
        ],
        recommendations=[
            Recommendation(
                topic=SyllabusRef(**topic.reference()),
                answered=tally.answered,
                correct=tally.correct,
                percent=tally.percent,
                reason=reason,
                available_questions=available.get(topic.subskill_id, 0),
            )
            for topic, tally, reason in scoring.recommendations(
                topics, by_subskill, available
            )
        ],
        attempts=attempts,
    )
