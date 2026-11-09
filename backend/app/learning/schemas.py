"""API request and response shapes. Requests are the trust boundary, so all are limited."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    StringConstraints,
    model_validator,
)

from app.learning.lessons import Depth
from app.learning.retrieval import ScopeLevel
from app.learning.tutor import MAX_MESSAGE_CHARS

MAX_ID = 2**31 - 1
Id = Annotated[int, Field(ge=1, le=MAX_ID)]
LessonStatus = Literal["in_progress", "completed"]
TopicStatus = Literal["not_started", "in_progress", "completed"]


def _without_nul(value: str) -> str:
    # PostgreSQL text can't hold NUL.
    return value.replace("\x00", "").strip()


def _as_utc(value: datetime) -> datetime:
    # Stored times are UTC, and a browser would read a zoneless one as local time.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


Timestamp = Annotated[datetime, AfterValidator(_as_utc)]


class LearnerCreated(BaseModel):
    id: int
    token: str


# --- Syllabus ---


class SubskillOut(BaseModel):
    id: int
    position: int
    text: str


class SkillOut(BaseModel):
    id: int
    position: int
    name: str
    subskills: list[SubskillOut]


class DomainOut(BaseModel):
    id: int
    position: int
    name: str
    weight_min: int
    weight_max: int
    skills: list[SkillOut]


class SyllabusOut(BaseModel):
    version_number: int
    latest_version_number: int
    exam_code: str
    effective_date: date
    source_url: str
    domains: list[DomainOut]


class SyllabusRef(BaseModel):
    subskill_id: int
    skill_id: int
    domain_id: int
    code: str
    domain: str
    skill: str
    subskill: str
    weight_min: int
    weight_max: int
    version_number: int
    match: str | None = None


# --- Tutor ---


class ConversationCreate(BaseModel):
    title: (
        Annotated[str, AfterValidator(_without_nul), Field(max_length=120)] | None
    ) = None
    scope_level: ScopeLevel | None = None
    scope_id: Id | None = None

    @model_validator(mode="after")
    def _scope_is_complete(self) -> Self:
        if (self.scope_level is None) != (self.scope_id is None):
            raise ValueError("scope_level and scope_id must be given together")
        return self


class MessageCreate(BaseModel):
    content: Annotated[
        str,
        AfterValidator(_without_nul),
        StringConstraints(min_length=1, max_length=MAX_MESSAGE_CHARS),
    ]
    client_message_id: Annotated[
        str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    ]


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    references: list[SyllabusRef]
    llm_model: str | None
    llm_provider: str | None
    created_at: Timestamp


class Exchange(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut


class ConversationOut(BaseModel):
    id: int
    title: str | None
    scope_level: str | None
    scope_id: int | None
    version_number: int
    created_at: Timestamp
    updated_at: Timestamp


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


# --- Lessons ---


class LessonCreate(BaseModel):
    scope_level: ScopeLevel
    scope_id: Id
    depth: Depth


class CheckQuestion(BaseModel):
    """A question as the learner first sees it, with no answer."""

    question: str
    options: list[str]


class CheckResult(BaseModel):
    chosen_index: int
    correct_index: int
    is_correct: bool
    explanation: str


class CheckOutcome(BaseModel):
    score: int
    total: int
    passed: bool
    attempts: int
    submitted_at: Timestamp | None
    results: list[CheckResult]


class LessonProgressOut(BaseModel):
    status: str
    started_at: Timestamp
    completed_at: Timestamp | None
    check: CheckOutcome | None


class AzureExampleOut(BaseModel):
    title: str
    scenario: str


class LessonSummary(BaseModel):
    id: int
    title: str
    scope_level: str
    scope_id: int
    depth: str
    version_number: int
    status: str
    check_score: int | None
    check_total: int | None


class LessonOut(BaseModel):
    id: int
    title: str
    scope_level: str
    scope_id: int
    depth: str
    learning_objectives: list[str]
    explanation: str
    azure_examples: list[AzureExampleOut]
    key_takeaways: list[str]
    checks: list[CheckQuestion]
    references: list[SyllabusRef]
    version_number: int
    llm_model: str
    llm_provider: str
    created_at: Timestamp
    reused: bool
    progress: LessonProgressOut


class CheckSubmit(BaseModel):
    answers: Annotated[list[Annotated[int, Field(ge=0, le=100)]], Field(max_length=20)]


class LessonProgressUpdate(BaseModel):
    status: LessonStatus


class TopicProgressUpdate(BaseModel):
    status: TopicStatus


class TopicProgressOut(BaseModel):
    subskill_id: int
    version_number: int
    status: str
    started_at: Timestamp | None
    completed_at: Timestamp | None
    updated_at: Timestamp


# --- Plan and dashboard ---


class PlanInputs(BaseModel):
    familiarity: dict[Id, Annotated[int, Field(ge=0, le=3)]]
    weekly_hours: Annotated[int, Field(ge=1, le=80)]
    exam_date: date | None = None


class PlanUpdate(PlanInputs):
    version_number: Id | None = None


class PlanItem(BaseModel):
    topic: SyllabusRef
    status: str
    kind: str
    minutes: int
    reason: str
    week: int
    week_start: date
    after_exam: bool


class PlanSummary(BaseModel):
    remaining_topics: int
    remaining_minutes: int
    weeks_needed: int
    projected_finish: date
    exam_date: date | None
    days_until_exam: int | None
    on_track: bool | None
    required_weekly_hours: int | None


class PlanOut(BaseModel):
    version_number: int
    latest_version_number: int
    inputs: PlanInputs | None
    summary: PlanSummary | None
    items: list[PlanItem]


class PlanExplanation(BaseModel):
    text: str
    llm_model: str
    llm_provider: str


class CountOut(BaseModel):
    completed: int
    in_progress: int
    total: int
    percent: int


class DomainCount(CountOut):
    domain_id: int
    position: int
    name: str
    weight_min: int
    weight_max: int


class WeakArea(BaseModel):
    topic: SyllabusRef
    reason: str


class NextLesson(BaseModel):
    topic: SyllabusRef
    kind: str
    minutes: int
    reason: str


class Dashboard(BaseModel):
    version_number: int
    latest_version_number: int
    has_plan: bool
    overall: CountOut
    domains: list[DomainCount]
    weak_areas: list[WeakArea]
    next_lesson: NextLesson | None
    lessons_completed: int
    checks_submitted: int
    checks_passed: int
    last_activity_at: Timestamp | None
