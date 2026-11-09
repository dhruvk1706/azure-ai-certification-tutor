// @vitest-environment jsdom
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../../frontend/src/App";

/** A route table standing in for the backend. Each handler sees the parsed request. */
type Handler = (body: unknown, request: RecordedCall) => unknown;
interface RecordedCall {
  method: string;
  path: string;
  body: unknown;
  authorization: string | null;
}

class Failure {
  readonly status: number;
  readonly detail: string;
  readonly code?: string;

  constructor(status: number, detail: string, code?: string) {
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

const SYLLABUS = {
  version_number: 1,
  latest_version_number: 1,
  exam_code: "AI-103",
  effective_date: "2026-04-16",
  source_url: "https://example.test",
  domains: [
    {
      id: 1,
      position: 1,
      name: "Plan and manage",
      weight_min: 25,
      weight_max: 30,
      skills: [
        {
          id: 10,
          position: 1,
          name: "Select services",
          subskills: [
            { id: 100, position: 1, text: "Choose a retrieval approach" },
          ],
        },
      ],
    },
  ],
};

const REFERENCE = {
  subskill_id: 100,
  skill_id: 10,
  domain_id: 1,
  code: "1.1.1",
  domain: "Plan and manage",
  skill: "Select services",
  subskill: "Choose a retrieval approach",
  weight_min: 25,
  weight_max: 30,
  version_number: 1,
  match: "search",
};

const COUNT = { completed: 0, in_progress: 0, total: 1, percent: 0 };

const DASHBOARD = {
  version_number: 1,
  latest_version_number: 1,
  has_plan: false,
  overall: COUNT,
  domains: [
    {
      ...COUNT,
      domain_id: 1,
      position: 1,
      name: "Plan and manage",
      weight_min: 25,
      weight_max: 30,
    },
  ],
  weak_areas: [],
  next_lesson: {
    topic: REFERENCE,
    kind: "learn",
    minutes: 60,
    reason: "Domain weight 25-30%.",
  },
  lessons_completed: 0,
  checks_submitted: 0,
  checks_passed: 0,
  last_activity_at: null,
};

const LESSON = {
  id: 7,
  title: "Choosing retrieval",
  scope_level: "subskill",
  scope_id: 100,
  depth: "beginner",
  learning_objectives: ["Compare approaches"],
  explanation: "Retrieval finds text.",
  azure_examples: [{ title: "Support bot", scenario: "Index help pages." }],
  key_takeaways: ["Fit the index to the data"],
  checks: [{ question: "Which one?", options: ["Right", "Wrong"] }],
  references: [{ ...REFERENCE, match: "lesson_scope" }],
  version_number: 1,
  llm_model: "test-model",
  llm_provider: "llm.test",
  created_at: "2026-11-07T00:00:00Z",
  reused: false,
  progress: {
    status: "in_progress",
    started_at: "2026-11-07T00:00:00Z",
    completed_at: null,
    check: null,
  },
};

const PLAN_ITEM = {
  topic: REFERENCE,
  status: "not_started",
  kind: "learn",
  minutes: 60,
  reason: "Domain weight 25-30%.",
  week: 1,
  week_start: "2026-11-07",
  after_exam: false,
};

const SUMMARY = {
  remaining_topics: 1,
  remaining_minutes: 60,
  weeks_needed: 1,
  projected_finish: "2026-11-14",
  exam_date: null,
  days_until_exam: null,
  on_track: null,
  required_weekly_hours: null,
};

function message(
  id: number,
  role: string,
  content: string,
  references: unknown[] = [],
) {
  return {
    id,
    role,
    content,
    references,
    llm_model: role === "assistant" ? "test-model" : null,
    llm_provider: role === "assistant" ? "llm.test" : null,
    created_at: "2026-11-07T00:00:00Z",
  };
}

let routes: Record<string, Handler>;
let calls: RecordedCall[];
let container: HTMLElement;
let root: Root;

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status });
}

async function fakeFetch(url: string, init: RequestInit = {}) {
  const path = url.replace(/^.*\/api/, "");
  const method = init.method ?? "GET";
  const call = {
    method,
    path,
    body: init.body ? JSON.parse(init.body as string) : undefined,
    authorization: new Headers(init.headers).get("Authorization"),
  };
  calls.push(call);
  const handler = routes[`${method} ${path}`];
  if (!handler) return respond(404, { detail: `No route ${method} ${path}` });
  try {
    return respond(200, handler(call.body, call));
  } catch (error) {
    if (error instanceof Failure) {
      return respond(error.status, { detail: error.detail, code: error.code });
    }
    throw error;
  }
}

