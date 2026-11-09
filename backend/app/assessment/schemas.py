"""Request and response shapes for the question bank, attempts and analytics.

Requests carry option indexes only. Correct answers and explanations appear in a
response only after the server has graded that answer.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.assessment.generation import Difficulty, Kind
from app.learning.retrieval import ScopeLevel
from app.learning.schemas import Id, SyllabusRef, Timestamp

MAX_QUESTIONS = 60
MAX_TIME_LIMIT_MINUTES = 240
Mode = Literal["practice", "mock"]
NOT_OFFICIAL = (
    "Original practice questions written by AI and checked against Microsoft Learn "
    "excerpts. They are not official Microsoft certification questions, and scores "
    "do not predict an exam result."
)


class SourceOut(BaseModel):
    id: int
    title: str
    url: str
    retrieved_at: Timestamp


class BankObjective(BaseModel):
    topic: SyllabusRef
    sources: list[SourceOut]
    questions: int
    by_difficulty: dict[str, int]


class BankOut(BaseModel):
    version_number: int
    latest_version_number: int
    total_questions: int
    notice: str = NOT_OFFICIAL
    objectives: list[BankObjective]


class GenerateRequest(BaseModel):
    subskill_id: Id
    count: Annotated[int, Field(ge=1, le=5)] = 3
    difficulty: Difficulty = "medium"
    kind: Kind = "mcq"


class Rejection(BaseModel):
    stem: str
    reason: str


class GenerateResult(BaseModel):
    accepted: int
    rejected: list[Rejection]
    active_questions: int
    llm_model: str
    llm_provider: str


class AttemptCreate(BaseModel):
    client_attempt_id: Annotated[
        str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    ]
    mode: Mode
    adaptive: bool = False
    scope_level: ScopeLevel | None = None
    scope_id: Id | None = None
    difficulty: Difficulty | None = None
    question_count: Annotated[int, Field(ge=1, le=MAX_QUESTIONS)]
    time_limit_minutes: (
        Annotated[int, Field(ge=1, le=MAX_TIME_LIMIT_MINUTES)] | None
    ) = None
    version_number: Id | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.scope_level is None) != (self.scope_id is None):
            raise ValueError("scope_level and scope_id must be given together")
        if self.mode == "mock":
            if self.time_limit_minutes is None:
                raise ValueError("a mock exam needs time_limit_minutes")
            if self.scope_level or self.adaptive or self.difficulty:
                raise ValueError("a mock exam covers the whole syllabus")
        else:
            if self.time_limit_minutes is not None:
                raise ValueError("practice quizzes are not timed")
            if self.adaptive == (self.scope_level is not None):
                raise ValueError("choose a topic, or adaptive practice, not both")
        return self


class AnswerSubmit(BaseModel):
    chosen_index: Annotated[int, Field(ge=0, le=9, strict=True)]


class SourceRef(BaseModel):
    title: str
    url: str
    excerpt: str


class Feedback(BaseModel):
    chosen_index: int | None
    correct_index: int
    is_correct: bool
    explanation: str
    source: SourceRef
    topic: SyllabusRef


class AttemptItem(BaseModel):
    position: int
    kind: str
    difficulty: str
    scenario: str | None
    stem: str
    options: list[str]
    chosen_index: int | None
    feedback: Feedback | None


class AttemptSummary(BaseModel):
    id: int
    mode: str
    selection: str
    scope_level: str | None
    scope_id: int | None
    version_number: int
    status: str
    question_count: int
    answered_count: int
    score: int | None
    percent: int | None
    passed: bool | None
    started_at: Timestamp
    deadline_at: Timestamp | None
    submitted_at: Timestamp | None
    submit_reason: str | None


class AttemptOut(AttemptSummary):
    difficulty: str | None
    time_limit_seconds: int | None
    server_time: Timestamp
    remaining_seconds: int | None
    pass_percent: int
    notice: str = NOT_OFFICIAL
    items: list[AttemptItem]


class Area(BaseModel):
    answered: int
    correct: int
    percent: int | None
    standing: str


class DomainPerformance(Area):
    domain_id: int
    position: int
    name: str
    weight_min: int
    weight_max: int


class SkillPerformance(Area):
    skill_id: int
    domain_id: int
    code: str
    name: str


class Recommendation(BaseModel):
    topic: SyllabusRef
    answered: int
    correct: int
    percent: int | None
    reason: str
    available_questions: int


class Analytics(BaseModel):
    version_number: int
    latest_version_number: int
    answered: int
    correct: int
    percent: int | None
    readiness_percent: int | None
    readiness: str
    pass_percent: int
    mock_exams_taken: int
    latest_mock_percent: int | None
    best_mock_percent: int | None
    domains: list[DomainPerformance]
    skills: list[SkillPerformance]
    recommendations: list[Recommendation]
    attempts: list[AttemptSummary]
    notice: str = NOT_OFFICIAL
