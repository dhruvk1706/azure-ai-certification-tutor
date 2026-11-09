import {
  useCallback,
  useEffect,
  useId,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type DependencyList,
} from "react";
import { ApiError, type SyllabusRef } from "./api";

export function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "Something went wrong. Try again.";
}

export function isMissingSyllabus(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 404 &&
    error.message.includes("ingested")
  );
}

interface Loaded<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
  setData: (data: T) => void;
}

/** Loads on mount and when deps change. A stale response can't overwrite a newer one. */
export function useLoad<T>(
  load: () => Promise<T>,
  deps: DependencyList,
): Loaded<T> {
  const [state, setState] = useState<{
    data: T | null;
    error: unknown;
    loading: boolean;
  }>({ data: null, error: null, loading: true });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    load().then(
      (data) => {
        if (current) setState({ data, error: null, loading: false });
      },
      (error: unknown) => {
        if (current) setState({ data: null, error, loading: false });
      },
    );
    return () => {
      current = false;
    };
    // The caller's deps decide when to reload, the same way useEffect's would.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt]);

  const reload = useCallback(() => {
    setState((previous) => ({ ...previous, loading: true, error: null }));
    setAttempt((value) => value + 1);
  }, []);
  const setData = useCallback((data: T) => {
    setState({ data, error: null, loading: false });
  }, []);

  return { ...state, reload, setData };
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="py-6 text-sm text-muted">
      {label}
    </p>
  );
}

export function ErrorNotice({
  error,
  onRetry,
  retryLabel = "Try again",
}: {
  error: unknown;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <span>{errorMessage(error)}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-red-300 bg-white px-3 py-1 font-medium hover:bg-red-100"
        >
          {retryLabel}
        </button>
      )}
    </div>
  );
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty bg-surface px-6 py-10 text-center">
      <p className="text-base font-semibold text-ink">{title}</p>
      {children && <div className="mt-2">{children}</div>}
    </div>
  );
}

/** Shown wherever the page can't work because nothing has been ingested. */
export function PageError({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  if (isMissingSyllabus(error)) {
    return (
      <Empty title="No syllabus has been ingested yet">
        Run <code>python -m app.syllabus.ingest</code> in the backend, then
        reload this page.
      </Empty>
    );
  }
  return <ErrorNotice error={error} onRetry={onRetry} />;
}

export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title && <h2 className="section-title mb-3">{title}</h2>}
      {children}
    </section>
  );
}

/** Older pages' name for buttonStyle, which defaults to primary instead. */
export function buttonClass(kind: "primary" | "secondary" = "primary") {
  return buttonStyle(kind);
}

const MATCH_LABELS: Record<string, string> = {
  search: "Matched your question",
  topic: "Your selected topic",
  previous_turn: "From earlier in this conversation",
  lesson_scope: "Covered by this lesson",
};

