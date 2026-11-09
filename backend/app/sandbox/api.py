"""HTTP routes for the Azure sandbox simulator and guided labs.

The learning API's rules apply: every route needs a learner token, every query filters
on that learner, and another learner's resource or lab answers 404. Writes lock the
learner's sandbox (see engine.py) and commit once, so a rejected operation changes
nothing. The assistant's model call happens with no transaction open and stores nothing.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.learning import llm
from app.learning.api import LearnerDep, SessionDep, _active_version
from app.learning.models import Learner
from app.learning.retrieval import Topic, load_topics, search
from app.learning.schemas import SyllabusRef
from app.sandbox import assistant, engine, simulate
from app.sandbox.catalog import (
    MODELS,
    REGIONS,
    TYPES,
    Conflict,
    Invalid,
    Row,
    World,
)
from app.sandbox.labs import LABS, Lab, grade
from app.sandbox.models import LabProgress, LabValidation
from app.sandbox.schemas import (
    ActionRequest,
    ActionResult,
    AssistantReply,
    AssistantRequest,
    Catalog,
    CheckOut,
    DeleteResult,
    HintRequest,
    LabDetail,
    LabSummary,
    OverviewItem,
    ResourceCreate,
    ResourceDetail,
    ResourceSummary,
    ResourceUpdate,
    TaskOut,
    ValidateRequest,
    ValidationOut,
)
from app.syllabus.parser import normalize_text

router = APIRouter(prefix="/api/sandbox")
ResourcePath = Annotated[int, Path(ge=1, le=2**31 - 1)]
LabPath = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]
ActionPath = Annotated[str, Path(pattern=r"^[a-z_]{1,32}$")]


def _write[T](session: Session, operation: Callable[[], T]) -> T:
    """Run a write and commit it, or roll it all back and explain why."""
    try:
        result = operation()
        session.commit()
        return result
    except Invalid as error:
        session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)
        ) from error
    except Conflict as error:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another change conflicted with this one. Reload and try again.",
        ) from error


def _own(world: World, resource_id: int) -> Row:
    """The world holds only this learner's rows, so anyone else's id is simply absent."""
    row = world.rows.get(resource_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
    return row


# --- Resources ---


def _summary(world: World, row: Row) -> ResourceSummary:
    group = world.resource_group(row) if row.state != "soft_deleted" else None
    return ResourceSummary(
        id=row.id,
        resource_type=row.resource_type,
        type_label=TYPES[row.resource_type].label,
        name=row.name,
        parent_id=row.parent_id,
        resource_group=group.name if group else row.outputs.get("deleted_from"),
        resource_group_id=group.id if group else None,
        region=world.region_of(row) or None,
        state=row.state,
        updated_at=row.updated_at,
    )


def _detail(world: World, row: Row) -> ResourceDetail:
    rtype = TYPES[row.resource_type]
    summary = _summary(world, row)
    path = []
    current: Row | None = row
    while current and current.resource_type != "resource_group":
        path.append(current.name)
        current = world.rows.get(current.parent_id) if current.parent_id else None
    group = summary.resource_group or "-"
    arm_id = (
        f"/subscriptions/sandbox/resourceGroups/{row.name}"
        if row.resource_type == "resource_group"
        else f"/subscriptions/sandbox/resourceGroups/{group}/providers/"
        f"{rtype.arm_type.split(' ')[0]}/{'/'.join(reversed(path))}"
    )
    references = {}
    for spec in rtype.fields:
        if spec.kind == "ref" and row.properties.get(spec.key) is not None:
            target = world.rows.get(row.properties[spec.key])
            references[spec.key] = target.name if target else "(deleted)"
    soft = row.state == "soft_deleted"
    actions = (
        ["recover", "purge"]
        if soft
        else [
            action
            for action in rtype.actions
            if not (action == "start" and row.state == "running")
            and not (action == "stop" and row.state == "stopped")
        ]
    )
    return ResourceDetail(
        **summary.model_dump(),
        arm_id=arm_id,
        version=row.version,
        properties=row.properties,
        references=references,
        outputs=row.outputs,
        overview=[
            OverviewItem(label=k, value=v) for k, v in simulate.overview(world, row)
        ],
        issues=[] if soft else simulate.issues(world, row),
        children=[_summary(world, child) for child in world.children(row.id)],
        actions=actions,
        created_at=row.created_at,
        deleted_at=row.deleted_at,
    )


@router.get("/catalog")
def get_catalog(learner: LearnerDep) -> Catalog:
    return Catalog(
        types=[t.describe() for t in TYPES.values()],
        regions=[
            {"name": name, "label": label, "data_zone": zone}
            for name, (label, zone) in REGIONS.items()
        ],
        models=[
            {
                "name": name,
                "kind": model.kind,
                "versions": list(model.versions),
                "deployment_types": list(model.deployment_types),
                "max_dimensions": model.max_dimensions,
            }
            for name, model in MODELS.items()
        ],
        sample_prompts={
            key: value[0] for key, value in simulate.SAMPLE_PROMPTS.items()
        },
        sample_questions={
            key: value[0] for key, value in simulate.SAMPLE_QUESTIONS.items()
        },
    )


@router.get("/resources")
def list_resources(
    session: SessionDep,
    learner: LearnerDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    resource_type: Annotated[str | None, Query(max_length=32)] = None,
) -> list[ResourceSummary]:
    world = engine.read_world(session, learner.id)
    needle = (q or "").strip().lower()
    rows = [
        row
        for row in sorted(world.rows.values(), key=lambda r: r.id)
        if row.state != "soft_deleted"
        and resource_type in (None, row.resource_type)
        and (
            not needle
            or needle in row.name.lower()
            or needle in TYPES[row.resource_type].label.lower()
        )
    ]
    return [_summary(world, row) for row in rows]


@router.get("/deleted")
def list_deleted(session: SessionDep, learner: LearnerDep) -> list[ResourceSummary]:
    world = engine.read_world(session, learner.id)
    return [
        _summary(world, row)
        for row in sorted(world.rows.values(), key=lambda r: r.id)
        if row.state == "soft_deleted"
    ]


@router.post("/resources", status_code=status.HTTP_201_CREATED)
def create_resource(
    body: ResourceCreate, session: SessionDep, learner: LearnerDep
) -> ResourceDetail:
    def operation() -> ResourceDetail:
        world = engine.open_sandbox(session, learner.id)
        row = engine.create(
            session,
            world,
            learner.id,
            body.resource_type,
            body.parent_id,
            body.name,
            body.properties,
            body.client_request_id,
        )
        return _detail(world, row)

    return _write(session, operation)


@router.get("/resources/{resource_id}")
def get_resource(
    resource_id: ResourcePath, session: SessionDep, learner: LearnerDep
) -> ResourceDetail:
    world = engine.read_world(session, learner.id)
    return _detail(world, _own(world, resource_id))


@router.put("/resources/{resource_id}")
def update_resource(
    resource_id: ResourcePath,
    body: ResourceUpdate,
    session: SessionDep,
    learner: LearnerDep,
) -> ResourceDetail:
    def operation() -> ResourceDetail:
        world = engine.open_sandbox(session, learner.id)
        row = engine.update(
            session, world, _own(world, resource_id), body.properties, body.version
        )
        return _detail(world, row)

    return _write(session, operation)


@router.delete("/resources/{resource_id}")
def delete_resource(
    resource_id: ResourcePath,
    session: SessionDep,
    learner: LearnerDep,
    confirm_name: Annotated[str | None, Query(max_length=128)] = None,
) -> DeleteResult:
    def operation() -> DeleteResult:
        world = engine.open_sandbox(session, learner.id)
        row = _own(world, resource_id)
        if row.state == "soft_deleted":
            return DeleteResult(
                deleted=engine.purge(session, world, row), soft_deleted=[]
            )
        return DeleteResult(**engine.delete(session, world, row, confirm_name))

    return _write(session, operation)


@router.post("/resources/{resource_id}/actions/{action}")
def run_action(
    resource_id: ResourcePath,
    action: ActionPath,
    body: ActionRequest,
    session: SessionDep,
    learner: LearnerDep,
) -> ActionResult:
    def operation() -> ActionResult:
        world = engine.open_sandbox(session, learner.id)
        row = _own(world, resource_id)
        result = engine.act(session, world, row, action, body.input)
        return ActionResult(result=result, resource=_detail(world, row))

    return _write(session, operation)


# --- Labs ---


def _lab(lab_id: str) -> Lab:
    lab = LABS.get(lab_id)
    if lab is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lab not found")
    return lab


def _progress(
    session: Session, learner: Learner, lab_id: str, lock: bool = False
) -> LabProgress | None:
    query = select(LabProgress).where(
        LabProgress.learner_id == learner.id, LabProgress.lab_id == lab_id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalar(query)


def _topics(session: Session, learner: Learner) -> list[Topic]:
    """The learner's syllabus version, or none: labs work before anything is ingested."""
    try:
        return load_topics(session, _active_version(session, learner).id)
    except HTTPException:
        return []


