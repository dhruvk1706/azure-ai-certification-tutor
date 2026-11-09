/** The only module that talks to the backend. Types mirror backend/app/learning/schemas.py. */

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "tutor.learnerToken";

export type ScopeLevel = "domain" | "skill" | "subskill";
export type Depth = "beginner" | "intermediate" | "advanced";
export type TopicStatus = "not_started" | "in_progress" | "completed";

export interface SyllabusRef {
  subskill_id: number;
  skill_id: number;
  domain_id: number;
  code: string;
  domain: string;
  skill: string;
  subskill: string;
  weight_min: number;
  weight_max: number;
  version_number: number;
  match: string | null;
}

export interface Subskill {
  id: number;
  position: number;
  text: string;
}
export interface Skill {
  id: number;
  position: number;
  name: string;
  subskills: Subskill[];
}
export interface Domain {
  id: number;
  position: number;
  name: string;
  weight_min: number;
  weight_max: number;
  skills: Skill[];
}
export interface Syllabus {
  version_number: number;
  latest_version_number: number;
  exam_code: string;
  effective_date: string;
  source_url: string;
  domains: Domain[];
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  references: SyllabusRef[];
  llm_model: string | null;
  llm_provider: string | null;
  created_at: string;
}
export interface Conversation {
  id: number;
  title: string | null;
  scope_level: ScopeLevel | null;
  scope_id: number | null;
  version_number: number;
  created_at: string;
  updated_at: string;
}
export interface ConversationDetail extends Conversation {
  messages: Message[];
}
export interface Exchange {
  user_message: Message;
  assistant_message: Message;
}

export interface CheckOutcome {
  score: number;
  total: number;
  passed: boolean;
  attempts: number;
  submitted_at: string | null;
  results: {
    chosen_index: number;
    correct_index: number;
    is_correct: boolean;
    explanation: string;
  }[];
}
export interface LessonSummary {
  id: number;
  title: string;
  scope_level: ScopeLevel;
  scope_id: number;
  depth: Depth;
  version_number: number;
  status: string;
  check_score: number | null;
  check_total: number | null;
}
export interface Lesson {
  id: number;
  title: string;
  scope_level: ScopeLevel;
  scope_id: number;
  depth: Depth;
  learning_objectives: string[];
  explanation: string;
  azure_examples: { title: string; scenario: string }[];
  key_takeaways: string[];
  checks: { question: string; options: string[] }[];
  references: SyllabusRef[];
  version_number: number;
  llm_model: string;
  llm_provider: string;
  created_at: string;
  reused: boolean;
  progress: {
    status: string;
    started_at: string;
    completed_at: string | null;
    check: CheckOutcome | null;
  };
}

export interface PlanInputs {
  familiarity: Record<string, number>;
  weekly_hours: number;
  exam_date: string | null;
}
export interface PlanItem {
  topic: SyllabusRef;
  status: TopicStatus;
  kind: "learn" | "review";
  minutes: number;
  reason: string;
  week: number;
  week_start: string;
  after_exam: boolean;
}
export interface Plan {
  version_number: number;
  latest_version_number: number;
  inputs: PlanInputs | null;
  summary: {
    remaining_topics: number;
    remaining_minutes: number;
    weeks_needed: number;
    projected_finish: string;
    exam_date: string | null;
    days_until_exam: number | null;
    on_track: boolean | null;
    required_weekly_hours: number | null;
  } | null;
  items: PlanItem[];
}

export interface Count {
  completed: number;
  in_progress: number;
  total: number;
  percent: number;
}
export interface Dashboard {
  version_number: number;
  latest_version_number: number;
  has_plan: boolean;
  overall: Count;
  domains: (Count & {
    domain_id: number;
    position: number;
    name: string;
    weight_min: number;
    weight_max: number;
  })[];
  weak_areas: { topic: SyllabusRef; reason: string }[];
  next_lesson: {
    topic: SyllabusRef;
    kind: "learn" | "review";
    minutes: number;
    reason: string;
  } | null;
  lessons_completed: number;
  checks_submitted: number;
  checks_passed: number;
  last_activity_at: string | null;
}

// --- Practice and mock exams (backend/app/assessment/schemas.py) ---

export type Difficulty = "easy" | "medium" | "hard";
export type QuestionKind = "mcq" | "scenario";