function open(hash: string) {
  window.location.hash = hash;
  root = createRoot(container);
  root.render(<App />);
}

function see(text: string) {
  return vi.waitFor(() => expect(container.textContent).toContain(text), {
    timeout: 2000,
  });
}

function button(label: string) {
  const match = [...container.querySelectorAll("button")].find((element) =>
    element.textContent?.includes(label),
  );
  if (!match) throw new Error(`no button ${label}`);
  return match;
}

/** Sets a value the way a browser does, so React's controlled inputs notice it. */
function setValue(
  element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
  value: string,
) {
  const prototype = Object.getPrototypeOf(element);
  Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(
    element,
    value,
  );
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function callsTo(method: string, path: string) {
  return calls.filter((call) => call.method === method && call.path === path);
}

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "";
  calls = [];
  routes = {
    "POST /learners": () => ({ id: 1, token: "learner-token" }),
    "GET /syllabus": () => SYLLABUS,
    "GET /dashboard": () => DASHBOARD,
    "GET /conversations": () => [],
    "GET /lessons": () => [],
    "GET /plan": () => ({
      version_number: 1,
      latest_version_number: 1,
      inputs: null,
      summary: null,
      items: [],
    }),
  };
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
  container = document.createElement("div");
  document.body.append(container);
});

afterEach(() => {
  root?.unmount();
  container.remove();
  vi.unstubAllGlobals();
  // A request still in flight must never reach a real backend on :8000.
  vi.stubGlobal("fetch", () => Promise.reject(new TypeError("test over")));
});

test("registers one learner and shows the dashboard", async () => {
  open("#/dashboard");
  await see("Choose a retrieval approach");

  expect(container.textContent).toContain("0 of 1 objectives");
  expect(callsTo("POST", "/learners")).toHaveLength(1);
  expect(callsTo("GET", "/dashboard")[0].authorization).toBe(
    "Bearer learner-token",
  );
  expect(localStorage.getItem("tutor.learnerToken")).toBe("learner-token");
});

test("a new learner's dashboard explains what is missing instead of inventing it", async () => {
  routes["GET /analytics"] = () => ({ answered: 0, recommendations: [] });
  open("#/dashboard");
  await see("welcome aboard");
  expect(container.textContent).toContain("Start learning");
  expect(container.textContent).toContain("No weekly goal yet");
  expect(container.textContent).toContain("No practice answers yet");
  expect(container.textContent).toContain("No weak areas yet");
  expect(container.querySelector('a[href="#/tutor"]')).not.toBeNull();
  expect(container.querySelector('a[href="#/plan"]')).not.toBeNull();
  expect(container.textContent).not.toMatch(/\bXP\b|streak/i);
});

test("the dashboard shows the weekly goal and assessment-based weak areas", async () => {
  routes["GET /dashboard"] = () => ({
    ...DASHBOARD,
    has_plan: true,
    overall: { completed: 1, in_progress: 0, total: 2, percent: 50 },
    checks_submitted: 1,
    weak_areas: [{ topic: REFERENCE, reason: "failed_check" }],
  });
  routes["GET /plan"] = () => ({
    version_number: 1,
    latest_version_number: 1,
    inputs: { familiarity: {}, weekly_hours: 2, exam_date: null },
    summary: SUMMARY,
    items: [PLAN_ITEM],
  });
  routes["GET /analytics"] = () => ({
    answered: 4,
    readiness: "borderline",
    readiness_percent: 63,
    recommendations: [
      {
        topic: REFERENCE,
        answered: 4,
        correct: 1,
        percent: 25,
        reason: "low_accuracy",
        available_questions: 6,
      },
    ],
  });
  open("#/dashboard");
  await see("welcome back");
  expect(container.textContent).toContain("Continue learning");
  await see("Planned this week");
  // One 60-minute objective against a 2-hour goal.
  expect(container.textContent).toContain("1 of 2 h");
  await see("Borderline · 63%");
  expect(container.textContent).toContain("1 of 4 correct");
  expect(container.textContent).toContain("Comprehension check not passed");
  expect(
    container.querySelector('a[href="#/practice?level=subskill&id=100"]'),
  ).not.toBeNull();
});

