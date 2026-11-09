// @vitest-environment jsdom
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../../frontend/src/App";

type Handler = (body: unknown, request: RecordedCall) => unknown;
interface RecordedCall {
  method: string;
  path: string;
  body: unknown;
}

class Failure {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    this.status = status;
    this.detail = detail;
  }
}

const NOTICE =
  "Original practice questions written by AI. They are not official Microsoft certification questions.";

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
  match: null,
};

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

const BANK = {
  version_number: 1,
  latest_version_number: 1,
  total_questions: 2,
  notice: NOTICE,
  objectives: [
    {
      topic: REFERENCE,
      sources: [
        {
          id: 5,
          title: "Choose a retrieval approach",
          url: "https://learn.microsoft.com/en-us/x",
          retrieved_at: "2026-11-07T00:00:00Z",
        },
      ],
      questions: 2,
      by_difficulty: { medium: 2 },
    },
  ],
};

const FEEDBACK = {
  chosen_index: 1,
  correct_index: 0,
  is_correct: false,
  explanation: "Hybrid search combines both query types.",
  source: {
    title: "Choose a retrieval approach",
    url: "https://learn.microsoft.com/en-us/x",
    excerpt: "Hybrid search runs keyword and vector queries in parallel",
  },
  topic: REFERENCE,
};

function item(position: number, extra: Record<string, unknown> = {}) {
  return {
    position,
    kind: "mcq",
    difficulty: "medium",
    scenario: null,
    stem: `Question number ${position}?`,
    options: ["Hybrid search", "Keyword search", "Vector search", "Ranking"],
    chosen_index: null,
    feedback: null,
    ...extra,
  };
}

function attempt(extra: Record<string, unknown> = {}) {
  return {
    id: 9,
    mode: "practice",
    selection: "topic",
    scope_level: "subskill",
    scope_id: 100,
    version_number: 1,
    status: "in_progress",
    question_count: 2,
    answered_count: 0,
    score: null,
    percent: null,
    passed: null,
    started_at: "2026-11-07T00:00:00Z",
    deadline_at: null,
    submitted_at: null,
    submit_reason: null,
    difficulty: null,
    time_limit_seconds: null,
    server_time: "2026-11-07T00:00:00Z",
    remaining_seconds: null,
    pass_percent: 70,
    notice: NOTICE,
    items: [item(1), item(2)],
    ...extra,
  };
}

const ANALYTICS = {
  version_number: 1,
  latest_version_number: 1,
  answered: 12,
  correct: 6,
  percent: 50,
  readiness_percent: 41,
  readiness: "insufficient_data",
  pass_percent: 70,
  mock_exams_taken: 1,
  latest_mock_percent: 55,
  best_mock_percent: 55,
  domains: [
    {
      domain_id: 1,
      position: 1,
      name: "Plan and manage",
      weight_min: 25,
      weight_max: 30,
      answered: 12,
      correct: 6,
      percent: 50,
      standing: "weakness",
    },
  ],
  skills: [
    {
      skill_id: 10,
      domain_id: 1,
      code: "1.1",
      name: "Select services",
      answered: 12,
      correct: 6,
      percent: 50,
      standing: "weakness",
    },
  ],
  recommendations: [
    {
      topic: REFERENCE,
      answered: 12,
      correct: 6,
      percent: 50,
      reason: "low_accuracy",
      available_questions: 2,
    },
  ],
  attempts: [],
  notice: NOTICE,
};

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
  };
  calls.push(call);
  const handler = routes[`${method} ${path}`];
  if (!handler) return respond(404, { detail: `No route ${method} ${path}` });
  try {
    return respond(200, handler(call.body, call));
  } catch (error) {
    if (error instanceof Failure) {
      return respond(error.status, { detail: error.detail });
    }
    throw error;
  }
}

function open(hash: string) {
  window.location.hash = hash;
  root = createRoot(container);
  root.render(<App />);
}

function see(text: string, timeout = 2000) {
  return vi.waitFor(() => expect(container.textContent).toContain(text), {
    timeout,
  });
}

function button(label: string) {
  const match = [...container.querySelectorAll("button")].find((element) =>
    element.textContent?.includes(label),
  );
  if (!match) throw new Error(`no button ${label}`);
  return match;
}