export interface LearnSourceInfo {
  id: number;
  title: string;
  url: string;
  retrieved_at: string;
}
export interface QuestionBank {
  version_number: number;
  latest_version_number: number;
  total_questions: number;
  notice: string;
  objectives: {
    topic: SyllabusRef;
    sources: LearnSourceInfo[];
    questions: number;
    by_difficulty: Record<string, number>;
  }[];
}
export interface GenerateResult {
  accepted: number;
  rejected: { stem: string; reason: string }[];
  active_questions: number;
  llm_model: string;
  llm_provider: string;
}

export interface AttemptSummary {
  id: number;
  mode: "practice" | "mock";
  selection: "topic" | "adaptive" | "exam";
  scope_level: ScopeLevel | null;
  scope_id: number | null;
  version_number: number;
  status: "in_progress" | "submitted";
  question_count: number;
  answered_count: number;
  score: number | null;
  percent: number | null;
  passed: boolean | null;
  started_at: string;
  deadline_at: string | null;
  submitted_at: string | null;
  submit_reason: "learner" | "completed" | "time_expired" | null;
}
export interface Feedback {
  chosen_index: number | null;
  correct_index: number;
  is_correct: boolean;
  explanation: string;
  source: { title: string; url: string; excerpt: string };
  topic: SyllabusRef;
}
export interface AttemptItem {
  position: number;
  kind: QuestionKind;
  difficulty: Difficulty;
  scenario: string | null;
  stem: string;
  options: string[];
  chosen_index: number | null;
  feedback: Feedback | null;
}
export interface Attempt extends AttemptSummary {
  difficulty: Difficulty | null;
  time_limit_seconds: number | null;
  server_time: string;
  remaining_seconds: number | null;
  pass_percent: number;
  notice: string;
  items: AttemptItem[];
}
export type AttemptRequest =
  | {
      mode: "practice";
      scope_level: ScopeLevel;
      scope_id: number;
      difficulty?: Difficulty;
      question_count: number;
    }
  | { mode: "practice"; adaptive: true; question_count: number }
  | { mode: "mock"; question_count: number; time_limit_minutes: number };

export interface Area {
  answered: number;
  correct: number;
  percent: number | null;
  standing: "strength" | "developing" | "weakness" | "insufficient_data";
}
export interface Analytics {
  version_number: number;
  latest_version_number: number;
  answered: number;
  correct: number;
  percent: number | null;
  readiness_percent: number | null;
  readiness: "likely_ready" | "borderline" | "not_ready" | "insufficient_data";
  pass_percent: number;
  mock_exams_taken: number;
  latest_mock_percent: number | null;
  best_mock_percent: number | null;
  domains: (Area & {
    domain_id: number;
    position: number;
    name: string;
    weight_min: number;
    weight_max: number;
  })[];
  skills: (Area & {
    skill_id: number;
    domain_id: number;
    code: string;
    name: string;
  })[];
  recommendations: {
    topic: SyllabusRef;
    answered: number;
    correct: number;
    percent: number | null;
    reason: "low_accuracy" | "not_attempted";
    available_questions: number;
  }[];
  attempts: AttemptSummary[];
  notice: string;
}

// --- Sandbox simulator and labs (backend/app/sandbox/schemas.py) ---

export type FieldKind =
  | "text"
  | "textarea"
  | "select"
  | "number"
  | "bool"
  | "ref"
  | "strings"
  | "list";