test("several requests on first load still register only one learner", async () => {
  open("#/tutor");
  await see("No conversation open");
  expect(callsTo("POST", "/learners")).toHaveLength(1);
});

test("keeps the stored learner across a reload", async () => {
  localStorage.setItem("tutor.learnerToken", "existing");
  open("#/dashboard");
  await see("Overall completion");
  expect(callsTo("POST", "/learners")).toHaveLength(0);
  expect(callsTo("GET", "/dashboard")[0].authorization).toBe("Bearer existing");
});

test("replaces a token the backend no longer knows", async () => {
  localStorage.setItem("tutor.learnerToken", "stale");
  routes["GET /dashboard"] = (_, call) => {
    if (call.authorization === "Bearer stale") {
      throw new Failure(401, "unknown");
    }
    return DASHBOARD;
  };
  open("#/dashboard");
  await see("Overall completion");
  expect(localStorage.getItem("tutor.learnerToken")).toBe("learner-token");
});

test("explains a missing syllabus instead of showing a bare error", async () => {
  const missing = () => {
    throw new Failure(404, "No syllabus has been ingested yet.");
  };
  routes["GET /dashboard"] = missing;
  open("#/dashboard");
  await see("No syllabus has been ingested yet");
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(container.textContent).toContain("python -m app.syllabus.ingest");
});

test("a failed load can be retried", async () => {
  let failing = true;
  routes["GET /dashboard"] = () => {
    if (failing) throw new Failure(503, "The database is unavailable.");
    return DASHBOARD;
  };
  open("#/dashboard");
  await see("The database is unavailable.");

  failing = false;
  button("Try again").click();
  await see("Overall completion");
});

function tutorRoutes() {
  routes["GET /conversations"] = () => [
    {
      id: 3,
      title: "Earlier question",
      scope_level: null,
      scope_id: null,
      version_number: 1,
      created_at: "2026-11-07T00:00:00Z",
      updated_at: "2026-11-07T00:00:00Z",
    },
  ];
  routes["GET /conversations/3"] = () => ({
    id: 3,
    title: "Earlier question",
    scope_level: null,
    scope_id: null,
    version_number: 1,
    created_at: "2026-11-07T00:00:00Z",
    updated_at: "2026-11-07T00:00:00Z",
    messages: [
      message(1, "user", "Earlier question"),
      message(2, "assistant", "Earlier answer [1].", [REFERENCE]),
    ],
  });
}

test("tutor shows stored history with explanation and sources kept apart", async () => {
  tutorRoutes();
  open("#/tutor/3");
  await see("Earlier answer [1].");

  expect(container.textContent).toContain("Tutor explanation · AI-generated");
  expect(container.textContent).toContain("Syllabus source");
  expect(container.textContent).toContain(
    "[1] 1.1.1 Choose a retrieval approach",
  );
  expect(container.textContent).toContain("Matched your question");
});

test("tutor says so when an answer has no syllabus reference", async () => {
  tutorRoutes();
  routes["POST /conversations/3/messages"] = () => ({
    user_message: message(3, "user", "Capital of France?"),
    assistant_message: message(4, "assistant", "This is outside the syllabus."),
  });
  open("#/tutor/3");
  await see("Earlier answer");

  setValue(container.querySelector("textarea")!, "Capital of France?");
  await vi.waitFor(() => expect(button("Send").disabled).toBe(false));
  button("Send").click();

  await see("This is outside the syllabus.");
  expect(container.textContent).toContain("No syllabus reference matched");
  expect(container.querySelector("textarea")!.value).toBe("");
});

test("a failed send keeps the question and retries as the same message", async () => {
  tutorRoutes();
  let failing = true;
  routes["POST /conversations/3/messages"] = () => {
    if (failing) {
      throw new Failure(
        503,
        "The AI model could not be reached.",
        "llm_unavailable",
      );
    }
    return {
      user_message: message(3, "user", "Why?"),
      assistant_message: message(4, "assistant", "Because [1].", [REFERENCE]),
    };
  };
  open("#/tutor/3");
  await see("Earlier answer");

  setValue(container.querySelector("textarea")!, "Why?");
  await vi.waitFor(() => expect(button("Send").disabled).toBe(false));
  button("Send").click();

  await see("The AI model could not be reached.");
  expect(container.querySelector("textarea")!.value).toBe("Why?");
  expect(container.textContent).toContain("Earlier answer");

  failing = false;
  button("Send again").click();
  await see("Because [1].");

  const sends = callsTo("POST", "/conversations/3/messages");
  expect(sends).toHaveLength(2);
  expect(
    (sends[0].body as { client_message_id: string }).client_message_id,
  ).toBe((sends[1].body as { client_message_id: string }).client_message_id);
});

