import { useEffect, useRef, useState } from "react";
import {
  api,
  type Analytics,
  type Domain,
  type Plan,
  type PlanItem,
  type Syllabus,
} from "../api";
import {
  buttonStyle,
  ErrorNotice,
  lessonHref,
  Loading,
  Meter,
  NewerVersionNotice,
  PageError,
  Panel,
  ProgressRing,
  useLoad,
} from "../ui";

/** Values are the plan engine's familiarity levels 0-3 (none, basic, working, strong). */
const LEVELS = [
  { label: "New to it", hint: "Haven't used it yet" },
  { label: "Basic", hint: "Read about it or tried a demo" },
  { label: "Working", hint: "Used it in a real project" },
  { label: "Strong", hint: "Could explain it to others" },
];
const HOUR_PRESETS = [3, 5, 8, 12];
const DEFAULT_WEEKLY_HOURS = 5;
const STEPS = ["Your pace", "What you know", "Review"];
// XP is encouragement only. Readiness comes from graded practice and mock exams.
const XP_PER_OBJECTIVE = 100;
const XP_PER_CHAPTER = 250;
export const READINESS: Record<Analytics["readiness"], string> = {
  likely_ready: "Likely ready",
  borderline: "Borderline",
  not_ready: "Not ready yet",
  insufficient_data: "Not enough evidence yet",
};

type ObjectiveState = "completed" | "review" | "in_progress" | "not_started";
const STATE_LABELS: Record<ObjectiveState, string> = {
  completed: "Completed",
  review: "Needs review",
  in_progress: "In progress",
  not_started: "Not started",
};
const STATE_ICONS: Record<ObjectiveState, string> = {
  completed: "✓",
  review: "↻",
  in_progress: "◐",
  not_started: "",
};
const STATE_STYLES: Record<ObjectiveState, string> = {
  completed: "border-(--q-done) bg-(--q-done) text-(--q-bg)",
  review: "border-(--q-warn) text-(--q-warn)",
  in_progress: "border-(--q-blue-soft) text-(--q-blue-soft)",
  not_started: "border-(--q-line) text-(--q-muted)",
};

/**
 * The plan lists only what is left, so an objective missing from it is completed. A
 * "review" item is completed with a failed latest check. Null without a plan.
 */
function objectiveStates(
  syllabus: Syllabus,
  plan: Plan,
): Map<number, ObjectiveState> | null {
  if (!plan.inputs) return null;
  const items = new Map(
    plan.items.map((item) => [item.topic.subskill_id, item]),
  );
  const states = new Map<number, ObjectiveState>();
  for (const domain of syllabus.domains) {
    for (const skill of domain.skills) {
      for (const objective of skill.subskills) {
        const item = items.get(objective.id);
        states.set(
          objective.id,
          !item
            ? "completed"
            : item.kind === "review"
              ? "review"
              : item.status === "in_progress"
                ? "in_progress"
                : "not_started",
        );
      }
    }
  }
  return states;
}

function domainIds(domain: Domain) {
  return domain.skills.flatMap((skill) => skill.subskills.map((o) => o.id));
}

function tally(ids: number[], states: Map<number, ObjectiveState> | null) {
  // Matches the dashboard: an objective awaiting review still counts as completed.
  const done = ids.filter((id) => {
    const state = states?.get(id);
    return state === "completed" || state === "review";
  }).length;
  return {
    done,
    total: ids.length,
    percent: ids.length ? Math.floor((done * 100) / ids.length) : 0,
  };
}

// --- Onboarding ---