export interface SandboxField {
  key: string;
  label: string;
  kind: FieldKind;
  options: (string | number)[];
  labels: string[];
  default: unknown;
  required: boolean;
  minimum: number | null;
  maximum: number | null;
  integer: boolean;
  max_length: number;
  help: string;
  refs: string[];
  updatable: boolean;
  items: SandboxField[];
  max_items: number;
}
export interface ResourceType {
  key: string;
  label: string;
  arm_type: string;
  parent: string | null;
  description: string;
  docs_url: string;
  fields: SandboxField[];
  name_help: string;
  soft_delete: boolean;
  auto_name: boolean;
  updatable: boolean;
  actions: string[];
  note: string;
}
export interface SandboxCatalog {
  notice: string;
  types: ResourceType[];
  regions: { name: string; label: string; data_zone: string | null }[];
  models: {
    name: string;
    kind: string;
    versions: string[];
    deployment_types: string[];
    max_dimensions: number | null;
  }[];
  sample_prompts: Record<string, string>;
  sample_questions: Record<string, string>;
}
export interface ResourceSummary {
  id: number;
  resource_type: string;
  type_label: string;
  name: string;
  parent_id: number | null;
  resource_group: string | null;
  resource_group_id: number | null;
  region: string | null;
  state: string;
  updated_at: string;
}
export type Properties = Record<string, unknown>;
export interface ResourceDetail extends ResourceSummary {
  arm_id: string;
  version: number;
  properties: Properties;
  references: Record<string, string>;
  outputs: Record<string, unknown>;
  overview: { label: string; value: string }[];
  issues: string[];
  children: ResourceSummary[];
  actions: string[];
  created_at: string;
  deleted_at: string | null;
  notice: string;
}
export interface ActionOutcome {
  result: Record<string, unknown>;
  resource: ResourceDetail;
}
export interface LabCheck {
  id: string;
  description: string;
  status: "passed" | "failed" | "not_checked";
  feedback: string | null;
  hints: string[];
  hints_total: number;
  explanation: string | null;
}
export interface LabValidation {
  id: number;
  passed: boolean;
  passed_checks: number;
  total_checks: number;
  created_at: string;
}
export interface LabSummary {
  id: string;
  title: string;
  objective: string;
  minutes: number;
  resource_group: string;
  syllabus: SyllabusRef[];
  syllabus_text: string[];
  status: "not_started" | "in_progress" | "completed";
  started_at: string | null;
  completed_at: string | null;
  validations: number;
  last_validation: LabValidation | null;
}
export interface LabDetail extends LabSummary {
  prerequisites: string[];
  scenario: string;
  expected_outcome: string;
  instructions: string[];
  tasks: { id: string; title: string; checks: LabCheck[] }[];
  completion: string | null;
  docs: { title: string; url: string }[];
  approximations: string[];
  resource_group_id: number | null;
  resets: number;
  history: LabValidation[];
  notice: string;
}
export interface AssistantReply {
  answer: string;
  llm_model: string;
  llm_provider: string;
  notice: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return memoryToken;
  }
}

function writeToken(token: string | null) {
  memoryToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Blocked storage: the token lasts for this page only.
  }
}

let memoryToken: string | null = null;
let registering: Promise<string> | null = null;

