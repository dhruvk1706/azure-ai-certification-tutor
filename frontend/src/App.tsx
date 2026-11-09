import {
  Component,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { AttemptPage } from "./pages/AttemptPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LessonsPage } from "./pages/LessonsPage";
import { PerformancePage } from "./pages/PerformancePage";
import { PlanPage } from "./pages/PlanPage";
import { PracticePage } from "./pages/PracticePage";
import { SandboxPage } from "./pages/SandboxPage";
import { TutorPage } from "./pages/TutorPage";

const PAGES = [
  { path: "dashboard", label: "Dashboard" },
  { path: "plan", label: "Learning path" },
  { path: "lessons", label: "Lessons" },
  { path: "tutor", label: "Tutor" },
  { path: "practice", label: "Practice & exams" },
  { path: "performance", label: "Performance" },
  { path: "sandbox", label: "Azure sandbox" },
];
const APP_NAME = "Azure AI Certification Tutor";
const THEME_KEY = "tutor.theme";
type Theme = "system" | "light" | "dark";

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** "#/lessons/7?depth=beginner" gives page "lessons", id 7 and those params. */
function parseRoute(hash: string) {
  const [path, query] = hash.replace(/^#\/?/, "").split("?");
  const [page, id] = path.split("/");
  return {
    page: PAGES.some((p) => p.path === page) ? page : "dashboard",
    id: id && /^\d+$/.test(id) ? Number(id) : undefined,
    params: new URLSearchParams(query),
  };
}

function savedTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

/** Mirrors the script in index.html, which sets the theme before first paint. */
function ThemeSelect() {
  const [theme, setTheme] = useState<Theme>(savedTheme);

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && !!media?.matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    try {
      if (theme === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Blocked storage: the choice lasts for this page only.
    }
    media?.addEventListener?.("change", apply);
    return () => media?.removeEventListener?.("change", apply);
  }, [theme]);

  return (
    <label className="flex items-center justify-between gap-2 text-sm text-muted">
      <span>Theme</span>
      <select
        value={theme}
        onChange={(event) => setTheme(event.target.value as Theme)}
        className="input w-auto min-h-0 py-1"
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}

/** A page that throws while rendering shows this instead of a blank screen. */
class PageBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
      >
        This page hit an unexpected error. Your saved progress is safe.{" "}
        <button
          type="button"
          className="font-medium underline"
          onClick={() => window.location.reload()}
        >
          Reload the page
        </button>
      </div>
    );
  }
}

export default function App() {
  const hash = useSyncExternalStore(
    subscribe,
    () => window.location.hash,
    () => "",
  );
  const { page, id, params } = parseRoute(hash);
  const label = PAGES.find((p) => p.path === page)?.label;
  // The mobile menu belongs to the route it was opened on, so navigating closes it.
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const menuOpen = menuFor === hash;
  const main = useRef<HTMLElement>(null);
  const firstPage = useRef(true);

  useEffect(() => {
    document.title = `${label} · ${APP_NAME}`;
    if (firstPage.current) {
      firstPage.current = false;
      return;
    }
    // Screen readers and keyboards start on the new page, not the old link.
    window.scrollTo?.(0, 0);
    main.current?.focus({ preventScroll: true });
  }, [page, label]);

  return (
    <div className="min-h-screen bg-bg text-ink md:flex">
      <button
        type="button"
        onClick={() => main.current?.focus()}
        className="btn btn-primary sr-only z-20 focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        Skip to main content
      </button>
      {/* The sidebar is always dark navy, framing the dark dashboard and path in either theme. */}
      <header className="ds-dark border-b border-line bg-surface text-ink md:sticky md:top-0 md:flex md:h-screen md:w-(--ds-sidebar-width) md:shrink-0 md:flex-col md:border-r md:border-b-0">
        <div className="flex items-center gap-3 px-4 py-3 md:py-5">
          <a
            href="#/dashboard"
            className="mr-auto flex items-center gap-2.5 rounded-md text-sm leading-tight font-bold"
          >
            <span
              aria-hidden="true"
              className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-linear-to-br from-accent to-accent-2 text-xs font-extrabold text-white shadow-[0_0_20px_-4px_var(--ds-glow)]"
            >
              AI
            </span>
            {APP_NAME}
          </a>
          <button
            type="button"
            className="btn btn-secondary md:hidden"
            aria-expanded={menuOpen}
            aria-controls="main-nav"
            onClick={() => setMenuFor(menuOpen ? null : hash)}
          >
            {menuOpen ? "Close menu" : "Menu"}
          </button>
        </div>
        <nav
          id="main-nav"
          aria-label="Main"
          className={`px-3 pb-3 md:flex-1 md:overflow-y-auto ${menuOpen ? "" : "hidden"} md:block`}
        >
          <ul className="flex flex-col gap-1">
            {PAGES.map(({ path, label }) => (
              <li key={path}>
                <a
                  href={`#/${path}`}
                  aria-current={page === path ? "page" : undefined}
                  // Choosing the page already shown changes no route, so close here too.
                  onClick={() => setMenuFor(null)}
                  className="nav-link"
                >
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div
          className={`border-t border-line px-4 py-3 ${menuOpen ? "" : "hidden"} md:block`}
        >
          <ThemeSelect />
        </div>
      </header>
      <div className="flex min-w-0 flex-1 flex-col">
        <main
          id="main"
          ref={main}
          tabIndex={-1}
          className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 focus:outline-none md:px-8"
        >
          <PageBoundary key={page}>
            {page === "dashboard" && <DashboardPage />}
            {page === "plan" && (
              <PlanPage
                targetVersion={Number(params.get("version")) || undefined}
              />
            )}
            {page === "lessons" && (
              <LessonsPage
                lessonId={id}
                level={params.get("level")}
                topicId={Number(params.get("id")) || undefined}
              />
            )}
            {page === "tutor" && <TutorPage conversationId={id} />}
            {page === "practice" &&
              (id ? (
                <AttemptPage key={id} attemptId={id} />
              ) : (
                <PracticePage
                  level={params.get("level")}
                  topicId={Number(params.get("id")) || undefined}
                />
              ))}
            {page === "performance" && <PerformancePage />}
            {page === "sandbox" && (
              <SandboxPage resourceId={id} params={params} />
            )}
          </PageBoundary>
        </main>
        <footer className="border-t border-line">
          <p className="mx-auto max-w-6xl px-4 py-3 text-xs text-muted md:px-8">
            An independent study aid, not affiliated with or endorsed by
            Microsoft. AI-generated content can be wrong: confirm details on
            Microsoft Learn.
          </p>
        </footer>
      </div>
    </div>
  );
}