test("lesson flow: generate, check answers, complete", async () => {
  routes["POST /lessons"] = () => LESSON;
  routes["GET /lessons/7"] = () => LESSON;
  routes["POST /lessons/7/checks"] = () => ({
    ...LESSON,
    progress: {
      ...LESSON.progress,
      check: {
        score: 1,
        total: 1,
        passed: true,
        attempts: 1,
        submitted_at: "2026-11-07T00:00:00Z",
        results: [
          {
            chosen_index: 0,
            correct_index: 0,
            is_correct: true,
            explanation: "Because it fits.",
          },
        ],
      },
    },
  });
  routes["PUT /lessons/7/progress"] = () => ({
    ...LESSON,
    progress: {
      ...LESSON.progress,
      status: "completed",
      completed_at: "2026-11-07T00:00:00Z",
    },
  });

  open("#/lessons?level=subskill&id=100");
  await see("Open a lesson");
  await vi.waitFor(() => expect(button("Open lesson").disabled).toBe(false));
  button("Open lesson").click();

  await see("Choosing retrieval");
  expect(callsTo("POST", "/lessons")[0].body).toEqual({
    scope_level: "subskill",
    scope_id: 100,
    depth: "beginner",
  });
  expect(container.textContent).toContain("AI-generated explanation");
  expect(container.textContent).toContain("Syllabus source");
  expect(container.textContent).toContain("test-model via llm.test");
  expect(container.textContent).toContain("Support bot");
  expect(container.textContent).toContain("Fit the index to the data");

  // Nothing reveals the answer before it is submitted.
  expect(container.textContent).not.toContain("Correct answer");

  container.querySelector<HTMLInputElement>('input[type="radio"]')!.click();
  await vi.waitFor(() => expect(button("Check answers").disabled).toBe(false));
  button("Check answers").click();
  await see("Score 1 of 1");
  expect(callsTo("POST", "/lessons/7/checks")[0].body).toEqual({
    answers: [0],
  });
  expect(container.textContent).toContain("Because it fits.");

  button("Mark lesson complete").click();
  await see("Completed");
  expect(callsTo("PUT", "/lessons/7/progress")[0].body).toEqual({
    status: "completed",
  });
});

test("a failed generation shows a retry and stays on the page", async () => {
  let failing = true;
  routes["POST /lessons"] = () => {
    if (failing) {
      throw new Failure(
        503,
        "The AI model is not configured.",
        "llm_not_configured",
      );
    }
    return LESSON;
  };
  routes["GET /lessons/7"] = () => LESSON;

  open("#/lessons?level=subskill&id=100");
  await see("Open a lesson");
  await vi.waitFor(() => expect(button("Open lesson").disabled).toBe(false));
  button("Open lesson").click();
  await see("The AI model is not configured.");

  failing = false;
  button("Try again").click();
  await see("Choosing retrieval");
});

test("plan flow: create from inputs, with no manual mark-done", async () => {
  let plan = {
    version_number: 1,
    latest_version_number: 1,
    inputs: null as unknown,
    summary: null as unknown,
    items: [] as unknown[],
  };
  routes["GET /plan"] = () => plan;
  routes["PUT /plan"] = (body) => {
    plan = { ...plan, inputs: body, summary: SUMMARY, items: [PLAN_ITEM] };
    return plan;
  };

  open("#/plan");
  await see("No learning path yet");
  // The skill tree only appears once there is a path.
  expect(container.textContent).not.toContain("Skill tree");

  // Step 1: pace.
  setValue(
    container.querySelector<HTMLInputElement>('input[type="number"]')!,
    "12",
  );
  setValue(
    container.querySelector<HTMLInputElement>('input[type="date"]')!,
    "2027-01-15",
  );
  await vi.waitFor(() =>
    expect(
      container.querySelector<HTMLInputElement>('input[type="number"]')!.value,
    ).toBe("12"),
  );
  button("Next").click();

  // Step 2: one answer per chapter sets every skill in it.
  await see("Step 2 of 3");
  container
    .querySelector<HTMLInputElement>('input[name="domain-1"][value="2"]')!
    .click();
  button("Next").click();

  // Step 3: review and create.
  await see("Step 3 of 3");
  expect(container.textContent).toContain("12 hours");
  button("Create my path").click();

  await see("Week 1, from 2026-11-07");
  expect(callsTo("PUT", "/plan")[0].body).toEqual({
    familiarity: { 10: 2 },
    weekly_hours: 12,
    exam_date: "2027-01-15",
  });
  expect(container.textContent).toContain("Skill tree");
  expect(container.textContent).toContain("Continue learning");
  expect(container.textContent).toContain("0 of 1 objectives complete");
  expect(
    container
      .querySelector('[role="progressbar"]')!
      .getAttribute("aria-valuenow"),
  ).toBe("0");

  // Only finishing the lesson completes an objective, never the plan page.
  expect(container.textContent).not.toContain("Mark done");
});

