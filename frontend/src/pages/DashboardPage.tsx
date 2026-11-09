import { useState, type ReactNode } from "react";
import { api, type Analytics, type Dashboard, type Plan } from "../api";
import {
  buttonStyle,
  lessonHref,
  Loading,
  Meter,
  NewerVersionNotice,
  PageError,
  Panel,
  ProgressRing,
  useLoad,
} from "../ui";
import { READINESS } from "./PlanPage";

const WEAK_REASONS: Record<string, string> = {
  failed_check: "Comprehension check not passed",
  low_familiarity: "Low self-assessed familiarity",
};
const PRACTICE_REASONS: Record<string, string> = {
  low_accuracy: "Low accuracy in practice",
  not_attempted: "Not practised yet",
};

function greeting() {
  const hour = new Date().getHours();
  return hour < 12
    ? "Good morning"
    : hour < 18
      ? "Good afternoon"
      : "Good evening";
}

/** A small dashed note shown in place of data the learner hasn't produced yet. */
function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-xl bg-(--q-raised) p-3">
      <dt className="text-xs text-(--q-muted)">{label}</dt>
      <dd className="font-bold">{children}</dd>
    </div>
  );
}

function Hero({ data }: { data: Dashboard }) {
  const next = data.next_lesson;
  const fresh =
    data.overall.completed + data.overall.in_progress === 0 &&
    data.checks_submitted === 0;

  return (
    <Panel className="grid gap-5 lg:grid-cols-[1fr_22rem]">
      <div className="space-y-4">
        <div>
          <p className="text-xs font-semibold tracking-widest text-(--q-violet-soft) uppercase">
            AI-103 certification prep · syllabus v{data.version_number}
          </p>
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight sm:text-3xl">
            {greeting()},{" "}
            <span className="bg-linear-to-r from-(--q-blue-soft) to-(--q-violet-soft) bg-clip-text text-transparent">
              {fresh ? "welcome aboard" : "welcome back"}
            </span>
          </h1>
          <p className="mt-1 text-sm text-(--q-muted)">
            {fresh
              ? "Your progress starts with your first lesson. Nothing is locked, so begin wherever you like."
              : data.last_activity_at
                ? `Last activity ${new Date(data.last_activity_at).toLocaleString()}.`
                : "Pick up where you left off."}
          </p>
        </div>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <ProgressRing percent={data.overall.percent} />
          <div className="min-w-0 flex-1 space-y-2">
            <h2 className="text-lg font-bold">Overall completion</h2>
            <p className="text-sm">
              {data.overall.completed} of {data.overall.total} objectives
              completed, {data.overall.in_progress} in progress. Syllabus
              version {data.version_number}.
            </p>
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <Stat label="Lessons completed">{data.lessons_completed}</Stat>
              <Stat label="Checks passed">
                {data.checks_passed} of {data.checks_submitted}
              </Stat>
            </dl>
          </div>
        </div>
      </div>

      {next ? (
        <div className="flex flex-col justify-between gap-3 rounded-2xl bg-linear-to-br from-(--q-blue) to-(--q-violet) p-5 text-white shadow-[0_0_40px_-10px_var(--q-violet)]">
          <h2 className="text-xs font-bold tracking-widest uppercase">
            Next recommended lesson
          </h2>
          <p>
            <span className="block text-lg leading-snug font-bold">
              {next.topic.code} {next.topic.subskill}
            </span>
            <span className="mt-1 block text-sm text-white/85">
              {next.reason} About {next.minutes} minutes.
            </span>
          </p>
          <div className="flex flex-wrap gap-2">
            <a
              href={lessonHref("subskill", next.topic.subskill_id)}
              className="inline-flex items-center gap-2 rounded-full bg-white/20 px-4 py-2 text-sm font-bold hover:bg-white/30"
            >
              {fresh
                ? "Start learning"
                : next.kind === "review"
                  ? "Continue learning: review"
                  : "Continue learning"}{" "}
              <span aria-hidden="true">→</span>
            </a>
            {!data.has_plan && (
              <a
                href="#/plan"
                className="inline-flex items-center rounded-full border border-white/40 px-4 py-2 text-sm font-semibold hover:bg-white/10"
              >
                Personalize with a learning path
              </a>
            )}
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border border-(--q-done) p-5">
          <h2 className="font-bold text-(--q-done)">All objectives done</h2>
          <p className="mt-1 text-sm text-(--q-muted)">
            You have completed every objective and passed every check. Practice
            exams show how ready you are.
          </p>
        </div>
      )}
    </Panel>
  );
}

