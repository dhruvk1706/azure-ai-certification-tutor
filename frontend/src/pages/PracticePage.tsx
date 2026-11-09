import { useRef, useState } from "react";
import {
  api,
  type AttemptRequest,
  type AttemptSummary,
  type Difficulty,
  type GenerateResult,
  type QuestionKind,
  type ScopeLevel,
} from "../api";
import {
  buttonClass,
  Card,
  ErrorNotice,
  Loading,
  NewerVersionNotice,
  PageError,
  PracticeNotice,
  useLoad,
} from "../ui";
import { TopicOptions } from "./LessonsPage";

const DIFFICULTIES: Difficulty[] = ["easy", "medium", "hard"];

export const REJECTION_REASONS: Record<string, string> = {
  invalid_shape: "The reply was not a well-formed question",
  invalid_answer_index: "Its answer was not one of the options",
  duplicate_options: "Two options were the same",
  missing_scenario: "A scenario question had no scenario",
  ambiguous_option: "It used an “all/none of the above” style option",
  contains_link: "It contained a link",
  claims_official_question: "It claimed to be a real exam question",
  missing_explanation: "It had no usable explanation",
  unknown_source: "It cited a source that was not supplied",
  excerpt_not_in_source:
    "Its quoted evidence is not on the Microsoft Learn page",
  answer_not_in_excerpt: "Its evidence does not single out the answer",
  duplicate: "The bank already has this question",
  not_verified: "The independent check gave no verdict",
  ambiguous: "The independent check found more than one right answer",
  unsupported_by_source: "The independent check found no support in the source",
  answer_disputed: "The independent check chose a different answer",
  explanation_unsupported:
    "Its explanation claims things the Microsoft Learn text does not say",
};

export function newAttemptId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function attemptLabel(attempt: AttemptSummary) {
  if (attempt.mode === "mock") return "Mock exam";
  return attempt.selection === "adaptive"
    ? "Adaptive practice"
    : "Topic practice";
}