def _syllabus(topics: list[Topic], lab: Lab) -> list[SyllabusRef]:
    """Real syllabus rows for the lab's objectives: an exact match, else the best search hit."""
    by_text = {normalize_text(t.subskill_text).lower(): t for t in topics}
    refs: dict[int, SyllabusRef] = {}
    for text in lab.syllabus:
        topic = by_text.get(normalize_text(text).lower()) or next(
            iter(search(topics, text, 1)), None
        )
        if topic:
            refs[topic.subskill_id] = SyllabusRef(**topic.reference("lab"))
    return list(refs.values())


def _validation_out(row: LabValidation) -> ValidationOut:
    return ValidationOut(
        id=row.id,
        passed=row.passed,
        passed_checks=row.passed_checks,
        total_checks=row.total_checks,
        created_at=row.created_at,
    )


def _validations(
    session: Session, learner: Learner, lab_id: str
) -> list[LabValidation]:
    return list(
        session.scalars(
            select(LabValidation)
            .where(
                LabValidation.learner_id == learner.id, LabValidation.lab_id == lab_id
            )
            .order_by(LabValidation.id.desc())
            .limit(20)
        )
    )


def _lab_summary(
    lab: Lab,
    topics: list[Topic],
    progress: LabProgress | None,
    count: int,
    latest: LabValidation | None,
) -> LabSummary:
    return LabSummary(
        id=lab.id,
        title=lab.title,
        objective=lab.objective,
        minutes=lab.minutes,
        resource_group=lab.resource_group,
        syllabus=_syllabus(topics, lab),
        syllabus_text=list(lab.syllabus),
        status=progress.status if progress else "not_started",
        started_at=progress.started_at if progress else None,
        completed_at=progress.completed_at if progress else None,
        validations=count,
        last_validation=_validation_out(latest) if latest else None,
    )