/** Retrieved syllabus text only, kept visibly apart from anything a model wrote. */
export function SyllabusReferences({
  references,
  numbered = false,
}: {
  references: SyllabusRef[];
  numbered?: boolean;
}) {
  return (
    <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3">
      <h3 className="text-xs font-semibold tracking-wide text-emerald-900 uppercase">
        Syllabus source · official study guide, v{references[0]?.version_number}
      </h3>
      <ul className="mt-2 space-y-2 text-sm">
        {references.map((reference, index) => (
          <li key={reference.subskill_id}>
            <span className="font-medium text-slate-900">
              {numbered && `[${index + 1}] `}
              {reference.code} {reference.subskill}
            </span>
            <div className="text-xs text-slate-600">
              {reference.domain} ({reference.weight_min}–{reference.weight_max}
              %) › {reference.skill}
              {reference.match && ` · ${MATCH_LABELS[reference.match] ?? ""}`}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ProgressBar({
  percent,
  label,
}: {
  percent: number;
  label: string;
}) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className="progress h-2"
    >
      <span style={{ width: `${percent}%` }} />
    </div>
  );
}

export function NewerVersionNotice({
  version,
  latest,
}: {
  version: number;
  latest: number;
}) {
  if (latest <= version) return null;
  return (
    <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      Syllabus version {latest} is available. You are on version {version}, and
      your progress stays on it.{" "}
      <a className="font-medium underline" href={`#/plan?version=${latest}`}>
        Create a plan on version {latest}
      </a>
    </p>
  );
}

/** Practice questions must never pass for official Microsoft exam content. */
export function PracticeNotice({ text }: { text: string }) {
  return (
    <p
      role="note"
      className="rounded-lg border border-slate-300 bg-slate-100 px-4 py-3 text-sm text-slate-800"
    >
      <span className="font-semibold">Unofficial practice. </span>
      {text}
    </p>
  );
}

// --- Design system (see the component classes in index.css) ---

export function buttonStyle(
  kind: "primary" | "secondary" | "ghost" | "danger" = "secondary",
) {
  return `btn btn-${kind}`;
}

export function Panel({
  title,
  id,
  children,
  className = "",
}: {
  title?: ReactNode;
  id?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-labelledby={title && id ? id : undefined}
      className={`card ${className}`}
    >
      {title && (
        <h2 id={id} className="section-title mb-3">
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}

export function Meter({ percent, label }: { percent: number; label: string }) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className="progress"
    >
      <span style={{ width: `${percent}%` }} />
    </div>
  );
}

export function ProgressRing({
  percent,
  label = "Objectives completed",
}: {
  percent: number;
  label?: string;
}) {
  const gradient = useId();
  const circumference = 2 * Math.PI * 42;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className="relative grid h-28 w-28 shrink-0 place-items-center"
    >
      <svg viewBox="0 0 100 100" className="absolute inset-0 -rotate-90">
        <defs>
          <linearGradient id={gradient} x1="0" x2="1">
            <stop offset="0" stopColor="var(--ds-accent)" />
            <stop offset="1" stopColor="var(--ds-accent-2)" />
          </linearGradient>
        </defs>
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke="var(--ds-line)"
          strokeWidth="8"
        />
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke={`url(#${gradient})`}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - percent / 100)}
        />
      </svg>
      <span className="text-2xl font-extrabold">{percent}%</span>
    </div>
  );
}

/** WAI-ARIA tabs: one tab stop, arrow keys and Home/End move and select. */
export function Tabs<K extends string>({
  label,
  tabs,
  value,
  onChange,
  children,
}: {
  label: string;
  tabs: readonly (readonly [K, ReactNode])[];
  value: K;
  onChange: (key: K) => void;
  children: ReactNode;
}) {
  const id = useId();
  const index = tabs.findIndex(([key]) => key === value);

  function onKeyDown(event: KeyboardEvent) {
    const step: number | undefined = {
      ArrowRight: 1,
      ArrowLeft: -1,
      Home: -index,
      End: tabs.length - 1 - index,
    }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    const [next] = tabs[(index + step + tabs.length) % tabs.length];
    onChange(next);
    document.getElementById(`${id}-${next}`)?.focus();
  }

  return (
    <>
      <div role="tablist" aria-label={label} className="tabs">
        {tabs.map(([key, text]) => (
          <button
            key={key}
            id={`${id}-${key}`}
            type="button"
            role="tab"
            aria-selected={key === value}
            aria-controls={`${id}-panel`}
            tabIndex={key === value ? 0 : -1}
            onClick={() => onChange(key)}
            onKeyDown={onKeyDown}
            className="tab"
          >
            {text}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`${id}-panel`}
        aria-labelledby={`${id}-${value}`}
        tabIndex={0}
        className="mt-4"
      >
        {children}
      </div>
    </>
  );
}

export function lessonHref(level: string, id: number) {
  return `#/lessons?level=${level}&id=${id}`;
}