export function AttemptHistory({ attempts }: { attempts: AttemptSummary[] }) {
  if (!attempts.length) {
    return (
      <p className="text-sm text-slate-500">
        Quizzes and exams you start are kept here.
      </p>
    );
  }
  return (
    <ul className="space-y-2 text-sm">
      {attempts.map((attempt) => (
        <li key={attempt.id}>
          <a
            className="font-medium text-blue-800 underline"
            href={`#/practice/${attempt.id}`}
          >
            {attemptLabel(attempt)} · {attempt.question_count} questions
          </a>
          <div className="text-xs text-slate-600">
            {new Date(attempt.started_at).toLocaleString()} ·{" "}
            {attempt.status === "in_progress"
              ? `in progress, ${attempt.answered_count} answered`
              : `${attempt.score} of ${attempt.question_count} (${attempt.percent}%)`}
            {attempt.submit_reason === "time_expired" && " · time ran out"}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** One idempotency key per start request, so a retried click can't start twice. */
function useStarter() {
  const pending = useRef<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ form: string; error: unknown }>();

  async function start(form: string, body: AttemptRequest) {
    pending.current ??= newAttemptId();
    setBusy(form);
    setFailure(undefined);
    try {
      const attempt = await api.startAttempt(body, pending.current);
      pending.current = null;
      window.location.hash = `#/practice/${attempt.id}`;
    } catch (error) {
      setFailure({ form, error });
    } finally {
      setBusy(null);
    }
  }
  // Different inputs are a different request.
  const changed = () => {
    pending.current = null;
  };
  const errorFor = (form: string) =>
    failure?.form === form ? <ErrorNotice error={failure.error} /> : null;
  return { start, busy, changed, errorFor };
}

function NumberField({
  label,
  value,
  onChange,
  max,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  max: number;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        type="number"
        min={1}
        max={max}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 font-normal"
      />
    </label>
  );
}

export function PracticePage({
  level,
  topicId,
}: {
  level: string | null;
  topicId?: number;
}) {
  const syllabus = useLoad(() => api.syllabus(), []);
  const bank = useLoad(() => api.questionBank(), []);
  const history = useLoad(() => api.attempts(), []);
  const starter = useStarter();

  const linked = level && topicId ? `${level}:${topicId}` : "";
  const [topic, setTopic] = useState<string | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty | "">("");
  const [practiceCount, setPracticeCount] = useState(5);
  const [adaptiveCount, setAdaptiveCount] = useState(10);
  const [examCount, setExamCount] = useState(20);
  const [examMinutes, setExamMinutes] = useState(30);
  const selected = topic ?? linked;

  const [target, setTarget] = useState("");
  const [genDifficulty, setGenDifficulty] = useState<Difficulty>("medium");
  const [kind, setKind] = useState<QuestionKind>("mcq");
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState<GenerateResult | null>(null);
  const [genError, setGenError] = useState<unknown>(null);

  async function generate() {
    setGenerating(true);
    setGenError(null);
    setGenerated(null);
    try {
      setGenerated(
        await api.generateQuestions(Number(target), 3, genDifficulty, kind),
      );
      bank.reload();
    } catch (error) {
      setGenError(error);
    } finally {
      setGenerating(false);
    }
  }

  // Keep the page up while the bank refreshes after a generation.
  if ((syllabus.loading && !syllabus.data) || (bank.loading && !bank.data)) {
    return <Loading />;
  }
  if (syllabus.error || !syllabus.data) {
    return <PageError error={syllabus.error} onRetry={syllabus.reload} />;
  }
  if (bank.error || !bank.data) {
    return <PageError error={bank.error} onRetry={bank.reload} />;
  }
  const withSources = bank.data.objectives.filter((o) => o.sources.length);

  return (
    <div className="space-y-5">
      <NewerVersionNotice
        version={bank.data.version_number}
        latest={bank.data.latest_version_number}
      />
      <PracticeNotice text={bank.data.notice} />

      <div className="grid items-start gap-5 lg:grid-cols-3">
        <Card title="Practise a topic">
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              const [scopeLevel, scopeId] = selected.split(":");
              void starter.start("topic", {
                mode: "practice",
                scope_level: scopeLevel as ScopeLevel,
                scope_id: Number(scopeId),
                question_count: practiceCount,
                ...(difficulty ? { difficulty } : {}),
              });
            }}
            onChange={starter.changed}
          >
            <label className="block text-sm font-medium">
              Topic
              <select
                value={selected}
                onChange={(event) => setTopic(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 font-normal"
              >
                <option value="">Choose a topic…</option>
                <TopicOptions syllabus={syllabus.data} />
              </select>
            </label>
            <label className="block text-sm font-medium">
              Difficulty
              <select
                value={difficulty}
                onChange={(event) =>
                  setDifficulty(event.target.value as Difficulty | "")
                }
                className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 font-normal capitalize"
              >
                <option value="">Any</option>
                {DIFFICULTIES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <NumberField
              label="Questions"
              value={practiceCount}
              onChange={setPracticeCount}
              max={60}
            />
            <button
              type="submit"
              className={buttonClass()}
              disabled={!selected || starter.busy !== null}
            >
              {starter.busy === "topic" ? "Starting…" : "Start practice"}
            </button>
            <p className="text-xs text-slate-500">
              Each answer is checked straight away, with the explanation and its
              Microsoft Learn evidence.
            </p>
            {starter.errorFor("topic")}
          </form>
        </Card>

        <Card title="Adaptive practice">
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void starter.start("adaptive", {
                mode: "practice",
                adaptive: true,
                question_count: adaptiveCount,
              });
            }}
            onChange={starter.changed}
          >
            <p className="text-sm text-slate-600">
              Questions you got wrong come first, then objectives where your
              record is weakest, weighted by exam domain.
            </p>
            <NumberField
              label="Questions"
              value={adaptiveCount}
              onChange={setAdaptiveCount}
              max={60}
            />
            <button
              type="submit"
              className={buttonClass()}
              disabled={starter.busy !== null}
            >
              {starter.busy === "adaptive" ? "Starting…" : "Start adaptive"}
            </button>
            {starter.errorFor("adaptive")}
          </form>
        </Card>

        <Card title="Mock exam">
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void starter.start("mock", {
                mode: "mock",
                question_count: examCount,
                time_limit_minutes: examMinutes,
              });
            }}
            onChange={starter.changed}
          >
            <p className="text-sm text-slate-600">
              Timed, drawn at random across all domains by exam weight. Answers
              are revealed after you submit, and the exam is submitted for you
              when time runs out. The bank holds {bank.data.total_questions}{" "}
              questions.
            </p>
            <NumberField
              label="Questions"
              value={examCount}
              onChange={setExamCount}
              max={60}
            />
            <NumberField
              label="Time limit (minutes)"
              value={examMinutes}
              onChange={setExamMinutes}
              max={240}
            />
            <button
              type="submit"
              className={buttonClass()}
              disabled={starter.busy !== null}
            >
              {starter.busy === "mock" ? "Starting…" : "Start mock exam"}
            </button>
            {starter.errorFor("mock")}
          </form>
        </Card>
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[1fr_20rem]">
        <Card title="Question bank">
          <form
            className="mb-4 flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              void generate();
            }}
          >
            <label className="block min-w-64 flex-1 text-sm font-medium">
              Generate 3 questions for
              <select
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 font-normal"
              >
                <option value="">Choose an objective with a source…</option>
                {withSources.map(({ topic }) => (
                  <option key={topic.subskill_id} value={topic.subskill_id}>
                    {topic.code} {topic.subskill}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm font-medium">
              Difficulty
              <select
                value={genDifficulty}
                onChange={(event) =>
                  setGenDifficulty(event.target.value as Difficulty)
                }
                className="mt-1 rounded-md border border-slate-300 bg-white p-2 font-normal capitalize"
              >
                {DIFFICULTIES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm font-medium">
              Format
              <select
                value={kind}
                onChange={(event) =>
                  setKind(event.target.value as QuestionKind)
                }
                className="mt-1 rounded-md border border-slate-300 bg-white p-2 font-normal"
              >
                <option value="mcq">Multiple choice</option>
                <option value="scenario">Scenario</option>
              </select>
            </label>
            <button
              type="submit"
              className={buttonClass()}
              disabled={!target || generating}
            >
              {generating ? "Writing and checking…" : "Generate"}
            </button>
          </form>
          {generating && (
            <p role="status" className="mb-3 text-xs text-slate-500">
              Questions are written, then checked against the Microsoft Learn
              text and by two further model calls: one answers each question
              from its evidence alone, one checks the explanation. This can take
              a minute.
            </p>
          )}
          {genError ? (
            <div className="mb-3">
              <ErrorNotice error={genError} onRetry={() => void generate()} />
            </div>
          ) : null}
          {generated && (
            <div
              role="status"
              className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm"
            >
              <p className="font-medium">
                {generated.accepted} added, {generated.rejected.length}{" "}
                rejected. This objective now has {generated.active_questions}{" "}
                questions.
              </p>
              {generated.rejected.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-700">
                  {generated.rejected.map((rejection, index) => (
                    <li key={index}>
                      {REJECTION_REASONS[rejection.reason] ?? rejection.reason}
                      {rejection.stem && `: “${rejection.stem}”`}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {withSources.length === 0 && (
            <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
              No Microsoft Learn pages are attached yet, so no questions can be
              generated. Run{" "}
              <code>
                python -m app.assessment.sources add --subskill ID &lt;URL&gt;
              </code>{" "}
              in the backend.
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr>
                  <th className="py-1 pr-3 font-medium">Objective</th>
                  <th className="py-1 pr-3 font-medium">Learn sources</th>
                  <th className="py-1 font-medium">Questions</th>
                </tr>
              </thead>
              <tbody>
                {bank.data.objectives.map((objective) => (
                  <tr
                    key={objective.topic.subskill_id}
                    className="border-t border-slate-100 align-top"
                  >
                    <td className="py-1.5 pr-3">
                      {objective.topic.code} {objective.topic.subskill}
                    </td>
                    <td className="py-1.5 pr-3">
                      {objective.sources.length
                        ? objective.sources.map((source) => (
                            <a
                              key={source.id}
                              href={source.url}
                              target="_blank"
                              rel="noreferrer"
                              className="block text-blue-800 underline"
                            >
                              {source.title}
                            </a>
                          ))
                        : "None"}
                    </td>
                    <td className="py-1.5">{objective.questions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Your attempts">
          {history.loading && !history.data && <Loading />}
          {history.error ? (
            <ErrorNotice error={history.error} onRetry={history.reload} />
          ) : null}
          {history.data && <AttemptHistory attempts={history.data} />}
        </Card>
      </div>
    </div>
  );
}