def _lab_detail(
    session: Session, learner: Learner, lab: Lab, world: World | None = None
) -> LabDetail:
    world = world or engine.read_world(session, learner.id)
    progress = _progress(session, learner, lab.id)
    history = _validations(session, learner, lab.id)
    count = (
        session.scalar(
            select(func.count()).where(
                LabValidation.learner_id == learner.id, LabValidation.lab_id == lab.id
            )
        )
        or 0
    )
    latest = history[0] if history else None
    results = {r["check_id"]: r for r in latest.results} if latest else {}
    hints = progress.hints if progress else {}
    group = world.group_named(lab.resource_group)
    tasks = []
    for task in lab.tasks:
        checks = []
        for check in task.checks:
            result = results.get(check.id)
            passed = bool(result and result["passed"])
            checks.append(
                CheckOut(
                    id=check.id,
                    description=check.description,
                    status="not_checked"
                    if result is None
                    else "passed"
                    if passed
                    else "failed",
                    feedback=result["feedback"] if result else None,
                    hints=list(check.hints[: hints.get(check.id, 0)]),
                    hints_total=len(check.hints),
                    explanation=check.explanation if passed else None,
                )
            )
        tasks.append(TaskOut(id=task.id, title=task.title, checks=checks))
    return LabDetail(
        **_lab_summary(
            lab, _topics(session, learner), progress, count, latest
        ).model_dump(),
        prerequisites=list(lab.prerequisites),
        scenario=lab.scenario,
        expected_outcome=lab.expected_outcome,
        instructions=list(lab.instructions),
        tasks=tasks,
        completion=lab.completion if latest and latest.passed else None,
        docs=[{"title": title, "url": url} for title, url in lab.docs],
        approximations=list(lab.approximations),
        resource_group_id=group.id if group else None,
        resets=progress.resets if progress else 0,
        history=[_validation_out(row) for row in history],
    )