test("adjusting a path keeps per-skill familiarity of untouched chapters", async () => {
  routes["GET /syllabus"] = () => ({
    ...SYLLABUS,
    domains: [
      SYLLABUS.domains[0],
      {
        id: 2,
        position: 2,
        name: "Build agents",
        weight_min: 20,
        weight_max: 25,
        skills: [
          {
            id: 20,
            position: 1,
            name: "Agents",
            subskills: [{ id: 200, position: 1, text: "Design an agent" }],
          },
        ],
      },
    ],
  });
  routes["GET /plan"] = () => ({
    version_number: 1,
    latest_version_number: 1,
    inputs: { familiarity: { 10: 3, 20: 1 }, weekly_hours: 5, exam_date: null },
    summary: SUMMARY,
    items: [PLAN_ITEM],
  });
  routes["PUT /plan"] = (body) => ({
    version_number: 1,
    latest_version_number: 1,
    inputs: body,
    summary: SUMMARY,
    items: [PLAN_ITEM],
  });

  open("#/plan");
  await see("Week 1");
  // Objective 200 is absent from the remaining items, so it is complete.
  expect(container.textContent).toContain("1 of 2 objectives complete");
  button("Adjust path").click();
  await see("Step 1 of 3");
  button("Next").click();
  await see("Step 2 of 3");
  container
    .querySelector<HTMLInputElement>('input[name="domain-2"][value="2"]')!
    .click();
  button("Next").click();
  await see("Step 3 of 3");
  button("Update my path").click();

  await vi.waitFor(() => expect(callsTo("PUT", "/plan")).toHaveLength(1));
  expect(callsTo("PUT", "/plan")[0].body).toEqual({
    familiarity: { 10: 3, 20: 2 },
    weekly_hours: 5,
    exam_date: null,
  });
});

test("readiness on the path comes from analytics, not XP", async () => {
  routes["GET /plan"] = () => ({
    version_number: 1,
    latest_version_number: 1,
    inputs: { familiarity: {}, weekly_hours: 5, exam_date: null },
    summary: SUMMARY,
    items: [],
  });
  routes["GET /analytics"] = () => ({
    readiness: "not_ready",
    readiness_percent: 41,
  });
  open("#/plan");
  await see("Not ready yet · 41%");
  // One objective and one cleared chapter.
  expect(container.textContent).toContain("350 XP");
});

test("a failed plan explanation leaves the plan on screen", async () => {
  routes["GET /plan"] = () => ({
    version_number: 1,
    latest_version_number: 1,
    inputs: { familiarity: {}, weekly_hours: 5, exam_date: null },
    summary: SUMMARY,
    items: [PLAN_ITEM],
  });
  routes["POST /plan/explanation?version=1"] = () => {
    throw new Failure(503, "The AI model could not be reached.");
  };

  open("#/plan");
  await see("Week 1");
  button("Explain this order").click();

  await see("The AI model could not be reached.");
  expect(container.textContent).toContain("Week 1");
});

test("offers a newer syllabus version without moving the learner", async () => {
  routes["GET /dashboard"] = () => ({ ...DASHBOARD, latest_version_number: 2 });
  open("#/dashboard");
  await see("Syllabus version 2 is available");
  const link = container.querySelector<HTMLAnchorElement>(
    'a[href="#/plan?version=2"]',
  );
  expect(link).not.toBeNull();
});