/** Study time isn't recorded, so this shows the goal and the plan's load, never time spent. */
function WeeklyGoal({ plan }: { plan: ReturnType<typeof useLoad<Plan>> }) {
  const data = plan.data;
  let body: ReactNode;
  if (plan.loading) body = <Loading label="Loading your weekly goal…" />;
  else if (!data)
    body = <EmptyNote>Your weekly goal is unavailable.</EmptyNote>;
  else if (!data.inputs) {
    body = (
      <EmptyNote>
        No weekly goal yet.{" "}
        <a
          href="#/plan"
          className="font-semibold text-(--q-blue-soft) underline"
        >
          Build your learning path
        </a>{" "}
        to set study hours and get a week-by-week schedule.
      </EmptyNote>
    );
  } else {
    const goal = data.inputs.weekly_hours * 60;
    const thisWeek = data.items.filter((item) => item.week === 1);
    const planned = thisWeek.reduce((sum, item) => sum + item.minutes, 0);
    const percent = Math.min(100, Math.round((planned * 100) / goal));
    body = (
      <div className="space-y-3">
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <Stat label="Weekly goal">{data.inputs.weekly_hours} hours</Stat>
          <Stat label="Planned this week">{thisWeek.length} objectives</Stat>
        </dl>
        <div>
          <p className="mb-1 flex justify-between text-xs text-(--q-muted)">
            <span>This week's plan</span>
            <span>
              {Math.round(planned / 6) / 10} of {data.inputs.weekly_hours} h
            </span>
          </p>
          <Meter percent={percent} label="This week's plan against your goal" />
        </div>
        {data.summary?.on_track === false && (
          <p className="text-sm text-(--q-danger)">
            Behind for your exam on {data.summary.exam_date}.
          </p>
        )}
        {data.summary?.on_track === true && (
          <p className="text-sm text-(--q-done)">
            On track for your exam on {data.summary.exam_date}.
          </p>
        )}
        <p className="text-xs text-(--q-muted)">
          Time spent studying isn't tracked yet, so this compares the planned
          workload with your goal.
        </p>
      </div>
    );
  }
  return (
    <Panel id="goal-title" title="Weekly study goal">
      {body}
    </Panel>
  );
}