async function call(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_URL}/api${path}`, init);
  } catch {
    throw new ApiError(0, "Could not reach the API. Is the backend running?");
  }
}

async function failure(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => null);
  const detail = typeof body?.detail === "string" ? body.detail : null;
  return new ApiError(
    response.status,
    detail ??
      (response.status === 422
        ? "That input was not accepted. Check it and try again."
        : `The request failed (${response.status}).`),
    body?.code ?? null,
  );
}

/** Registers once, even when several requests arrive together on first load. */
function learnerToken(): Promise<string> {
  const stored = readToken();
  if (stored) return Promise.resolve(stored);
  registering ??= (async () => {
    const response = await call("/learners", { method: "POST" });
    if (!response.ok) throw await failure(response);
    const { token } = (await response.json()) as { token: string };
    writeToken(token);
    return token;
  })().finally(() => {
    registering = null;
  });
  return registering;
}

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
  isRetry = false,
): Promise<T> {
  const token = await learnerToken();
  const response = await call(path, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401 && !isRetry) {
    // The token is unknown, for example after the database was reset.
    if (readToken() === token) writeToken(null);
    return request<T>(path, method, body, true);
  }
  if (!response.ok) throw await failure(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function versionQuery(version?: number) {
  return version === undefined ? "" : `?version=${version}`;
}

export const api = {
  syllabus: (version?: number) =>
    request<Syllabus>(`/syllabus${versionQuery(version)}`),

  conversations: () => request<Conversation[]>("/conversations"),
  conversation: (id: number) =>
    request<ConversationDetail>(`/conversations/${id}`),
  createConversation: (scope?: { scope_level: ScopeLevel; scope_id: number }) =>
    request<Conversation>("/conversations", "POST", scope ?? {}),
  sendMessage: (id: number, content: string, clientMessageId: string) =>
    request<Exchange>(`/conversations/${id}/messages`, "POST", {
      content,
      client_message_id: clientMessageId,
    }),

  lessons: () => request<LessonSummary[]>("/lessons"),
  lesson: (id: number) => request<Lesson>(`/lessons/${id}`),
  openLesson: (scope_level: ScopeLevel, scope_id: number, depth: Depth) =>
    request<Lesson>("/lessons", "POST", { scope_level, scope_id, depth }),
  setLessonStatus: (id: number, status: "in_progress" | "completed") =>
    request<Lesson>(`/lessons/${id}/progress`, "PUT", { status }),
  submitChecks: (id: number, answers: number[]) =>
    request<Lesson>(`/lessons/${id}/checks`, "POST", { answers }),

  plan: (version?: number) => request<Plan>(`/plan${versionQuery(version)}`),
  savePlan: (inputs: PlanInputs, versionNumber?: number) =>
    request<Plan>("/plan", "PUT", { ...inputs, version_number: versionNumber }),
  clearPlan: () => request<void>("/plan", "DELETE"),
  explainPlan: (version?: number) =>
    request<{ text: string; llm_model: string; llm_provider: string }>(
      `/plan/explanation${versionQuery(version)}`,
      "POST",
    ),

  dashboard: () => request<Dashboard>("/dashboard"),
  clearProgress: () => request<void>("/progress", "DELETE"),
  clearMemory: () => request<void>("/conversations", "DELETE"),

  questionBank: () => request<QuestionBank>("/questions/bank"),
  generateQuestions: (
    subskillId: number,
    count: number,
    difficulty: Difficulty,
    kind: QuestionKind,
  ) =>
    request<GenerateResult>("/questions/generate", "POST", {
      subskill_id: subskillId,
      count,
      difficulty,
      kind,
    }),

  attempts: () => request<AttemptSummary[]>("/attempts"),
  attempt: (id: number) => request<Attempt>(`/attempts/${id}`),
  startAttempt: (body: AttemptRequest, clientAttemptId: string) =>
    request<Attempt>("/attempts", "POST", {
      ...body,
      client_attempt_id: clientAttemptId,
    }),
  answer: (id: number, position: number, chosenIndex: number) =>
    request<Attempt>(`/attempts/${id}/answers/${position}`, "PUT", {
      chosen_index: chosenIndex,
    }),
  submitAttempt: (id: number) =>
    request<Attempt>(`/attempts/${id}/submit`, "POST"),

  analytics: (version?: number) =>
    request<Analytics>(`/analytics${versionQuery(version)}`),

  sandboxCatalog: () => request<SandboxCatalog>("/sandbox/catalog"),
  sandboxResources: (q = "") =>
    request<ResourceSummary[]>(
      `/sandbox/resources${q ? `?q=${encodeURIComponent(q)}` : ""}`,
    ),
  sandboxDeleted: () => request<ResourceSummary[]>("/sandbox/deleted"),
  sandboxResource: (id: number) =>
    request<ResourceDetail>(`/sandbox/resources/${id}`),
  createResource: (body: {
    resource_type: string;
    name: string;
    parent_id: number | null;
    properties: Properties;
    client_request_id: string;
  }) => request<ResourceDetail>("/sandbox/resources", "POST", body),
  updateResource: (id: number, properties: Properties, version: number) =>
    request<ResourceDetail>(`/sandbox/resources/${id}`, "PUT", {
      properties,
      version,
    }),
  deleteResource: (id: number, confirmName?: string) =>
    request<{ deleted: number[]; soft_deleted: number[] }>(
      `/sandbox/resources/${id}${
        confirmName ? `?confirm_name=${encodeURIComponent(confirmName)}` : ""
      }`,
      "DELETE",
    ),
  resourceAction: (id: number, action: string, input: Record<string, string>) =>
    request<ActionOutcome>(
      `/sandbox/resources/${id}/actions/${action}`,
      "POST",
      { input },
    ),

  labs: () => request<LabSummary[]>("/sandbox/labs"),
  lab: (id: string) => request<LabDetail>(`/sandbox/labs/${id}`),
  startLab: (id: string) =>
    request<LabDetail>(`/sandbox/labs/${id}/start`, "POST"),
  resetLab: (id: string) =>
    request<LabDetail>(`/sandbox/labs/${id}/reset`, "POST"),
  validateLab: (id: string, clientValidationId: string) =>
    request<LabDetail>(`/sandbox/labs/${id}/validate`, "POST", {
      client_validation_id: clientValidationId,
    }),
  revealHint: (id: string, checkId: string, level: number) =>
    request<LabDetail>(`/sandbox/labs/${id}/hints`, "POST", {
      check_id: checkId,
      level,
    }),
  askLabAssistant: (id: string, question: string) =>
    request<AssistantReply>(`/sandbox/labs/${id}/assistant`, "POST", {
      question,
    }),
};