@router.get("/labs")
def list_labs(session: SessionDep, learner: LearnerDep) -> list[LabSummary]:
    topics = _topics(session, learner)
    progress = {
        row.lab_id: row
        for row in session.scalars(
            select(LabProgress).where(LabProgress.learner_id == learner.id)
        )
    }
    counts: dict[str, int] = {
        lab_id: number
        for lab_id, number in session.execute(
            select(LabValidation.lab_id, func.count())
            .where(LabValidation.learner_id == learner.id)
            .group_by(LabValidation.lab_id)
        )
    }
    latest: dict[str, LabValidation] = {}
    for row in session.scalars(
        select(LabValidation)
        .where(LabValidation.learner_id == learner.id)
        .order_by(LabValidation.id)
    ):
        latest[row.lab_id] = row
    return [
        _lab_summary(
            lab,
            topics,
            progress.get(lab.id),
            counts.get(lab.id, 0),
            latest.get(lab.id),
        )
        for lab in LABS.values()
    ]


@router.get("/labs/{lab_id}")
def get_lab(lab_id: LabPath, session: SessionDep, learner: LearnerDep) -> LabDetail:
    return _lab_detail(session, learner, _lab(lab_id))


def _seed(session: Session, world: World, learner: Learner, lab: Lab) -> None:
    ids: dict[str, int] = {}
    for seed in lab.seeds:
        props = {
            key: ids[value[1:]]
            if isinstance(value, str) and value.startswith("@")
            else value
            for key, value in seed.properties.items()
        }
        parent_id = ids[seed.parent] if seed.parent else None
        try:
            row = engine.create(
                session,
                world,
                learner.id,
                seed.resource_type,
                parent_id,
                seed.name,
                props,
            )
        except Conflict as error:
            raise Conflict(
                f"Can't set up the lab: {error} Delete or purge that resource, then start again."
            ) from error
        if seed.load_sample:
            engine.act(session, world, row, "load_sample", {})
        ids[seed.name] = row.id


@router.post("/labs/{lab_id}/start")
def start_lab(lab_id: LabPath, session: SessionDep, learner: LearnerDep) -> LabDetail:
    """Idempotent. The first start creates the lab's starter resources."""
    lab = _lab(lab_id)

    def operation() -> World:
        world = engine.open_sandbox(session, learner.id)
        if _progress(session, learner, lab.id) is None:
            session.add(
                LabProgress(
                    learner_id=learner.id,
                    lab_id=lab.id,
                    status="in_progress",
                    started_at=engine.now(),
                    resets=0,
                    hints={},
                )
            )
            if world.group_named(lab.resource_group) is None:
                _seed(session, world, learner, lab)
        return world

    world = _write(session, operation)
    return _lab_detail(session, learner, lab, world)


def _started(session: Session, learner: Learner, lab: Lab) -> LabProgress:
    progress = _progress(session, learner, lab.id, lock=True)
    if progress is None:
        raise Conflict("Start the lab first.")
    return progress


