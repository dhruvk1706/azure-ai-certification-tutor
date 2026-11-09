import { useRef, useState } from "react";
import { api, type Analytics, type Area } from "../api";
import {
  buttonClass,
  Card,
  Empty,
  ErrorNotice,
  Loading,
  NewerVersionNotice,
  PageError,
  PracticeNotice,
  ProgressBar,
  useLoad,
} from "../ui";
import { AttemptHistory, newAttemptId } from "./PracticePage";

const STANDINGS: Record<Area["standing"], string> = {
  strength: "Strength",
  developing: "Developing",
  weakness: "Weakness",
  insufficient_data: "Not enough answers yet",
};
const STANDING_STYLES: Record<Area["standing"], string> = {
  strength: "bg-emerald-100 text-emerald-900",
  developing: "bg-amber-100 text-amber-900",
  weakness: "bg-red-100 text-red-900",
  insufficient_data: "bg-slate-100 text-slate-700",
};
const READINESS: Record<Analytics["readiness"], string> = {
  likely_ready: "Likely ready",
  borderline: "Borderline",
  not_ready: "Not ready yet",
  insufficient_data: "Not enough evidence yet",
};

function Standing({ area }: { area: Area }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${STANDING_STYLES[area.standing]}`}
    >
      {STANDINGS[area.standing]}
    </span>
  );
}

function AdaptiveButton() {
  const pending = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function start() {
    pending.current ??= newAttemptId();
    setBusy(true);
    setError(null);
    try {
      const attempt = await api.startAttempt(
        { mode: "practice", adaptive: true, question_count: 10 },
        pending.current,
      );
      pending.current = null;
      window.location.hash = `#/practice/${attempt.id}`;
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-2">
      <button
        type="button"
        className={buttonClass()}
        disabled={busy}
        onClick={() => void start()}
      >
        {busy ? "Starting…" : "Start 10 adaptive questions"}
      </button>
      {error ? <ErrorNotice error={error} /> : null}
    </div>
  );
}

export function PerformancePage() {
  const { data, error, loading, reload } = useLoad(() => api.analytics(), []);
  if (loading) return <Loading label="Loading your performance…" />;
  if (error || !data) return <PageError error={error} onRetry={reload} />;

  return (
    <div className="space-y-5">
      <NewerVersionNotice
        version={data.version_number}
        latest={data.latest_version_number}
      />
      <PracticeNotice text={data.notice} />

      <div className="grid gap-5 md:grid-cols-3">
        <Card title="Readiness estimate">
          <p className="text-3xl font-semibold">
            {data.readiness_percent === null
              ? "–"
              : `${data.readiness_percent}%`}
          </p>
          <p className="mt-1 font-medium">{READINESS[data.readiness]}</p>
          <p className="mt-2 text-xs text-slate-600">
            Accuracy in each domain, weighted by its share of the exam. Domains
            you haven't answered count as 0%. Needs at least 20 answers and 3 in
            every domain to give a verdict. {data.pass_percent}% is a practice
            mark, not Microsoft's scaled passing score.
          </p>
        </Card>
        <Card title="Accuracy">
          <p className="text-3xl font-semibold">
            {data.percent === null ? "–" : `${data.percent}%`}
          </p>
          <p className="mt-1 text-sm text-slate-600">
            {data.correct} correct of {data.answered} graded answers on syllabus
            version {data.version_number}.
          </p>
        </Card>
        <Card title="Mock exams">
          <p className="text-3xl font-semibold">{data.mock_exams_taken}</p>
          <p className="mt-1 text-sm text-slate-600">
            {data.mock_exams_taken
              ? `Latest ${data.latest_mock_percent}%, best ${data.best_mock_percent}%.`
              : "No mock exam submitted yet."}
          </p>
        </Card>
      </div>

      <div className="grid items-start gap-5 md:grid-cols-2">
        <Card title="By domain">
          <ul className="space-y-4">
            {data.domains.map((domain) => (
              <li key={domain.domain_id}>
                <div className="flex flex-wrap justify-between gap-2 text-sm">
                  <span>
                    {domain.position}. {domain.name}{" "}
                    <span className="text-slate-500">
                      ({domain.weight_min}–{domain.weight_max}%)
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="font-medium">
                      {domain.correct}/{domain.answered}
                    </span>
                    <Standing area={domain} />
                  </span>
                </div>
                <div className="mt-1">
                  <ProgressBar
                    percent={domain.percent ?? 0}
                    label={`${domain.name} accuracy`}
                  />
                </div>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Practise next">
          {data.recommendations.length ? (
            <ul className="mb-4 space-y-3 text-sm">
              {data.recommendations.map((item) => (
                <li key={item.topic.subskill_id}>
                  <a
                    className="font-medium text-blue-800 underline"
                    href={`#/practice?level=subskill&id=${item.topic.subskill_id}`}
                  >
                    {item.topic.code} {item.topic.subskill}
                  </a>
                  <div className="text-xs text-slate-600">
                    {item.reason === "low_accuracy"
                      ? `${item.correct} of ${item.answered} correct so far`
                      : "Not practised yet"}{" "}
                    · {item.available_questions} questions available · domain
                    weight {item.topic.weight_min}–{item.topic.weight_max}%
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="mb-4">
              <Empty title="Nothing to recommend yet">
                Recommendations need questions in the bank.
              </Empty>
            </div>
          )}
          <AdaptiveButton />
        </Card>
      </div>

      <div className="grid items-start gap-5 md:grid-cols-2">
        <Card title="By skill">
          <ul className="space-y-2 text-sm">
            {data.skills.map((skill) => (
              <li
                key={skill.skill_id}
                className="flex flex-wrap items-center justify-between gap-2"
              >
                <span>
                  {skill.code} {skill.name}
                </span>
                <span className="flex items-center gap-2">
                  <span className="font-medium">
                    {skill.answered ? `${skill.percent}%` : "–"}
                  </span>
                  <Standing area={skill} />
                </span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Attempt history">
          <AttemptHistory attempts={data.attempts} />
        </Card>
      </div>
    </div>
  );
}
