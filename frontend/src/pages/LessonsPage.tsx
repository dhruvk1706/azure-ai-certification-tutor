import { useState } from "react";
import {
  api,
  type Depth,
  type Lesson,
  type ScopeLevel,
  type Syllabus,
} from "../api";
import {
  buttonClass,
  Card,
  Empty,
  ErrorNotice,
  Loading,
  NewerVersionNotice,
  PageError,
  SyllabusReferences,
  useLoad,
} from "../ui";

interface Topic {
  level: ScopeLevel;
  id: number;
}

const DEPTHS: Depth[] = ["beginner", "intermediate", "advanced"];

function decode(value: string): Topic | null {
  const [level, id] = value.split(":");
  return level && id ? { level: level as ScopeLevel, id: Number(id) } : null;
}

/** Options for every domain, skill and subskill, in syllabus order. */
export function TopicOptions({ syllabus }: { syllabus: Syllabus }) {
  return syllabus.domains.map((domain) => (
    <optgroup key={domain.id} label={`${domain.position}. ${domain.name}`}>
      <option value={`domain:${domain.id}`}>
        Whole domain: {domain.name} ({domain.weight_min}–{domain.weight_max}%)
      </option>
      {domain.skills.flatMap((skill) => [
        <option key={`s${skill.id}`} value={`skill:${skill.id}`}>
          {domain.position}.{skill.position} Skill: {skill.name}
        </option>,
        ...skill.subskills.map((subskill) => (
          <option key={`o${subskill.id}`} value={`subskill:${subskill.id}`}>
            {"  "}
            {domain.position}.{skill.position}.{subskill.position}{" "}
            {subskill.text}
          </option>
        )),
      ])}
    </optgroup>
  ));
}

function ChecksForm({
  lesson,
  onChange,
}: {
  lesson: Lesson;
  onChange: (lesson: Lesson) => void;
}) {
  const outcome = lesson.progress.check;
  const [answers, setAnswers] = useState<(number | undefined)[]>(
    () => outcome?.results.map((result) => result.chosen_index) ?? [],
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const complete =
    lesson.checks.every((_, index) => answers[index] !== undefined) &&
    answers.length === lesson.checks.length;

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      onChange(await api.submitChecks(lesson.id, answers as number[]));
    } catch (failure) {
      setError(failure);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
      className="space-y-5"
    >
      {lesson.checks.map((check, questionIndex) => {
        const result = outcome?.results[questionIndex];
        return (
          <fieldset key={questionIndex}>
            <legend className="font-medium">
              {questionIndex + 1}. {check.question}
            </legend>
            <div className="mt-2 space-y-1 text-sm">
              {check.options.map((option, optionIndex) => (
                <label key={optionIndex} className="flex items-start gap-2">
                  <input
                    type="radio"
                    className="mt-1"
                    name={`check-${lesson.id}-${questionIndex}`}
                    checked={answers[questionIndex] === optionIndex}
                    onChange={() => {
                      const next = [...answers];
                      next[questionIndex] = optionIndex;
                      setAnswers(next);
                    }}
                  />
                  <span>
                    {option}
                    {result?.correct_index === optionIndex && (
                      <span className="ml-2 font-medium text-emerald-700">
                        Correct answer
                      </span>
                    )}
                  </span>
                </label>
              ))}
            </div>
            {result && (
              <p
                className={`mt-2 text-sm ${result.is_correct ? "text-emerald-800" : "text-red-800"}`}
              >
                {result.is_correct ? "Correct." : "Not quite."}{" "}
                {result.explanation}
              </p>
            )}
          </fieldset>
        );
      })}
      {error ? <ErrorNotice error={error} /> : null}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          className={buttonClass()}
          disabled={!complete || saving}
        >
          {saving ? "Checking…" : outcome ? "Submit again" : "Check answers"}
        </button>
        {outcome && (
          <p role="status" className="text-sm font-medium">
            Score {outcome.score} of {outcome.total}:{" "}
            {outcome.passed
              ? "passed"
              : "not passed, so this stays on your weak areas"}
            . Attempts: {outcome.attempts}.
          </p>
        )}
      </div>
    </form>
  );
}

