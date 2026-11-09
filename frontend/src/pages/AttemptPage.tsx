import { useEffect, useState } from "react";
import { api, ApiError, type Attempt, type AttemptItem } from "../api";
import {
  buttonClass,
  Card,
  ErrorNotice,
  Loading,
  PageError,
  PracticeNotice,
  useLoad,
} from "../ui";
import { attemptLabel } from "./PracticePage";

function clock(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

/** Counts down from the server's remaining time. The server enforces the deadline;
 * this only tells the learner, and asks the server to settle the exam at zero. */
function Countdown({
  seconds,
  onExpire,
}: {
  seconds: number;
  onExpire: () => void;
}) {
  const [endsAt] = useState(() => Date.now() + seconds * 1000);
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    const timer = setInterval(() => {
      const value = Math.max(0, Math.ceil((endsAt - Date.now()) / 1000));
      setLeft(value);
      if (value === 0) {
        clearInterval(timer);
        onExpire();
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [endsAt, onExpire]);
  return (
    <p
      role="timer"
      aria-label="Time remaining"
      className={`text-2xl font-semibold tabular-nums ${left < 60 ? "text-red-700" : ""}`}
    >
      {clock(left)}
    </p>
  );
}

function FeedbackPanel({ item }: { item: AttemptItem }) {
  const feedback = item.feedback!;
  return (
    <div
      className={`mt-4 rounded-md border p-3 text-sm ${feedback.is_correct ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`}
    >
      <p className="font-semibold">
        {feedback.is_correct
          ? "Correct."
          : feedback.chosen_index === null
            ? "Not answered."
            : "Incorrect."}{" "}
        The answer is {String.fromCharCode(65 + feedback.correct_index)}:{" "}
        {item.options[feedback.correct_index]}
      </p>
      <p className="mt-2">{feedback.explanation}</p>
      <figure className="mt-3 rounded border border-slate-200 bg-white p-2">
        <blockquote className="text-slate-800">
          “{feedback.source.excerpt}”
        </blockquote>
        <figcaption className="mt-1 text-xs text-slate-600">
          Evidence from Microsoft Learn:{" "}
          <a
            href={feedback.source.url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-800 underline"
          >
            {feedback.source.title}
          </a>{" "}
          · Objective {feedback.topic.code} {feedback.topic.subskill}
        </figcaption>
      </figure>
    </div>
  );
}

function Question({
  attempt,
  item,
  saving,
  choosing,
  onChoose,
}: {
  attempt: Attempt;
  item: AttemptItem;
  saving: boolean;
  choosing: number | null;
  onChoose: (index: number) => void;
}) {
  const picked = choosing ?? item.chosen_index;
  const locked =
    attempt.status !== "in_progress" ||
    (attempt.mode === "practice" && item.chosen_index !== null) ||
    saving;
  return (
    <fieldset>
      <legend className="text-xs font-medium tracking-wide text-slate-500 uppercase">
        Question {item.position} of {attempt.question_count} ·{" "}
        {item.kind === "scenario" ? "Scenario" : "Multiple choice"} ·{" "}
        {item.difficulty}
      </legend>
      {item.scenario && (
        <p className="mt-3 rounded-md bg-slate-50 p-3 text-sm whitespace-pre-wrap">
          {item.scenario}
        </p>
      )}
      <p className="mt-3 font-medium whitespace-pre-wrap">{item.stem}</p>
      <div className="mt-3 space-y-2 text-sm">
        {item.options.map((option, index) => {
          const correct = item.feedback?.correct_index === index;
          const wrongPick =
            item.feedback &&
            !item.feedback.is_correct &&
            item.chosen_index === index;
          return (
            <label
              key={index}
              className={`flex items-start gap-2 rounded-md border px-3 py-2 ${correct ? "border-emerald-400" : wrongPick ? "border-red-400" : "border-slate-200"}`}
            >
              <input
                type="radio"
                className="mt-1"
                name={`q-${attempt.id}-${item.position}`}
                checked={picked === index}
                disabled={locked}
                onChange={() => onChoose(index)}
              />
              <span>
                <span className="font-medium">
                  {String.fromCharCode(65 + index)}.
                </span>{" "}
                {option}
                {correct && (
                  <span className="ml-2 font-medium text-emerald-700">
                    Correct answer
                  </span>
                )}
                {wrongPick && (
                  <span className="ml-2 font-medium text-red-700">
                    Your answer
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>
      {item.feedback && <FeedbackPanel item={item} />}
    </fieldset>
  );
}

function Result({ attempt }: { attempt: Attempt }) {
  const byDomain = new Map<string, { correct: number; total: number }>();
  for (const item of attempt.items) {
    const topic = item.feedback!.topic;
    const key = `${topic.code.split(".")[0]}. ${topic.domain}`;
    const entry = byDomain.get(key) ?? { correct: 0, total: 0 };
    entry.total += 1;
    entry.correct += Number(item.feedback!.is_correct);
    byDomain.set(key, entry);
  }
  return (
    <Card title="Result">
      <p role="status" className="text-2xl font-semibold">
        {attempt.score} of {attempt.question_count} ({attempt.percent}%)
      </p>
      {attempt.mode === "mock" && (
        <p className="mt-1 text-sm">
          {attempt.passed
            ? `At or above the ${attempt.pass_percent}% practice mark.`
            : `Below the ${attempt.pass_percent}% practice mark.`}{" "}
          The real exam reports a scaled score, so this is only a guide.
        </p>
      )}
      {attempt.submit_reason === "time_expired" && (
        <p className="mt-1 text-sm font-medium text-amber-800">
          Time ran out, so the exam was submitted automatically with your saved
          answers.
        </p>
      )}
      <ul className="mt-3 space-y-1 text-sm">
        {[...byDomain].map(([domain, { correct, total }]) => (
          <li key={domain} className="flex justify-between gap-3">
            <span>{domain}</span>
            <span className="font-medium">
              {correct}/{total}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap gap-2">
        <a className={buttonClass()} href="#/performance">
          See performance
        </a>
        <a className={buttonClass("secondary")} href="#/practice">
          Back to practice
        </a>
      </div>
    </Card>
  );
}

function AttemptView({
  attempt,
  onChange,
  onRefresh,
}: {
  attempt: Attempt;
  onChange: (attempt: Attempt) => void;
  onRefresh: () => void;
}) {
  const firstOpen = attempt.items.findIndex(
    (item) => item.chosen_index === null,
  );
  const [current, setCurrent] = useState(Math.max(firstOpen, 0));
  const [saving, setSaving] = useState(false);
  // Shown as picked while it saves, so the click is acknowledged at once.
  const [choosing, setChoosing] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const open = attempt.status === "in_progress";
  const item = attempt.items[current];
  const unanswered = attempt.items.filter(
    (entry) => entry.chosen_index === null,
  ).length;

  async function run(action: () => Promise<Attempt>) {
    setSaving(true);
    setError(null);
    try {
      onChange(await action());
    } catch (failure) {
      setError(failure);
      // A conflict means the server moved on (time ran out, or already submitted).
      if (failure instanceof ApiError && failure.status === 409) onRefresh();
    } finally {
      setSaving(false);
      setConfirming(false);
    }
  }

  return (
    <div className="space-y-5">
      <PracticeNotice text={attempt.notice} />
      <div className="grid items-start gap-5 lg:grid-cols-[1fr_16rem]">
        <div className="space-y-5">
          {!open && <Result attempt={attempt} />}
          <Card>
            <Question
              attempt={attempt}
              item={item}
              saving={saving}
              choosing={choosing}
              onChoose={(index) => {
                setChoosing(index);
                void run(() =>
                  api.answer(attempt.id, item.position, index),
                ).finally(() => setChoosing(null));
              }}
            />
            {error ? (
              <div className="mt-3">
                <ErrorNotice error={error} />
              </div>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                className={buttonClass("secondary")}
                disabled={current === 0}
                onClick={() => setCurrent(current - 1)}
              >
                Previous
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                disabled={current === attempt.items.length - 1}
                onClick={() => setCurrent(current + 1)}
              >
                Next
              </button>
            </div>
          </Card>
        </div>

        <aside className="space-y-5">
          <Card title={attemptLabel(attempt)}>
            {open && attempt.remaining_seconds !== null && (
              <Countdown
                key={attempt.server_time}
                seconds={attempt.remaining_seconds}
                onExpire={onRefresh}
              />
            )}
            <p className="text-sm text-slate-600">
              {attempt.items.length - unanswered} of {attempt.question_count}{" "}
              answered · syllabus version {attempt.version_number}
            </p>
            <nav aria-label="Questions" className="mt-3 flex flex-wrap gap-1">
              {attempt.items.map((entry, index) => {
                const tone = entry.feedback
                  ? entry.feedback.is_correct
                    ? "bg-emerald-600 text-white"
                    : "bg-red-600 text-white"
                  : entry.chosen_index !== null
                    ? "bg-blue-700 text-white"
                    : "bg-white text-slate-800";
                return (
                  <button
                    key={entry.position}
                    type="button"
                    aria-label={`Question ${entry.position}`}
                    aria-current={index === current ? "step" : undefined}
                    onClick={() => setCurrent(index)}
                    className={`h-8 w-8 rounded border border-slate-300 text-xs font-medium ${tone} ${index === current ? "ring-2 ring-blue-400" : ""}`}
                  >
                    {entry.position}
                  </button>
                );
              })}
            </nav>
            {open && (
              <div className="mt-4 space-y-2">
                {confirming ? (
                  <>
                    <p className="text-sm">
                      {unanswered
                        ? `${unanswered} unanswered, which count as wrong.`
                        : "All questions answered."}{" "}
                      Submit now?
                    </p>
                    <button
                      type="button"
                      className={buttonClass()}
                      disabled={saving}
                      onClick={() =>
                        void run(() => api.submitAttempt(attempt.id))
                      }
                    >
                      Confirm submit
                    </button>{" "}
                    <button
                      type="button"
                      className={buttonClass("secondary")}
                      onClick={() => setConfirming(false)}
                    >
                      Keep going
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className={buttonClass(
                      attempt.mode === "mock" ? "primary" : "secondary",
                    )}
                    disabled={saving}
                    onClick={() => setConfirming(true)}
                  >
                    {attempt.mode === "mock" ? "Submit exam" : "Finish quiz"}
                  </button>
                )}
                {attempt.mode === "mock" && (
                  <p className="text-xs text-slate-500">
                    Answers save as you choose them, so you can leave and come
                    back before the time runs out.
                  </p>
                )}
              </div>
            )}
          </Card>
        </aside>
      </div>
    </div>
  );
}

export function AttemptPage({ attemptId }: { attemptId: number }) {
  const { data, error, loading, reload, setData } = useLoad(
    () => api.attempt(attemptId),
    [attemptId],
  );
  if (loading && !data) return <Loading label="Loading…" />;
  if (error || !data) return <PageError error={error} onRetry={reload} />;
  return (
    <AttemptView
      key={`${data.id}-${data.status}`}
      attempt={data}
      onChange={setData}
      onRefresh={reload}
    />
  );
}