@router.post("/labs/{lab_id}/reset")
def reset_lab(lab_id: LabPath, session: SessionDep, learner: LearnerDep) -> LabDetail:
    """Deletes only this lab's resource group, then recreates its starter resources.
    Completion records, validation history and revealed hints are kept."""
    lab = _lab(lab_id)

    def operation() -> World:
        world = engine.open_sandbox(session, learner.id)
        progress = _started(session, learner, lab)
        group = world.group_named(lab.resource_group)
        if group is not None:
            engine.delete(session, world, group, group.name)
        for row in list(world.rows.values()):
            deleted_from = row.outputs.get("deleted_from") or ""
            if (
                row.state == "soft_deleted"
                and deleted_from.lower() == lab.resource_group.lower()
            ):
                engine.purge(session, world, row)
        _seed(session, world, learner, lab)
        progress.resets += 1
        return world

    world = _write(session, operation)
    return _lab_detail(session, learner, lab, world)


@router.post("/labs/{lab_id}/validate")
def validate_lab(
    lab_id: LabPath, body: ValidateRequest, session: SessionDep, learner: LearnerDep
) -> LabDetail:
    """Grades stored state. Idempotent on client_validation_id."""
    lab = _lab(lab_id)

    def operation() -> World:
        world = engine.open_sandbox(session, learner.id)
        progress = _started(session, learner, lab)
        stored = session.scalar(
            select(LabValidation).where(
                LabValidation.learner_id == learner.id,
                LabValidation.client_validation_id == body.client_validation_id,
            )
        )
        if stored is not None:
            if stored.lab_id != lab.id:
                raise Conflict("That validation id was already used for another lab.")
            return world
        results = grade(lab, world)
        passed = all(r["passed"] for r in results)
        at = engine.now()
        session.add(
            LabValidation(
                learner_id=learner.id,
                lab_id=lab.id,
                client_validation_id=body.client_validation_id,
                passed=passed,
                passed_checks=sum(r["passed"] for r in results),
                total_checks=len(results),
                results=results,
                created_at=at,
            )
        )
        if passed and progress.status != "completed":
            progress.status = "completed"
            progress.completed_at = progress.completed_at or at
        return world

    world = _write(session, operation)
    return _lab_detail(session, learner, lab, world)


@router.post("/labs/{lab_id}/hints")
def reveal_hint(
    lab_id: LabPath, body: HintRequest, session: SessionDep, learner: LearnerDep
) -> LabDetail:
    """Reveals hints up to `level`. Repeating a request changes nothing."""
    lab = _lab(lab_id)
    check = next((c for c in lab.checks if c.id == body.check_id), None)
    if check is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Check not found")

    def operation() -> None:
        progress = _started(session, learner, lab)
        level = min(body.level, len(check.hints))
        if progress.hints.get(check.id, 0) < level:
            progress.hints = {**progress.hints, check.id: level}

    _write(session, operation)
    return _lab_detail(session, learner, lab)


@router.post("/labs/{lab_id}/assistant")
def ask_assistant(
    lab_id: LabPath, body: AssistantRequest, session: SessionDep, learner: LearnerDep
) -> AssistantReply:
    """Explains, never grades. Stores nothing, so a failed model call loses nothing."""
    lab = _lab(lab_id)
    world = engine.read_world(session, learner.id)
    progress = _progress(session, learner, lab.id)
    history = _validations(session, learner, lab.id)
    messages = assistant.build_messages(
        lab,
        world,
        history[0].results if history else None,
        progress.hints if progress else {},
        body.question,
    )
    # Don't hold a database connection through a slow model call.
    session.commit()
    llm.reserve(learner.id)
    reply = llm.complete(messages)
    answer = llm.clean_model_text(reply.text, 0)
    if not answer:
        raise llm.invalid_output("The AI model returned an empty response. Try again.")
    return AssistantReply(
        answer=answer, llm_model=reply.model, llm_provider=reply.provider
    )
