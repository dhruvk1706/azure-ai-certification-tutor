// @vitest-environment jsdom
// Phase 6: the app shell — theme, mobile menu, routing fallbacks and the error boundary.
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../../frontend/src/App";

const COUNT = { completed: 0, in_progress: 0, total: 1, percent: 0 };
let dashboard: unknown;
let container: HTMLElement;
let root: Root;

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status });
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  window.location.hash = "";
  dashboard = {
    version_number: 1,
    latest_version_number: 1,
    has_plan: true,
    overall: COUNT,
    domains: [],
    weak_areas: [],
    next_lesson: null,
    lessons_completed: 0,
    checks_submitted: 0,
    checks_passed: 0,
    last_activity_at: null,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const path = url.replace(/^.*\/api/, "");
      if (init.method === "POST" && path === "/learners") {
        return respond(201, { id: 1, token: "t" });
      }
      if (path === "/dashboard") return respond(200, dashboard);
      return respond(404, { detail: `No route ${path}` });
    }),
  );
  vi.stubGlobal("scrollTo", () => {});
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

function select(label: string) {
  const element = [...container.querySelectorAll("label")]
    .find((l) => l.textContent?.includes(label))
    ?.querySelector("select");
  if (!element) throw new Error(`no select ${label}`);
  return element;
}

function setValue(element: HTMLSelectElement, value: string) {
  Object.getOwnPropertyDescriptor(
    HTMLSelectElement.prototype,
    "value",
  )!.set!.call(element, value);
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

test("the theme choice applies at once and is remembered", async () => {
  open("#/dashboard");
  await see("Overall completion");
  expect(document.documentElement.dataset.theme).toBe("light");

  setValue(select("Theme"), "dark");
  await vi.waitFor(() =>
    expect(document.documentElement.dataset.theme).toBe("dark"),
  );
  expect(localStorage.getItem("tutor.theme")).toBe("dark");

  setValue(select("Theme"), "system");
  await vi.waitFor(() =>
    expect(document.documentElement.dataset.theme).toBe("light"),
  );
  expect(localStorage.getItem("tutor.theme")).toBeNull();
});

test("the mobile menu opens, and closes when a page is chosen", async () => {
  open("#/dashboard");
  await see("Overall completion");
  const toggle = [...container.querySelectorAll("button")].find(
    (b) => b.textContent === "Menu",
  )!;
  const nav = container.querySelector("#main-nav")!;
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(nav.className).toContain("hidden");

  toggle.click();
  await vi.waitFor(() =>
    expect(toggle.getAttribute("aria-expanded")).toBe("true"),
  );
  expect(nav.className).not.toContain(" hidden");

  window.location.hash = "#/performance";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await vi.waitFor(() =>
    expect(toggle.getAttribute("aria-expanded")).toBe("false"),
  );
  expect(document.title).toBe("Performance · Azure AI Certification Tutor");
  expect(document.activeElement?.id).toBe("main");

  // Choosing the page already shown changes no route, but still closes the menu.
  toggle.click();
  await vi.waitFor(() =>
    expect(toggle.getAttribute("aria-expanded")).toBe("true"),
  );
  nav.querySelector<HTMLAnchorElement>('a[href="#/performance"]')!.click();
  await vi.waitFor(() =>
    expect(toggle.getAttribute("aria-expanded")).toBe("false"),
  );
});

test("an unknown route shows the dashboard", async () => {
  open("#/no-such-page");
  await see("Overall completion");
  expect(document.title).toBe("Dashboard · Azure AI Certification Tutor");
  expect(container.querySelector('[aria-current="page"]')?.textContent).toBe(
    "Dashboard",
  );
});

test("a page that fails to render shows a recoverable error, not a blank screen", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  dashboard = { ...(dashboard as object), domains: null };
  open("#/dashboard");
  await see("This page hit an unexpected error");
  // The shell still works, so the learner can go elsewhere.
  expect(container.querySelector("nav")?.textContent).toContain("Lessons");
});