function LessonView({
  lesson,
  onChange,
}: {
  lesson: Lesson;
  onChange: (lesson: Lesson) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const completed = lesson.progress.status === "completed";

  async function setStatus(status: "in_progress" | "completed") {
    setSaving(true);
    setError(null);
    try {
      onChange(await api.setLessonStatus(lesson.id, status));
    } catch (failure) {
      setError(failure);
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="space-y-5">
      <Card>
        <h2 className="text-xl font-semibold">{lesson.title}</h2>
        <p className="mt-1 text-xs text-slate-500">
          {lesson.depth} · syllabus version {lesson.version_number} · written by{" "}
          {lesson.llm_model} via {lesson.llm_provider} · generated{" "}
          {new Date(lesson.created_at).toLocaleDateString()}
        </p>
        <div className="mt-4">
          <SyllabusReferences references={lesson.references} />
        </div>
      </Card>

      <Card>
        <p className="mb-3 rounded-md bg-slate-100 px-3 py-2 text-xs text-slate-700">
          AI-generated explanation, not official Microsoft content. The study
          guide only lists what the exam measures, so confirm product details on
          Microsoft Learn.
        </p>
        <h3 className="font-semibold">Learning objectives</h3>
        <ul className="mt-1 mb-4 list-disc space-y-1 pl-5 text-sm">
          {lesson.learning_objectives.map((objective, index) => (
            <li key={index}>{objective}</li>
          ))}
        </ul>
        <h3 className="font-semibold">Explanation</h3>
        <p className="mt-1 mb-4 text-sm leading-6 whitespace-pre-wrap">
          {lesson.explanation}
        </p>
        <h3 className="font-semibold">Practical Azure examples</h3>
        <ul className="mt-1 mb-4 space-y-3 text-sm">
          {lesson.azure_examples.map((example, index) => (
            <li key={index}>
              <span className="font-medium">{example.title}</span>
              <p className="whitespace-pre-wrap">{example.scenario}</p>
            </li>
          ))}
        </ul>
        <h3 className="font-semibold">Key takeaways</h3>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
          {lesson.key_takeaways.map((takeaway, index) => (
            <li key={index}>{takeaway}</li>
          ))}
        </ul>
      </Card>

      <Card title="Comprehension check">
        <ChecksForm lesson={lesson} onChange={onChange} />
      </Card>

      <Card>
        <div className="flex flex-wrap items-center gap-3">
          {completed ? (
            <>
              <p role="status" className="text-sm font-medium text-emerald-800">
                Completed
                {lesson.progress.completed_at &&
                  ` on ${new Date(lesson.progress.completed_at).toLocaleDateString()}`}
              </p>
              <button
                type="button"
                className={buttonClass("secondary")}
                disabled={saving}
                onClick={() => void setStatus("in_progress")}
              >
                Mark as not finished
              </button>
            </>
          ) : (
            <button
              type="button"
              className={buttonClass()}
              disabled={saving}
              onClick={() => void setStatus("completed")}
            >
              {saving
                ? "Saving…"
                : `Mark lesson complete (${lesson.references.length} ${lesson.references.length === 1 ? "objective" : "objectives"})`}
            </button>
          )}
          <a className={buttonClass("secondary")} href="#/dashboard">
            Back to dashboard
          </a>
        </div>
        {error ? (
          <div className="mt-3">
            <ErrorNotice error={error} />
          </div>
        ) : null}
      </Card>
    </article>
  );
}

function LessonPanel({ lessonId }: { lessonId: number }) {
  const { data, error, loading, reload, setData } = useLoad(
    () => api.lesson(lessonId),
    [lessonId],
  );
  if (loading) return <Loading label="Loading lesson…" />;
  if (error || !data) return <PageError error={error} onRetry={reload} />;
  return <LessonView key={data.id} lesson={data} onChange={setData} />;
}

export function LessonsPage({
  lessonId,
  level,
  topicId,
}: {
  lessonId?: number;
  level: string | null;
  topicId?: number;
}) {
  const syllabus = useLoad(() => api.syllabus(), []);
  const lessons = useLoad(() => api.lessons(), [lessonId]);
  const linked = level && topicId ? `${level}:${topicId}` : "";
  const [chosen, setChosen] = useState<string | null>(null);
  const [depth, setDepth] = useState<Depth>("beginner");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const selected = chosen ?? linked;

  async function open() {
    const topic = decode(selected);
    if (!topic) return;
    setGenerating(true);
    setError(null);
    try {
      const lesson = await api.openLesson(topic.level, topic.id, depth);
      window.location.hash = `#/lessons/${lesson.id}`;
    } catch (failure) {
      setError(failure);
    } finally {
      setGenerating(false);
    }
  }

  if (syllabus.loading) return <Loading />;
  if (syllabus.error || !syllabus.data) {
    return <PageError error={syllabus.error} onRetry={syllabus.reload} />;
  }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[20rem_1fr]">
      <aside className="space-y-5">
        <NewerVersionNotice
          version={syllabus.data.version_number}
          latest={syllabus.data.latest_version_number}
        />
        <Card title="Open a lesson">
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void open();
            }}
          >
            <label className="block text-sm font-medium">
              Topic
              <select
                value={selected}
                onChange={(event) => setChosen(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 font-normal"
              >
                <option value="">Choose a topic…</option>
                <TopicOptions syllabus={syllabus.data} />
              </select>
            </label>
            <label className="block text-sm font-medium">
              Depth
              <select
                value={depth}
                onChange={(event) => setDepth(event.target.value as Depth)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 font-normal capitalize"
              >
                {DEPTHS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              className={buttonClass()}
              disabled={!selected || generating}
            >
              {generating ? "Preparing lesson…" : "Open lesson"}
            </button>
            {generating && (
              <p role="status" className="text-xs text-slate-500">
                A new lesson can take a minute to write. Stored lessons open
                straight away.
              </p>
            )}
            {error ? (
              <ErrorNotice error={error} onRetry={() => void open()} />
            ) : null}
          </form>
        </Card>

        <Card title="Your lessons">
          {lessons.loading && !lessons.data && <Loading />}
          {lessons.error ? (
            <ErrorNotice error={lessons.error} onRetry={lessons.reload} />
          ) : null}
          {lessons.data?.length === 0 && (
            <p className="text-sm text-slate-500">
              Lessons you open are kept here.
            </p>
          )}
          <ul className="space-y-2 text-sm">
            {lessons.data?.map((lesson) => (
              <li key={lesson.id}>
                <a
                  className="font-medium text-blue-800 underline"
                  href={`#/lessons/${lesson.id}`}
                  aria-current={lesson.id === lessonId ? "page" : undefined}
                >
                  {lesson.title}
                </a>
                <div className="text-xs text-slate-600">
                  {lesson.depth} ·{" "}
                  {lesson.status === "completed" ? "completed" : "in progress"}
                  {lesson.check_total !== null &&
                    ` · check ${lesson.check_score}/${lesson.check_total}`}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </aside>

      <div>
        {lessonId ? (
          <LessonPanel key={lessonId} lessonId={lessonId} />
        ) : (
          <Empty title="No lesson open">
            Choose a domain, skill or objective and a depth to read its lesson.
          </Empty>
        )}
      </div>
    </div>
  );
}