function Domains({ data }: { data: Dashboard }) {
  return (
    <Panel id="domains-title" title="Completion by domain">
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {data.domains.map((domain) => {
          const cleared = domain.total > 0 && domain.completed === domain.total;
          return (
            <li
              key={domain.domain_id}
              className="flex flex-col gap-3 rounded-2xl border border-(--q-line) bg-(--q-raised)/60 p-4 hover:border-(--q-blue-soft)"
            >
              <div className="flex items-start gap-3">
                <span
                  aria-hidden="true"
                  className={`grid h-9 w-9 shrink-0 place-items-center rounded-full border-2 text-sm font-extrabold ${
                    cleared
                      ? "border-(--q-done) bg-(--q-done) text-(--q-bg)"
                      : "border-(--q-blue-soft) shadow-[0_0_14px_-2px_var(--q-blue)]"
                  }`}
                >
                  {cleared ? "✓" : domain.position}
                </span>
                <div className="min-w-0">
                  <h3 className="text-sm leading-snug font-bold">
                    {domain.position}. {domain.name}
                  </h3>
                  <p className="text-xs text-(--q-muted)">
                    {domain.weight_min}–{domain.weight_max}% of the exam
                  </p>
                </div>
              </div>
              <div>
                <p className="mb-1 flex justify-between text-xs text-(--q-muted)">
                  <span>
                    {domain.in_progress > 0 &&
                      `${domain.in_progress} in progress`}
                  </span>
                  <span className="font-semibold text-(--q-text)">
                    {domain.completed}/{domain.total}
                  </span>
                </p>
                <Meter percent={domain.percent} label={domain.name} />
              </div>
              <div className="mt-auto flex flex-wrap gap-2">
                <a
                  className={buttonStyle()}
                  href={lessonHref("domain", domain.domain_id)}
                >
                  Study<span className="sr-only"> {domain.name}</span>
                </a>
                <a
                  className={buttonStyle()}
                  href={`#/practice?level=domain&id=${domain.domain_id}`}
                >
                  Practise<span className="sr-only"> {domain.name}</span>
                </a>
              </div>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

function WeakAreas({
  data,
  analytics,
}: {
  data: Dashboard;
  analytics: ReturnType<typeof useLoad<Analytics>>;
}) {
  const practice = analytics.data?.recommendations ?? [];
  const started = data.overall.completed + data.overall.in_progress > 0;

  return (
    <Panel id="weak-title" title="Weak areas and next steps">
      <div className="space-y-5">
        <section aria-labelledby="practice-weak">
          <h3 id="practice-weak" className="mb-2 text-sm font-semibold">
            From practice and mock exams
          </h3>
          {analytics.loading ? (
            <Loading label="Loading practice results…" />
          ) : !analytics.data ? (
            <EmptyNote>Practice results are unavailable.</EmptyNote>
          ) : analytics.data.answered === 0 ? (
            <EmptyNote>
              No practice answers yet.{" "}
              <a
                href="#/practice"
                className="font-semibold text-(--q-blue-soft) underline"
              >
                Take a practice quiz
              </a>{" "}
              and weak areas show up here.
            </EmptyNote>
          ) : (
            <>
              <p className="mb-2 text-sm">
                Readiness:{" "}
                <span className="font-bold">
                  {READINESS[analytics.data.readiness]}
                  {analytics.data.readiness_percent !== null &&
                    ` · ${analytics.data.readiness_percent}%`}
                </span>{" "}
                <a
                  href="#/performance"
                  className="text-xs font-semibold text-(--q-blue-soft) underline"
                >
                  See performance
                </a>
              </p>
              {practice.length ? (
                <ul className="space-y-2">
                  {practice.slice(0, 5).map((item) => (
                    <li
                      key={item.topic.subskill_id}
                      className="flex flex-wrap items-center gap-2 rounded-lg border border-(--q-line) p-2.5"
                    >
                      <span className="min-w-0 flex-1 text-sm">
                        {item.topic.code} {item.topic.subskill}
                        <span className="block text-xs text-(--q-muted)">
                          {PRACTICE_REASONS[item.reason] ?? item.reason}
                          {item.percent !== null &&
                            ` · ${item.correct} of ${item.answered} correct`}
                        </span>
                      </span>
                      <a
                        className={buttonStyle()}
                        href={`#/practice?level=subskill&id=${item.topic.subskill_id}`}
                      >
                        Practise
                      </a>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyNote>No weak areas in your practice results.</EmptyNote>
              )}
            </>
          )}
        </section>

        <section aria-labelledby="lesson-weak">
          <h3 id="lesson-weak" className="mb-2 text-sm font-semibold">
            From lesson checks and your self-assessment
          </h3>
          {data.weak_areas.length ? (
            <ul className="space-y-2">
              {data.weak_areas.map(({ topic, reason }) => (
                <li
                  key={topic.subskill_id}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-(--q-line) p-2.5"
                >
                  <span className="min-w-0 flex-1 text-sm">
                    {topic.code} {topic.subskill}
                    <span className="block text-xs text-(--q-muted)">
                      {WEAK_REASONS[reason] ?? reason}
                    </span>
                  </span>
                  <a
                    className={buttonStyle()}
                    href={lessonHref("subskill", topic.subskill_id)}
                  >
                    Lesson
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyNote>
              {started
                ? "No weak areas yet. Nothing needs extra attention right now."
                : "No weak areas yet. They appear after a self-assessment or a comprehension check."}
            </EmptyNote>
          )}
        </section>
      </div>
    </Panel>
  );
}

/** Loaded on its own, so the sandbox can never stop the dashboard from showing. */
function LabProgress() {
  const { data, error } = useLoad(() => api.labs(), []);
  if (error) {
    return (
      <p className="text-sm text-(--q-muted)">Lab progress is unavailable.</p>
    );
  }
  if (!data) return <Loading label="Loading labs…" />;
  const completed = data.filter((lab) => lab.status === "completed").length;
  const started = data.filter((lab) => lab.status === "in_progress").length;
  const percent = Math.round((completed / Math.max(data.length, 1)) * 100);
  return (
    <div className="space-y-2">
      <p className="text-sm text-(--q-muted)">
        {completed} of {data.length} guided labs completed, {started} in
        progress.
      </p>
      <Meter percent={percent} label="Sandbox labs completed" />
    </div>
  );
}

function QuickAccess() {
  const cards = [
    {
      href: "#/tutor",
      icon: "✦",
      title: "AI Tutor",
      text: "Ask questions answered from the official syllabus.",
      action: "Ask the tutor",
    },
    {
      href: "#/practice",
      icon: "◎",
      title: "Practice exams",
      text: "Topic quizzes and timed mock exams with explanations.",
      action: "Start practising",
    },
    {
      href: "#/sandbox?view=labs",
      icon: "⬡",
      title: "Azure sandbox",
      text: "Guided labs in a simulated Azure, with no subscription or charges.",
      action: "Open sandbox labs",
      extra: <LabProgress />,
    },
  ];
  return (
    <Panel id="quick-title" title="Quick access">
      <ul className="grid gap-3 md:grid-cols-3 lg:grid-cols-1">
        {cards.map((card) => (
          <li
            key={card.href}
            className="flex flex-col gap-3 rounded-2xl border border-(--q-line) bg-(--q-raised)/60 p-4"
          >
            <div className="flex items-center gap-3">
              <span
                aria-hidden="true"
                className="grid h-9 w-9 place-items-center rounded-xl bg-linear-to-br from-(--q-blue) to-(--q-violet) text-white"
              >
                {card.icon}
              </span>
              <h3 className="font-bold">{card.title}</h3>
            </div>
            <p className="text-sm text-(--q-muted)">{card.text}</p>
            {card.extra}
            <a
              className={`${buttonStyle()} mt-auto self-start`}
              href={card.href}
            >
              {card.action}
            </a>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/** Destructive, so each button asks first. Plans, lessons and sandbox resources stay. */
function ResetData({ onProgressCleared }: { onProgressCleared: () => void }) {
  const [message, setMessage] = useState("");
  const clear = async (
    action: () => Promise<void>,
    ask: string,
    done: string,
  ) => {
    if (!window.confirm(ask)) return;
    try {
      await action();
      setMessage(done);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not clear.");
    }
  };
  return (
    <Panel id="reset-title" title="Reset">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={buttonStyle("danger")}
          onClick={() =>
            clear(
              async () => {
                await api.clearProgress();
                onProgressCleared();
              },
              "Clear all progress? Topic and lesson completion, quiz and exam attempts and lab progress are deleted. This can't be undone.",
              "Progress cleared.",
            )
          }
        >
          Clear progress
        </button>
        <button
          type="button"
          className={buttonStyle("danger")}
          onClick={() =>
            clear(
              api.clearMemory,
              "Clear tutor memory? Every tutor conversation is deleted. This can't be undone.",
              "Tutor memory cleared.",
            )
          }
        >
          Clear tutor memory
        </button>
        <p role="status" className="text-sm text-(--q-muted)">
          {message}
        </p>
      </div>
    </Panel>
  );
}

export function DashboardPage() {
  const { data, error, loading, reload } = useLoad(() => api.dashboard(), []);
  // Both are extras: if either fails, the rest of the dashboard still shows.
  const plan = useLoad(() => api.plan(), []);
  const analytics = useLoad(() => api.analytics(), []);

  if (loading) return <Loading label="Loading your progress…" />;
  if (error || !data) return <PageError error={error} onRetry={reload} />;

  return (
    <div className="quest -mx-4 space-y-5 px-4 py-5 sm:mx-0 sm:rounded-3xl sm:p-6">
      <NewerVersionNotice
        version={data.version_number}
        latest={data.latest_version_number}
      />
      <Hero data={data} />
      <div className="grid items-start gap-5 lg:grid-cols-[1fr_24rem]">
        <Domains data={data} />
        <WeeklyGoal plan={plan} />
      </div>
      <div className="grid items-start gap-5 lg:grid-cols-2">
        <WeakAreas data={data} analytics={analytics} />
        <QuickAccess />
      </div>
      <ResetData
        onProgressCleared={() => {
          reload();
          plan.reload();
          analytics.reload();
        }}
      />
    </div>
  );
}