function setValue(
  element: HTMLInputElement | HTMLSelectElement,
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

function radios() {
  return [
    ...container.querySelectorAll<HTMLInputElement>('input[type="radio"]'),
  ];
}

beforeEach(() => {
  localStorage.setItem("tutor.learnerToken", "token");
  window.location.hash = "";
  calls = [];
  routes = {
    "GET /syllabus": () => SYLLABUS,
    "GET /questions/bank": () => BANK,
    "GET /attempts": () => [],
    "GET /analytics": () => ANALYTICS,
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
  localStorage.clear();
});

test("practice page labels questions as unofficial and retries a start safely", async () => {
  let failing = true;
  routes["POST /attempts"] = () => {
    if (failing) throw new Failure(503, "The database is unavailable.");
    return attempt();
  };
  routes["GET /attempts/9"] = () => attempt();

  open("#/practice?level=subskill&id=100");
  await see("Practise a topic");
  expect(container.textContent).toContain("Unofficial practice.");
  expect(container.textContent).toContain("not official Microsoft");
  expect(container.textContent).toContain("Choose a retrieval approach");

  button("Start practice").click();
  await see("The database is unavailable.");
  failing = false;
  button("Start practice").click();
  await see("Question number 1?");

  const starts = callsTo("POST", "/attempts");
  expect(starts).toHaveLength(2);
  const [first, second] = starts.map(
    (call) => call.body as Record<string, unknown>,
  );
  expect(first.client_attempt_id).toBe(second.client_attempt_id);
  expect(first).toMatchObject({
    mode: "practice",
    scope_level: "subskill",
    scope_id: 100,
    question_count: 5,
  });
});

test("practice shows the server's feedback only after an answer", async () => {
  let current = attempt();
  routes["GET /attempts/9"] = () => current;
  routes["PUT /attempts/9/answers/1"] = () => {
    current = attempt({
      items: [item(1, { chosen_index: 1, feedback: FEEDBACK }), item(2)],
    });
    return current;
  };

  open("#/practice/9");
  await see("Question number 1?");
  expect(container.textContent).not.toContain("Correct answer");
  expect(container.textContent).not.toContain("Hybrid search combines");

  radios()[1].click();
  await see("Hybrid search combines both query types.");
  expect(callsTo("PUT", "/attempts/9/answers/1")[0].body).toEqual({
    chosen_index: 1,
  });
  expect(container.textContent).toContain("Incorrect.");
  expect(container.textContent).toContain("Correct answer");
  expect(container.textContent).toContain("Your answer");
  expect(container.textContent).toContain("Evidence from Microsoft Learn");
  expect(container.textContent).toContain(
    "Hybrid search runs keyword and vector queries in parallel",
  );
  // A practice answer is final.
  expect(radios().every((radio) => radio.disabled)).toBe(true);
});

test("mock exam saves answers, confirms submission and shows the result", async () => {
  let current = attempt({
    mode: "mock",
    selection: "exam",
    remaining_seconds: 1800,
    deadline_at: "2026-11-07T00:30:00Z",
    time_limit_seconds: 1800,
  });
  routes["GET /attempts/9"] = () => current;
  routes["PUT /attempts/9/answers/1"] = (body) => {
    current = {
      ...current,
      items: [
        item(1, {
          chosen_index: (body as { chosen_index: number }).chosen_index,
        }),
        item(2),
      ],
    };
    return current;
  };
  routes["POST /attempts/9/submit"] = () => {
    current = attempt({
      mode: "mock",
      selection: "exam",
      status: "submitted",
      submit_reason: "learner",
      score: 0,
      percent: 0,
      passed: false,
      items: [
        item(1, { chosen_index: 1, feedback: FEEDBACK }),
        item(2, { feedback: { ...FEEDBACK, chosen_index: null } }),
      ],
    });
    return current;
  };

  open("#/practice/9");
  await see("30:00");
  expect(container.querySelector('[role="timer"]')).not.toBeNull();

  radios()[1].click();
  await vi.waitFor(() =>
    expect(callsTo("PUT", "/attempts/9/answers/1")).toHaveLength(1),
  );
  // Once saved, mock answers stay open to change, and nothing is revealed.
  await vi.waitFor(() => expect(radios()[0].disabled).toBe(false));
  expect(radios()[1].checked).toBe(true);
  expect(container.textContent).not.toContain("Correct answer");

  button("Submit exam").click();
  await see("1 unanswered, which count as wrong.");
  expect(callsTo("POST", "/attempts/9/submit")).toHaveLength(0);
  button("Confirm submit").click();

  await see("0 of 2 (0%)");
  expect(container.textContent).toContain("Below the 70% practice mark");
  expect(container.textContent).toContain("1. Plan and manage");
  expect(container.textContent).toContain("Not answered.");
  expect(container.querySelector('[role="timer"]')).toBeNull();
});

test("a picked answer shows at once while it saves, and reverts if saving fails", async () => {
  routes["GET /attempts/9"] = () =>
    attempt({ mode: "mock", selection: "exam", remaining_seconds: 1800 });
  let finish: (response: Response) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit = {}) =>
      url.endsWith("/answers/1")
        ? new Promise<Response>((resolve) => (finish = resolve))
        : fakeFetch(url, init),
    ),
  );

  open("#/practice/9");
  await see("Question number 1?");
  radios()[2].click();
  await vi.waitFor(() => expect(radios()[2].checked).toBe(true));
  // Locked while the save is in flight, so a second pick can't race it.
  expect(radios().every((radio) => radio.disabled)).toBe(true);

  finish(respond(503, { detail: "The database is unavailable." }));
  await see("The database is unavailable.");
  expect(radios().some((radio) => radio.checked)).toBe(false);
  expect(radios()[0].disabled).toBe(false);
});