function PathSetup({
  syllabus,
  plan,
  version,
  onSaved,
  onCancel,
}: {
  syllabus: Syllabus;
  plan: Plan;
  version?: number;
  onSaved: (plan: Plan) => void;
  onCancel?: () => void;
}) {
  const inputs = plan.inputs;
  const [step, setStep] = useState(0);
  const [hours, setHours] = useState(
    String(inputs?.weekly_hours ?? DEFAULT_WEEKLY_HOURS),
  );
  const [examDate, setExamDate] = useState(inputs?.exam_date ?? "");
  // Per-skill values are kept, and a chapter's answer only replaces them once changed.
  const [familiarity, setFamiliarity] = useState<Record<string, number>>(
    inputs?.familiarity ?? {},
  );
  const [levels, setLevels] = useState<Record<number, number>>(() =>
    Object.fromEntries(
      syllabus.domains.map((domain) => [
        domain.id,
        Math.min(
          LEVELS.length - 1,
          ...domain.skills.map((skill) => inputs?.familiarity[skill.id] ?? 0),
        ),
      ]),
    ),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);

  useEffect(() => {
    // Keyboard and screen reader users land on the new step, not the old button.
    if (moved.current) heading.current?.focus();
    moved.current = true;
  }, [step]);

  const hoursNumber = Number(hours);
  const hoursValid =
    Number.isInteger(hoursNumber) && hoursNumber >= 1 && hoursNumber <= 80;

  function choose(domain: Domain, level: number) {
    setLevels({ ...levels, [domain.id]: level });
    setFamiliarity({
      ...familiarity,
      ...Object.fromEntries(domain.skills.map((skill) => [skill.id, level])),
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      onSaved(
        await api.savePlan(
          {
            familiarity,
            weekly_hours: hoursNumber,
            exam_date: examDate || null,
          },
          version,
        ),
      );
    } catch (failure) {
      setError(failure);
      setSaving(false);
    }
  }

  const fieldClass =
    "mt-1 w-full rounded-lg border border-(--q-line) bg-(--q-bg) p-2 font-normal text-(--q-text)";

  return (
    <Panel
      id="setup-title"
      title={inputs ? "Adjust your path" : "Build your path in 3 quick steps"}
      className="shadow-[0_0_60px_-30px_var(--q-violet)]"
    >
      <ol aria-label="Setup steps" className="mb-5 flex gap-2 text-xs">
        {STEPS.map((label, index) => (
          <li
            key={label}
            aria-current={index === step ? "step" : undefined}
            className={`flex flex-1 items-center gap-2 rounded-full border px-3 py-1.5 ${
              index === step
                ? "border-(--q-blue-soft) bg-(--q-raised) text-(--q-text)"
                : "border-(--q-line) text-(--q-muted)"
            }`}
          >
            <span
              aria-hidden="true"
              className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[0.65rem] font-bold ${
                index < step
                  ? "bg-(--q-done) text-(--q-bg)"
                  : index === step
                    ? "bg-linear-to-r from-(--q-blue) to-(--q-violet) text-white"
                    : "bg-(--q-line)"
              }`}
            >
              {index < step ? "✓" : index + 1}
            </span>
            <span className="truncate">{label}</span>
          </li>
        ))}
      </ol>

      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (step < STEPS.length - 1) setStep(step + 1);
          else void save();
        }}
      >
        <h3
          ref={heading}
          tabIndex={-1}
          className="text-lg font-bold focus:outline-none"
        >
          Step {step + 1} of {STEPS.length}: {STEPS[step]}
        </h3>

        {step === 0 && (
          <div className="space-y-4">
            <fieldset>
              <legend className="text-sm font-medium">
                How many hours can you study each week?
              </legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {HOUR_PRESETS.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    aria-pressed={hoursNumber === preset}
                    onClick={() => setHours(String(preset))}
                    className={`rounded-full border px-4 py-1.5 text-sm font-semibold ${
                      hoursNumber === preset
                        ? "border-(--q-blue-soft) bg-(--q-blue) text-white"
                        : "border-(--q-line) bg-(--q-raised) hover:border-(--q-blue-soft)"
                    }`}
                  >
                    {preset} h
                  </button>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-sm font-medium">
                Hours per week
                <input
                  type="number"
                  min={1}
                  max={80}
                  required
                  value={hours}
                  aria-invalid={!hoursValid}
                  aria-describedby="hours-help"
                  onChange={(event) => setHours(event.target.value)}
                  className={fieldClass}
                />
                <span
                  id="hours-help"
                  className="mt-1 block text-xs font-normal text-(--q-muted)"
                >
                  A whole number from 1 to 80.
                </span>
              </label>
              <label className="block text-sm font-medium">
                Exam date (optional)
                <input
                  type="date"
                  value={examDate}
                  onChange={(event) => setExamDate(event.target.value)}
                  className={fieldClass}
                />
              </label>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <p className="text-sm text-(--q-muted)">
              One quick answer per chapter. It only orders your path, and every
              lesson stays open whatever you pick.
            </p>
            {syllabus.domains.map((domain) => (
              <fieldset key={domain.id}>
                <legend className="text-sm font-semibold">
                  Chapter {domain.position}: {domain.name}
                </legend>
                <div className="mt-2 grid grid-cols-2 gap-2 lg:grid-cols-4">
                  {LEVELS.map((level, value) => (
                    <label
                      key={level.label}
                      className="group relative cursor-pointer rounded-xl border border-(--q-line) bg-(--q-raised) p-2.5 pr-8 text-sm hover:border-(--q-blue-soft) has-checked:border-(--q-blue-soft) has-checked:bg-linear-to-br has-checked:from-(--q-blue)/45 has-checked:to-(--q-violet)/45 has-checked:shadow-[0_0_18px_-6px_var(--q-blue)] has-focus-visible:outline-2 has-focus-visible:outline-(--q-blue-soft)"
                    >
                      <input
                        type="radio"
                        name={`domain-${domain.id}`}
                        value={value}
                        checked={levels[domain.id] === value}
                        onChange={() => choose(domain, value)}
                        className="sr-only"
                      />
                      <span
                        aria-hidden="true"
                        className="absolute top-2 right-2 hidden h-5 w-5 place-items-center rounded-full bg-(--q-blue-soft) text-[0.65rem] font-bold text-(--q-bg) group-has-checked:grid"
                      >
                        ✓
                      </span>
                      <span className="block font-semibold">{level.label}</span>
                      <span className="block text-xs text-(--q-muted)">
                        {level.hint}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3 text-sm">
            <dl className="grid gap-2 sm:grid-cols-2">
              <div className="rounded-xl bg-(--q-raised) p-3">
                <dt className="text-(--q-muted)">Weekly study time</dt>
                <dd className="font-semibold">{hoursNumber} hours</dd>
              </div>
              <div className="rounded-xl bg-(--q-raised) p-3">
                <dt className="text-(--q-muted)">Exam date</dt>
                <dd className="font-semibold">{examDate || "Not set"}</dd>
              </div>
            </dl>
            <ul className="space-y-1">
              {syllabus.domains.map((domain) => (
                <li key={domain.id} className="flex justify-between gap-3">
                  <span className="text-(--q-muted)">
                    {domain.position}. {domain.name}
                  </span>
                  <span className="shrink-0 font-semibold">
                    {LEVELS[levels[domain.id]].label}
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-(--q-muted)">
              Syllabus version {plan.version_number}. Changing these
              recalculates the plan and never changes what you have completed.
            </p>
          </div>
        )}

        {error ? <ErrorNotice error={error} /> : null}

        <div className="flex flex-wrap items-center gap-2">
          {step > 0 && (
            <button
              type="button"
              className={buttonStyle()}
              onClick={() => setStep(step - 1)}
            >
              Back
            </button>
          )}
          {onCancel && (
            <button type="button" className={buttonStyle()} onClick={onCancel}>
              Cancel
            </button>
          )}
          <button
            type="submit"
            className={`${buttonStyle("primary")} ml-auto`}
            disabled={!hoursValid || saving}
          >
            {step < STEPS.length - 1
              ? "Next"
              : saving
                ? "Saving…"
                : inputs
                  ? "Update my path"
                  : "Create my path"}
          </button>
        </div>
      </form>
    </Panel>
  );
}

// --- Progress, milestones, skill tree ---

function Readiness({ version }: { version?: number }) {
  const analytics = useLoad(() => api.analytics(version), [version]);
  const data = analytics.data;
  return (
    <a
      href="#/performance"
      className="block rounded-xl bg-(--q-raised) p-3 hover:ring-1 hover:ring-(--q-blue-soft)"
    >
      <span className="block text-xs text-(--q-muted)">Exam readiness</span>
      <span className="block font-bold">
        {analytics.loading
          ? "Loading…"
          : data
            ? `${READINESS[data.readiness]}${
                data.readiness_percent === null
                  ? ""
                  : ` · ${data.readiness_percent}%`
              }`
            : "Unavailable"}
      </span>
      <span className="block text-xs text-(--q-muted)">
        From practice and mock exam results, not XP
      </span>
    </a>
  );
}

function Hero({
  syllabus,
  plan,
  states,
  version,
}: {
  syllabus: Syllabus;
  plan: Plan;
  states: Map<number, ObjectiveState>;
  version?: number;
}) {
  const overall = tally([...states.keys()], states);
  const cleared = syllabus.domains.filter(
    (domain) => tally(domainIds(domain), states).percent === 100,
  ).length;
  const xp = overall.done * XP_PER_OBJECTIVE + cleared * XP_PER_CHAPTER;
  const next: PlanItem | undefined = plan.items[0];
  const reviews = plan.items.filter((item) => item.kind === "review").length;

  return (
    <Panel className="grid gap-5 lg:grid-cols-[1fr_22rem]">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <ProgressRing percent={overall.percent} />
        <div className="min-w-0 space-y-3">
          <div>
            <p className="text-xs font-semibold tracking-widest text-(--q-violet-soft) uppercase">
              {syllabus.exam_code} learning path · v{plan.version_number}
            </p>
            <p className="text-xl font-extrabold">
              {overall.done} of {overall.total} objectives complete
            </p>
            {reviews > 0 && (
              <p className="text-sm text-(--q-warn)">
                {reviews} to review after a missed check
              </p>
            )}
          </div>
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
            <div className="rounded-xl bg-(--q-raised) p-3">
              <dt className="text-xs text-(--q-muted)">Chapters cleared</dt>
              <dd className="font-bold">
                {cleared} / {syllabus.domains.length}
              </dd>
            </div>
            <div className="rounded-xl bg-(--q-raised) p-3">
              <dt className="text-xs text-(--q-muted)">Path XP</dt>
              <dd className="font-bold text-(--q-blue-soft)">
                {xp.toLocaleString()} XP
              </dd>
            </div>
            <div className="col-span-2 sm:col-span-1">
              <dt className="sr-only">Exam readiness</dt>
              <dd>
                <Readiness version={version} />
              </dd>
            </div>
          </dl>
        </div>
      </div>

      {next ? (
        <a
          href={lessonHref("subskill", next.topic.subskill_id)}
          className="group flex flex-col justify-between gap-3 rounded-2xl bg-linear-to-br from-(--q-blue) to-(--q-violet) p-5 text-white shadow-[0_0_40px_-10px_var(--q-violet)] hover:brightness-110"
        >
          <span className="text-xs font-bold tracking-widest uppercase">
            {next.kind === "review" ? "Review next" : "Up next"}
          </span>
          <span>
            <span className="block text-lg leading-snug font-bold">
              {next.topic.code} {next.topic.subskill}
            </span>
            <span className="mt-1 block text-sm text-white/85">
              {next.topic.skill} · about {next.minutes} minutes
            </span>
          </span>
          <span className="inline-flex items-center gap-2 self-start rounded-full bg-white/15 px-4 py-2 text-sm font-bold group-hover:bg-white/25">
            Continue learning <span aria-hidden="true">→</span>
          </span>
        </a>
      ) : (
        <div className="rounded-2xl border border-(--q-done) p-5">
          <p className="font-bold text-(--q-done)">Nothing left in your plan</p>
          <p className="mt-1 text-sm text-(--q-muted)">
            You have completed every objective and passed every check. Practice
            exams show how ready you are.
          </p>
        </div>
      )}
    </Panel>
  );
}

function Milestones({
  syllabus,
  states,
}: {
  syllabus: Syllabus;
  states: Map<number, ObjectiveState>;
}) {
  const overall = tally([...states.keys()], states);
  const milestones = [
    { label: "First objective", reached: overall.done > 0 },
    { label: "25% of the path", reached: overall.percent >= 25 },
    { label: "Halfway there", reached: overall.percent >= 50 },
    { label: "75% of the path", reached: overall.percent >= 75 },
    ...syllabus.domains.map((domain) => ({
      label: `Chapter ${domain.position} cleared`,
      reached: tally(domainIds(domain), states).percent === 100,
    })),
    { label: "Path complete", reached: overall.percent === 100 },
  ];
  const reached = milestones.filter((m) => m.reached).length;

  return (
    <Panel
      id="milestones-title"
      title={`Milestones · ${reached} of ${milestones.length}`}
    >
      <ul className="flex flex-wrap gap-2">
        {milestones.map((milestone) => (
          <li
            key={milestone.label}
            className={`relative flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold ${
              milestone.reached
                ? "border-(--q-violet-soft) bg-(--q-violet)/25 text-(--q-text)"
                : "border-dashed border-(--q-line) text-(--q-muted)"
            }`}
          >
            <span aria-hidden="true">{milestone.reached ? "★" : "☆"}</span>
            {milestone.label}
            <span className="sr-only">
              {milestone.reached ? "(reached)" : "(not yet reached)"}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function SkillTree({
  syllabus,
  states,
  nextId,
}: {
  syllabus: Syllabus;
  states: Map<number, ObjectiveState> | null;
  nextId?: number;
}) {
  return (
    <Panel id="tree-title" title="Skill tree">
      <p className="-mt-2 mb-4 text-sm text-(--q-muted)">
        {states
          ? "Five chapters, one per exam domain. Every lesson is open: start anywhere."
          : "Five chapters, one per exam domain. Every lesson is open now; create your path to track progress here."}
      </p>
      <ol className="space-y-4">
        {syllabus.domains.map((domain, index) => {
          const chapter = tally(domainIds(domain), states);
          const cleared = !!states && chapter.percent === 100;
          return (
            <li key={domain.id} className="relative pl-12">
              {index < syllabus.domains.length - 1 && (
                <span
                  aria-hidden="true"
                  className="absolute top-10 bottom-[-1rem] hidden sm:block left-[1.15rem] w-0.5 bg-linear-to-b from-(--q-blue) to-(--q-violet) opacity-60"
                />
              )}
              <span
                aria-hidden="true"
                className={`absolute top-0 left-0 grid h-10 w-10 place-items-center rounded-full border-2 text-sm font-extrabold ${
                  cleared
                    ? "border-(--q-done) bg-(--q-done) text-(--q-bg)"
                    : "border-(--q-blue-soft) bg-(--q-raised) shadow-[0_0_16px_-2px_var(--q-blue)]"
                }`}
              >
                {cleared ? "✓" : domain.position}
              </span>
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <h3 className="font-bold">
                  <span className="text-(--q-violet-soft)">
                    Chapter {domain.position}:
                  </span>{" "}
                  {domain.name}
                </h3>
                <span className="text-xs text-(--q-muted)">
                  {domain.weight_min}–{domain.weight_max}% of the exam
                  {states && ` · ${chapter.done}/${chapter.total} objectives`}
                  {cleared && " · Chapter cleared"}
                </span>
              </div>
              {states && (
                <div className="mt-2">
                  <Meter
                    percent={chapter.percent}
                    label={`Chapter ${domain.position} progress`}
                  />
                </div>
              )}
              <a
                href={lessonHref("domain", domain.id)}
                className="mt-2 inline-block text-xs font-semibold text-(--q-blue-soft) underline-offset-2 hover:underline"
              >
                Chapter overview lesson
              </a>
              <ul className="mt-2 -ml-12 space-y-2 sm:ml-0 sm:border-l sm:border-(--q-line) sm:pl-4">
                {domain.skills.map((skill) => {
                  const ids = skill.subskills.map((o) => o.id);
                  const counted = tally(ids, states);
                  return (
                    <li key={skill.id}>
                      <details
                        open={nextId !== undefined && ids.includes(nextId)}
                        className="group rounded-xl border border-(--q-line) bg-(--q-raised)/60 open:bg-(--q-raised)"
                      >
                        <summary className="flex cursor-pointer list-none items-center gap-3 rounded-xl p-3 [&::-webkit-details-marker]:hidden">
                          <span
                            aria-hidden="true"
                            className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border-2 text-xs font-bold ${
                              states && counted.done === counted.total
                                ? STATE_STYLES.completed
                                : states && counted.done > 0
                                  ? STATE_STYLES.in_progress
                                  : STATE_STYLES.not_started
                            }`}
                          >
                            {states && counted.done === counted.total
                              ? "✓"
                              : ""}
                          </span>
                          <span className="min-w-0 flex-1 text-sm font-semibold">
                            {skill.name}
                          </span>
                          {states && (
                            <span className="shrink-0 text-xs text-(--q-muted)">
                              {counted.done}/{counted.total}
                            </span>
                          )}
                          <span
                            aria-hidden="true"
                            className="shrink-0 text-(--q-muted) transition-transform group-open:rotate-90"
                          >
                            ›
                          </span>
                        </summary>
                        <div className="space-y-2 px-3 pb-3">
                          <a
                            href={lessonHref("skill", skill.id)}
                            className="inline-block text-xs font-semibold text-(--q-blue-soft) underline-offset-2 hover:underline"
                          >
                            Skill lesson
                          </a>
                          <ul className="space-y-2">
                            {skill.subskills.map((objective) => {
                              const state = states?.get(objective.id);
                              return (
                                <li
                                  key={objective.id}
                                  className={`flex flex-wrap items-center gap-2 rounded-lg border p-2.5 ${
                                    objective.id === nextId
                                      ? "border-(--q-blue-soft) shadow-[0_0_20px_-8px_var(--q-blue)]"
                                      : "border-(--q-line)"
                                  }`}
                                >
                                  {state && (
                                    <span
                                      aria-hidden="true"
                                      className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border-2 text-[0.65rem] font-bold ${STATE_STYLES[state]}`}
                                    >
                                      {STATE_ICONS[state]}
                                    </span>
                                  )}
                                  <span className="min-w-0 flex-1 text-sm">
                                    {domain.position}.{skill.position}.
                                    {objective.position} {objective.text}
                                    {state && (
                                      <span className="block text-xs text-(--q-muted)">
                                        {STATE_LABELS[state]}
                                        {objective.id === nextId &&
                                          " · Up next"}
                                      </span>
                                    )}
                                  </span>
                                  <span className="flex shrink-0 basis-full flex-wrap justify-end gap-2 sm:basis-auto">
                                    <a
                                      className={buttonStyle()}
                                      href={lessonHref(
                                        "subskill",
                                        objective.id,
                                      )}
                                    >
                                      Lesson
                                    </a>
                                  </span>
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                      </details>
                    </li>
                  );
                })}
              </ul>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

// --- Weekly schedule from the planning engine ---

function Schedule({ plan }: { plan: Plan }) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const summary = plan.summary;
  if (!summary) return null;

  async function explain() {
    setExplaining(true);
    setError(null);
    try {
      setExplanation((await api.explainPlan(plan.version_number)).text);
    } catch (failure) {
      setError(failure);
    } finally {
      setExplaining(false);
    }
  }

  const weeks = new Map<number, PlanItem[]>();
  for (const item of plan.items) {
    weeks.set(item.week, [...(weeks.get(item.week) ?? []), item]);
  }

  return (
    <Panel id="schedule-title" title="Weekly plan">
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {[
          ["Objectives left", summary.remaining_topics],
          [
            "Study time left",
            `${Math.ceil(summary.remaining_minutes / 60)} hours`,
          ],
          ["At your pace", `${summary.weeks_needed} weeks`],
          ["Projected finish", summary.projected_finish],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl bg-(--q-raised) p-3">
            <dt className="text-xs text-(--q-muted)">{label}</dt>
            <dd className="font-bold">{value}</dd>
          </div>
        ))}
      </dl>
      {summary.on_track === true && (
        <p className="mt-3 rounded-lg border border-(--q-done) px-3 py-2 text-sm text-(--q-done)">
          On track for your exam on {summary.exam_date}.
        </p>
      )}
      {summary.on_track === false && (
        <p className="mt-3 rounded-lg border border-(--q-danger) px-3 py-2 text-sm text-(--q-danger)">
          Behind for your exam on {summary.exam_date}.{" "}
          {summary.required_weekly_hours
            ? `Finishing in time needs about ${summary.required_weekly_hours} hours a week. Highest-priority objectives come first.`
            : "That date has passed, so update it."}
        </p>
      )}

      <div className="mt-4">
        <button
          type="button"
          className={buttonStyle()}
          disabled={explaining}
          onClick={() => void explain()}
        >
          {explaining ? "Explaining…" : "Explain this order"}
        </button>
        {error ? (
          <div className="mt-3">
            <ErrorNotice error={error} onRetry={() => void explain()} />
          </div>
        ) : null}
        {explanation && (
          <p className="mt-3 rounded-lg bg-(--q-raised) p-3 text-sm whitespace-pre-wrap">
            <span className="block text-xs font-semibold tracking-wide text-(--q-muted) uppercase">
              AI-generated explanation. The plan's numbers are calculated by the
              app.
            </span>
            {explanation}
          </p>
        )}
      </div>

      <div className="mt-4 space-y-2">
        {[...weeks.entries()].map(([week, items]) => (
          <details
            key={week}
            open={week === 1}
            className="rounded-xl border border-(--q-line) bg-(--q-raised)/60"
          >
            <summary className="cursor-pointer p-3 text-sm font-semibold">
              Week {week}, from {items[0].week_start}
              <span className="ml-2 text-xs font-normal text-(--q-muted)">
                {items.length} objectives
              </span>
            </summary>
            <ul className="space-y-2 px-3 pb-3">
              {items.map((item) => (
                <li
                  key={item.topic.subskill_id}
                  className="flex flex-wrap items-start justify-between gap-2 border-t border-(--q-line) pt-2 first:border-t-0"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      {item.topic.code} {item.topic.subskill}
                      {item.kind === "review" && (
                        <span className="ml-2 rounded bg-(--q-warn)/20 px-1.5 py-0.5 text-xs text-(--q-warn)">
                          Review
                        </span>
                      )}
                      {item.status === "in_progress" && (
                        <span className="ml-2 rounded bg-(--q-blue)/25 px-1.5 py-0.5 text-xs text-(--q-blue-soft)">
                          In progress
                        </span>
                      )}
                      {item.after_exam && (
                        <span className="ml-2 rounded bg-(--q-danger)/20 px-1.5 py-0.5 text-xs text-(--q-danger)">
                          After exam date
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-(--q-muted)">
                      {item.reason} About {item.minutes} minutes.
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <a
                      className={buttonStyle()}
                      href={lessonHref("subskill", item.topic.subskill_id)}
                    >
                      Lesson
                    </a>
                  </div>
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>
    </Panel>
  );
}

export function PlanPage({ targetVersion }: { targetVersion?: number }) {
  const syllabus = useLoad(() => api.syllabus(targetVersion), [targetVersion]);
  const plan = useLoad(() => api.plan(targetVersion), [targetVersion]);
  const [editing, setEditing] = useState(false);

  if ((syllabus.loading && !syllabus.data) || (plan.loading && !plan.data)) {
    return <Loading label="Loading your learning path…" />;
  }
  if (syllabus.error || !syllabus.data) {
    return <PageError error={syllabus.error} onRetry={syllabus.reload} />;
  }
  if (plan.error || !plan.data) {
    return <PageError error={plan.error} onRetry={plan.reload} />;
  }

  const states = objectiveStates(syllabus.data, plan.data);
  const setup = (
    <PathSetup
      key={plan.data.version_number}
      syllabus={syllabus.data}
      plan={plan.data}
      version={targetVersion}
      onSaved={(saved) => {
        plan.setData(saved);
        setEditing(false);
      }}
      onCancel={plan.data.inputs ? () => setEditing(false) : undefined}
    />
  );

  return (
    <div className="quest -mx-4 space-y-5 px-4 py-5 sm:mx-0 sm:rounded-3xl sm:p-6">
      <NewerVersionNotice
        version={plan.data.version_number}
        latest={plan.data.latest_version_number}
      />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">
            Your{" "}
            <span className="bg-linear-to-r from-(--q-blue-soft) to-(--q-violet-soft) bg-clip-text text-transparent">
              learning path
            </span>
          </h1>
          <p className="text-sm text-(--q-muted)">
            {syllabus.data.exam_code} syllabus version{" "}
            {plan.data.version_number}
          </p>
        </div>
        {states && !editing && (
          <div className="flex gap-2">
            <button
              type="button"
              className={buttonStyle()}
              onClick={() => setEditing(true)}
            >
              Adjust path
            </button>
            <button
              type="button"
              className={buttonStyle("danger")}
              onClick={async () => {
                if (
                  !window.confirm(
                    "Clear your learning path? Your answers and schedule are deleted; progress is kept.",
                  )
                )
                  return;
                await api.clearPlan();
                plan.reload();
              }}
            >
              Clear path
            </button>
          </div>
        )}
      </div>

      {!states ? (
        <>
          <p className="text-sm text-(--q-muted)">
            No learning path yet. Answer three short questions and the planner
            orders all five chapters for you.
          </p>
          {setup}
        </>
      ) : (
        <>
          {editing && setup}
          <Hero
            syllabus={syllabus.data}
            plan={plan.data}
            states={states}
            version={targetVersion}
          />
          <Milestones syllabus={syllabus.data} states={states} />
        </>
      )}

      {states && (
        <div className="grid items-start gap-5 xl:grid-cols-[1fr_26rem]">
          <SkillTree
            syllabus={syllabus.data}
            states={states}
            nextId={plan.data.items[0]?.topic.subskill_id}
          />
          <Schedule plan={plan.data} />
        </div>
      )}
    </div>
  );
}
