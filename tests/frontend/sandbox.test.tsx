// @vitest-environment jsdom
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../../frontend/src/App";

/** A route table standing in for the backend, as in the other frontend tests. */
type Handler = (body: unknown, request: RecordedCall) => unknown;
interface RecordedCall {
  method: string;
  path: string;
  body: unknown;
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

function field(key: string, kind: string, extra: object = {}) {
  return {
    key,
    label: key,
    kind,
    options: [],
    labels: [],
    default: null,
    required: true,
    minimum: null,
    maximum: null,
    integer: true,
    max_length: 120,
    help: "",
    refs: [],
    updatable: true,
    items: [],
    max_items: 20,
    ...extra,
  };
}

function type(
  key: string,
  label: string,
  parent: string | null,
  fields: object[],
  extra: object = {},
) {
  return {
    key,
    label,
    arm_type: `Simulated/${key}`,
    parent,
    description: `${label} description`,
    docs_url: "https://learn.microsoft.com/en-us/azure/",
    fields,
    name_help: "Letters and digits.",
    soft_delete: false,
    auto_name: false,
    updatable: true,
    actions: [],
    note: "",
    ...extra,
  };
}

const REGION = field("region", "select", {
  options: ["eastus", "westeurope"],
  labels: ["East US", "West Europe"],
  default: "eastus",
  updatable: false,
});

const CATALOG = {
  notice: "No Azure subscription, resources or charges are involved.",
  types: [
    type("resource_group", "Resource group", null, [REGION]),
    type(
      "foundry_resource",
      "Foundry resource",
      "resource_group",
      [REGION, field("disable_local_auth", "bool", { default: false })],
      { soft_delete: true },
    ),
    type("web_app", "Web app", "resource_group", [REGION], {
      actions: ["start", "stop", "test_connection"],
    }),
  ],
  regions: [
    { name: "eastus", label: "East US", data_zone: "US" },
    { name: "westeurope", label: "West Europe", data_zone: "EU" },
  ],
  models: [],
  sample_prompts: {},
  sample_questions: {},
};

function summary(
  id: number,
  resource_type: string,
  name: string,
  extra: object = {},
) {
  return {
    id,
    resource_type,
    type_label: CATALOG.types.find((t) => t.key === resource_type)!.label,
    name,
    parent_id: resource_type === "resource_group" ? null : 1,
    resource_group: "rg-lab",
    resource_group_id: 1,
    region: "eastus",
    state: "succeeded",
    updated_at: "2026-11-08T00:00:00Z",
    ...extra,
  };
}

function detail(
  id: number,
  resource_type: string,
  name: string,
  extra: object = {},
) {
  return {
    ...summary(id, resource_type, name),
    arm_id: `/subscriptions/sandbox/resourceGroups/rg-lab/${name}`,
    version: 3,
    properties: { region: "eastus", disable_local_auth: false },
    references: {},
    outputs: {},
    overview: [{ label: "Location", value: "East US" }],
    issues: [],
    children: [],
    actions: [],
    created_at: "2026-11-08T00:00:00Z",
    deleted_at: null,
    notice: "Simulated environment.",
    ...extra,
  };
}

const GROUP = detail(1, "resource_group", "rg-lab", {
  children: [summary(2, "foundry_resource", "lab-ai")],
});
const ACCOUNT = detail(2, "foundry_resource", "lab-ai", {
  issues: ["Content filter points to a resource that no longer exists."],
});
const APP = detail(3, "web_app", "lab-web", {
  state: "running",
  actions: ["stop", "test_connection"],
});

function check(id: string, status: string, extra: object = {}) {
  return {
    id,
    description: `Check ${id}`,
    status,
    feedback: null,
    hints: [],
    hints_total: 2,
    explanation: null,
    ...extra,
  };
}

function lab(status: string, checks: object[], extra: object = {}) {
  return {
    id: "foundry-setup",
    title: "Set up a Foundry resource",
    objective: "Plan the resources.",
    minutes: 10,
    resource_group: "rg-lab-foundry",
    syllabus: [],
    syllabus_text: ["Design Azure infrastructure for AI apps"],
    status,
    started_at: status === "not_started" ? null : "2026-11-08T00:00:00Z",
    completed_at: status === "completed" ? "2026-11-08T01:00:00Z" : null,
    validations: 0,
    last_validation: null,
    prerequisites: ["None."],
    scenario: "Data must stay in the EU.",
    expected_outcome: "A project in an EU resource.",
    instructions: ["Create the resource group."],
    tasks: [{ id: "resource", title: "Create the resource", checks }],
    completion: null,
    docs: [
      { title: "Create a resource", url: "https://learn.microsoft.com/x" },
    ],
    approximations: ["Regions are simplified."],
    resource_group_id: null,
    resets: 0,
    history: [],
    notice: "Simulated.",
    ...extra,
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
  };
  calls.push(call);
  const handler = routes[`${method} ${path.split("?")[0]}`];
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
  return calls.filter(
    (c) => c.method === method && c.path.split("?")[0] === path,
  );
}

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "";
  calls = [];
  routes = {
    "POST /learners": () => ({ id: 1, token: "learner-token" }),
    "GET /sandbox/catalog": () => CATALOG,
    "GET /sandbox/resources": () => [
      summary(1, "resource_group", "rg-lab"),
      summary(2, "foundry_resource", "lab-ai"),
    ],
    "GET /sandbox/resources/1": () => GROUP,
    "GET /sandbox/resources/2": () => ACCOUNT,
    "GET /sandbox/resources/3": () => APP,
    "GET /sandbox/deleted": () => [],
    "GET /sandbox/labs": () => [],
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

test("the portal says it is simulated and lists resources", async () => {
  open("#/sandbox");
  await see("lab-ai");
  expect(container.textContent).toContain("Simulated Azure sandbox");
  expect(container.textContent).toContain(CATALOG.notice);
  expect(container.textContent).toContain("Simulated");
  const links = [...container.querySelectorAll("a")].map((a) => a.textContent);
  expect(links).toContain("Guided labs");
  expect(links).toContain("Deleted resources");
});

test("search asks the server for matching resources", async () => {
  open("#/sandbox?q=foundry");
  await see('Resources matching "foundry"');
  expect(callsTo("GET", "/sandbox/resources")[0].path).toBe(
    "/sandbox/resources?q=foundry",
  );
});

test("creating a resource sends the form to the server and opens it", async () => {
  routes["POST /sandbox/resources"] = () => GROUP;
  open("#/sandbox?view=create&type=resource_group");
  await see("Create Resource group");

  setValue(container.querySelector<HTMLInputElement>("#new-name")!, "rg-lab");
  setValue(
    container.querySelector<HTMLSelectElement>("#new-region")!,
    "westeurope",
  );
  button("Review and create").click();

  await vi.waitFor(() => expect(window.location.hash).toBe("#/sandbox/1"));
  const [post] = callsTo("POST", "/sandbox/resources");
  expect(post.body).toMatchObject({
    resource_type: "resource_group",
    name: "rg-lab",
    parent_id: null,
    properties: { region: "westeurope" },
  });
  expect(
    (post.body as { client_request_id: string }).client_request_id,
  ).toBeTruthy();
});

test("a rejected create shows the server's reason and keeps the input", async () => {
  routes["POST /sandbox/resources"] = () => {
    throw new Failure(422, "'bad name!' isn't a valid name.");
  };
  open("#/sandbox?view=create&type=resource_group");
  await see("Create Resource group");
  setValue(
    container.querySelector<HTMLInputElement>("#new-name")!,
    "bad name!",
  );
  button("Review and create").click();
  await see("isn't a valid name");
  expect(container.querySelector<HTMLInputElement>("#new-name")!.value).toBe(
    "bad name!",
  );
  expect(window.location.hash).toBe(
    "#/sandbox?view=create&type=resource_group",
  );
});

test("settings save with the version they were read at, and conflicts are shown", async () => {
  routes["PUT /sandbox/resources/2"] = () => {
    throw new Failure(409, "This resource changed since you loaded it.");
  };
  open("#/sandbox/2");
  await see("Content filter points to a resource that no longer exists.");
  button("Settings").click();
  await vi.waitFor(() =>
    expect(container.querySelector("#edit-disable_local_auth")).not.toBeNull(),
  );
  expect(
    container.querySelector<HTMLSelectElement>("#edit-region")!.disabled,
  ).toBe(true);
  container
    .querySelector<HTMLInputElement>("#edit-disable_local_auth")!
    .click();
  button("Save").click();

  await see("changed since you loaded it");
  expect(callsTo("PUT", "/sandbox/resources/2")[0].body).toEqual({
    properties: { region: "eastus", disable_local_auth: true },
    version: 3,
  });
});

test("deleting a resource group needs its name typed", async () => {
  routes["DELETE /sandbox/resources/1"] = () => ({
    deleted: [1],
    soft_deleted: [2],
  });
  open("#/sandbox/1");
  await see("rg-lab");
  button("Delete").click();
  await see("Type the resource group name");
  const remove = button("Delete resource group");
  expect(remove.disabled).toBe(true);
  setValue(
    container.querySelector<HTMLInputElement>("input:not([name])")!,
    "rg-lab",
  );
  await vi.waitFor(() =>
    expect(button("Delete resource group").disabled).toBe(false),
  );
  button("Delete resource group").click();
  await vi.waitFor(() =>
    expect(callsTo("DELETE", "/sandbox/resources/1")).toHaveLength(1),
  );
  expect(callsTo("DELETE", "/sandbox/resources/1")[0].path).toBe(
    "/sandbox/resources/1?confirm_name=rg-lab",
  );
});

test("operations show the simulated result from the server", async () => {
  routes["POST /sandbox/resources/3/actions/test_connection"] = () => ({
    result: {
      ok: false,
      error:
        "401 Unauthorized: key-based authentication is disabled on lab-ai.",
      steps: ["Calling lab-ai from lab-web."],
      notice: "Simulated result: no Azure service or AI model was called.",
    },
    resource: APP,
  });
  open("#/sandbox/3");
  await see("lab-web");
  button("Operations").click();
  await see("Test connection");
  button("Test connection").click();
  await see("401 Unauthorized");
  expect(container.textContent).toContain("Simulated result");
  expect(
    callsTo("POST", "/sandbox/resources/3/actions/test_connection")[0].body,
  ).toEqual({
    input: {},
  });
});

test("a lab is started, validated, hinted and completed by the server", async () => {
  let state = lab("not_started", [check("foundry-in-eu", "not_checked")]);
  routes["GET /sandbox/labs/foundry-setup"] = () => state;
  routes["POST /sandbox/labs/foundry-setup/start"] = () =>
    (state = lab("in_progress", [check("foundry-in-eu", "not_checked")]));
  routes["POST /sandbox/labs/foundry-setup/validate"] = () =>
    (state = lab(
      "in_progress",
      [
        check("foundry-in-eu", "failed", {
          feedback: "lab-ai is outside the EU.",
        }),
      ],
      {
        last_validation: {
          id: 1,
          passed: false,
          passed_checks: 0,
          total_checks: 1,
          created_at: "2026-11-08T00:00:00Z",
        },
      },
    ));
  routes["POST /sandbox/labs/foundry-setup/hints"] = () =>
    (state = lab("in_progress", [
      check("foundry-in-eu", "failed", {
        feedback: "lab-ai is outside the EU.",
        hints: ["Region decides residency."],
      }),
    ]));

  open("#/sandbox?lab=foundry-setup");
  await see("Data must stay in the EU.");
  expect(container.textContent).toContain(
    "Design Azure infrastructure for AI apps",
  );
  button("Start lab").click();
  await see("Create the resource group.");
  // Starting a lab creates starter resources, so the resource list reloads.
  await vi.waitFor(() =>
    expect(callsTo("GET", "/sandbox/resources").length).toBeGreaterThan(1),
  );

  button("Validate").click();
  await see("lab-ai is outside the EU.");
  const firstId = (
    callsTo("POST", "/sandbox/labs/foundry-setup/validate")[0].body as {
      client_validation_id: string;
    }
  ).client_validation_id;
  expect(firstId).toBeTruthy();

  button("Show a hint").click();
  await see("Hint 1: Region decides residency.");
  expect(callsTo("POST", "/sandbox/labs/foundry-setup/hints")[0].body).toEqual({
    check_id: "foundry-in-eu",
    level: 1,
  });

  routes["POST /sandbox/labs/foundry-setup/validate"] = () =>
    lab(
      "completed",
      [
        check("foundry-in-eu", "passed", {
          explanation: "Region is fixed at creation.",
        }),
      ],
      {
        completion: "You planned a Foundry deployment.",
      },
    );
  button("Validate").click();
  await see("Lab complete");
  expect(container.textContent).toContain("Region is fixed at creation.");
  const ids = callsTo("POST", "/sandbox/labs/foundry-setup/validate").map(
    (c) => (c.body as { client_validation_id: string }).client_validation_id,
  );
  expect(new Set(ids).size).toBe(2);
});

test("the assistant's answer is labelled, and a failure can be retried without losing the question", async () => {
  routes["GET /sandbox/labs/foundry-setup"] = () =>
    lab("in_progress", [check("foundry-in-eu", "failed")]);
  let failing = true;
  routes["POST /sandbox/labs/foundry-setup/assistant"] = () => {
    if (failing)
      throw new Failure(
        503,
        "The AI model could not be reached.",
        "llm_unavailable",
      );
    return {
      answer: "Look at the region you chose.",
      llm_model: "test-model",
      llm_provider: "llm.test",
      notice: "Only Validate grades your work.",
    };
  };
  open("#/sandbox?lab=foundry-setup");
  await see("Lab assistant");
  const box = container.querySelector<HTMLTextAreaElement>("#lab-question")!;
  setValue(box, "Why did it fail?");
  button("Ask").click();
  await see("The AI model could not be reached.");
  expect(box.value).toBe("Why did it fail?");

  failing = false;
  button("Ask again").click();
  await see("Look at the region you chose.");
  expect(container.textContent).toContain("AI-generated");
  expect(container.textContent).toContain("Only Validate grades your work.");
  expect(
    callsTo("POST", "/sandbox/labs/foundry-setup/assistant").at(-1)!.body,
  ).toEqual({
    question: "Why did it fail?",
  });
  expect(callsTo("POST", "/sandbox/labs/foundry-setup/validate")).toHaveLength(
    0,
  );
});

test("the dashboard shows lab progress, and keeps working when labs can't load", async () => {
  const count = { completed: 0, in_progress: 0, total: 1, percent: 0 };
  routes["GET /dashboard"] = () => ({
    version_number: 1,
    latest_version_number: 1,
    has_plan: false,
    overall: count,
    domains: [],
    weak_areas: [],
    next_lesson: null,
    lessons_completed: 0,
    checks_submitted: 0,
    checks_passed: 0,
    last_activity_at: null,
  });
  routes["GET /sandbox/labs"] = () => [
    lab("completed", []),
    { ...lab("in_progress", []), id: "other" },
    { ...lab("not_started", []), id: "third" },
  ];
  open("#/dashboard");
  await see("1 of 3 guided labs completed, 1 in progress");

  root.unmount();
  routes["GET /sandbox/labs"] = () => {
    throw new Failure(503, "The database is unavailable.");
  };
  open("#/dashboard");
  await see("Lab progress is unavailable.");
  expect(container.textContent).toContain("Overall completion");
});
