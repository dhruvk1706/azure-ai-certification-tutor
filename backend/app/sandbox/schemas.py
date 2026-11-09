"""Request and response shapes for the sandbox. Requests are the trust boundary."""

from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from app.learning.schemas import Id, SyllabusRef, Timestamp
from app.sandbox.assistant import MAX_QUESTION_CHARS

ClientId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
SIMULATED_NOTICE = (
    "Simulated environment. No Azure subscription, resources or charges are involved, "
    "and nothing here is real Azure state. Inspired by the Azure portal; not affiliated "
    "with or endorsed by Microsoft."
)
ASSISTANT_NOTICE = (
    "AI-generated guidance about a simulation. It can be wrong, and only Validate "
    "grades your work."
)


def _without_nul(value: str) -> str:
    return value.replace("\x00", "").strip()


class Catalog(BaseModel):
    notice: str = SIMULATED_NOTICE
    types: list[dict[str, Any]]
    regions: list[dict[str, Any]]
    models: list[dict[str, Any]]
    sample_prompts: dict[str, str]
    sample_questions: dict[str, str]


class ResourceCreate(BaseModel):
    resource_type: Annotated[str, StringConstraints(max_length=32)]
    parent_id: Id | None = None
    name: Annotated[str, StringConstraints(max_length=128)] = ""
    properties: dict[str, Any] = Field(default_factory=dict)
    client_request_id: ClientId | None = None


class ResourceUpdate(BaseModel):
    properties: dict[str, Any]
    version: Annotated[int, Field(ge=1)]


class ActionRequest(BaseModel):
    input: dict[str, Annotated[str, StringConstraints(max_length=40)]] = Field(
        default_factory=dict, max_length=4
    )


class ResourceSummary(BaseModel):
    id: int
    resource_type: str
    type_label: str
    name: str
    parent_id: int | None
    resource_group: str | None
    resource_group_id: int | None
    region: str | None
    state: str
    updated_at: Timestamp


class OverviewItem(BaseModel):
    label: str
    value: str


class ResourceDetail(ResourceSummary):
    arm_id: str
    version: int
    properties: dict[str, Any]
    references: dict[str, str]
    outputs: dict[str, Any]
    overview: list[OverviewItem]
    issues: list[str]
    children: list[ResourceSummary]
    actions: list[str]
    created_at: Timestamp
    deleted_at: Timestamp | None
    notice: str = SIMULATED_NOTICE


class ActionResult(BaseModel):
    result: dict[str, Any]
    resource: ResourceDetail


class DeleteResult(BaseModel):
    deleted: list[int]
    soft_deleted: list[int]


# --- Labs ---


class ValidateRequest(BaseModel):
    client_validation_id: ClientId


class HintRequest(BaseModel):
    check_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,40}$")]
    level: Annotated[int, Field(ge=1, le=5)]


class AssistantRequest(BaseModel):
    question: Annotated[
        str,
        AfterValidator(_without_nul),
        StringConstraints(min_length=1, max_length=MAX_QUESTION_CHARS),
    ]


class AssistantReply(BaseModel):
    answer: str
    llm_model: str
    llm_provider: str
    notice: str = ASSISTANT_NOTICE


class CheckOut(BaseModel):
    id: str
    description: str
    status: str  # passed, failed or not_checked
    feedback: str | None
    hints: list[str]
    hints_total: int
    explanation: str | None


class TaskOut(BaseModel):
    id: str
    title: str
    checks: list[CheckOut]


class ValidationOut(BaseModel):
    id: int
    passed: bool
    passed_checks: int
    total_checks: int
    created_at: Timestamp


class LabSummary(BaseModel):
    id: str
    title: str
    objective: str
    minutes: int
    resource_group: str
    syllabus: list[SyllabusRef]
    syllabus_text: list[str]
    status: str  # not_started, in_progress or completed
    started_at: Timestamp | None
    completed_at: Timestamp | None
    validations: int
    last_validation: ValidationOut | None


class LabDetail(LabSummary):
    prerequisites: list[str]
    scenario: str
    expected_outcome: str
    instructions: list[str]
    tasks: list[TaskOut]
    completion: str | None
    docs: list[dict[str, str]]
    approximations: list[str]
    resource_group_id: int | None
    resets: int
    history: list[ValidationOut]
    notice: str = SIMULATED_NOTICE