test("when the timer runs out the page asks the server to settle the exam", async () => {
  let reads = 0;
  routes["GET /attempts/9"] = () => {
    reads += 1;
    return reads === 1
      ? attempt({ mode: "mock", selection: "exam", remaining_seconds: 1 })
      : attempt({
          mode: "mock",
          selection: "exam",
          status: "submitted",
          submit_reason: "time_expired",
          score: 0,
          percent: 0,
          passed: false,
          items: [
            item(1, { feedback: { ...FEEDBACK, chosen_index: null } }),
            item(2, { feedback: { ...FEEDBACK, chosen_index: null } }),
          ],
        });
  };
  open("#/practice/9");
  await see("0:01");
  await see("Time ran out, so the exam was submitted automatically", 4000);
  expect(reads).toBe(2);
});

test("a conflict on answering reloads the attempt from the server", async () => {
  let expired = false;
  routes["GET /attempts/9"] = () =>
    expired
      ? attempt({
          mode: "mock",
          status: "submitted",
          submit_reason: "time_expired",
          score: 0,
          percent: 0,
          passed: false,
          items: [
            item(1, { feedback: { ...FEEDBACK, chosen_index: null } }),
            item(2, { feedback: { ...FEEDBACK, chosen_index: null } }),
          ],
        })
      : attempt({ mode: "mock", remaining_seconds: 600 });
  routes["PUT /attempts/9/answers/1"] = () => {
    expired = true;
    throw new Failure(409, "Time is up, so the exam was submitted.");
  };
  open("#/practice/9");
  await see("Question number 1?");
  radios()[0].click();
  await see("Time ran out, so the exam was submitted automatically");
});

test("generation reports what was added and why the rest was rejected", async () => {
  routes["POST /questions/generate"] = () => ({
    accepted: 1,
    rejected: [
      { stem: "Which is best?", reason: "excerpt_not_in_source" },
      { stem: "Pick one", reason: "answer_disputed" },
    ],
    active_questions: 3,
    llm_model: "m",
    llm_provider: "p",
  });
  open("#/practice");
  await see("Question bank");
  const select = [...container.querySelectorAll("select")].find((element) =>
    element.textContent?.includes("Choose an objective with a source"),
  )!;
  setValue(select, "100");
  await vi.waitFor(() => expect(button("Generate").disabled).toBe(false));
  button("Generate").click();

  await see("1 added, 2 rejected");
  expect(callsTo("POST", "/questions/generate")[0].body).toEqual({
    subskill_id: 100,
    count: 3,
    difficulty: "medium",
    kind: "mcq",
  });
  expect(container.textContent).toContain(
    "Its quoted evidence is not on the Microsoft Learn page",
  );
  expect(container.textContent).toContain(
    "The independent check chose a different answer",
  );
});

test("generation limits and unsupported explanations are explained", async () => {
  let limited = true;
  routes["POST /questions/generate"] = () => {
    if (limited) {
      throw new Failure(429, "You can generate questions 10 times an hour.");
    }
    return {
      accepted: 0,
      rejected: [{ stem: "Which is best?", reason: "explanation_unsupported" }],
      active_questions: 2,
      llm_model: "m",
      llm_provider: "p",
    };
  };
  open("#/practice");
  await see("Question bank");
  const select = [...container.querySelectorAll("select")].find((element) =>
    element.textContent?.includes("Choose an objective with a source"),
  )!;
  setValue(select, "100");
  await vi.waitFor(() => expect(button("Generate").disabled).toBe(false));
  button("Generate").click();
  await see("You can generate questions 10 times an hour.");

  limited = false;
  button("Try again").click();
  await see("0 added, 1 rejected");
  expect(container.textContent).toContain(
    "Its explanation claims things the Microsoft Learn text does not say",
  );
});

test("performance page shows readiness, weaknesses and adaptive practice", async () => {
  routes["POST /attempts"] = () => attempt({ id: 9, selection: "adaptive" });
  routes["GET /attempts/9"] = () => attempt({ selection: "adaptive" });
  open("#/performance");
  await see("Readiness estimate");
  expect(container.textContent).toContain("41%");
  expect(container.textContent).toContain("Not enough evidence yet");
  expect(container.textContent).toContain("Weakness");
  expect(container.textContent).toContain("6 of 12 correct so far");
  expect(
    container.querySelector('a[href="#/practice?level=subskill&id=100"]'),
  ).not.toBeNull();
  expect(container.textContent).toContain(
    "not Microsoft's scaled passing score",
  );

  button("Start 10 adaptive questions").click();
  await see("Adaptive practice");
  expect(callsTo("POST", "/attempts")[0].body).toMatchObject({
    mode: "practice",
    adaptive: true,
    question_count: 10,
  });
});
