import { useState } from "react";
import {
  api,
  type AssistantReply,
  type LabCheck,
  type LabDetail,
} from "../api";
import { buttonClass, ErrorNotice, Loading, PageError, useLoad } from "../ui";
import { newId, sandboxHref, useSandbox } from "./SandboxPage";

/** A guided lab beside the portal. Grades come only from the server's Validate. */

const CHECK_STYLES = {
  passed: ["✓", "Passed", "text-emerald-700"],
  failed: ["✗", "Not yet", "text-red-700"],
  not_checked: ["○", "Not checked", "text-slate-400"],
} as const;

function withoutLab() {
  const [path, query] = window.location.hash.split("?");
  const params = new URLSearchParams(query);
  params.delete("lab");
  const rest = params.toString();
  return `${path}${rest ? `?${rest}` : ""}`;
}

function Check({
  check,
  onHint,
  busy,
}: {
  check: LabCheck;
  onHint: () => void;
  busy: boolean;
}) {
  const [icon, label, color] = CHECK_STYLES[check.status];
  return (
    <li className="space-y-1">
      <p className="flex gap-2 text-sm">
        <span className={`font-bold ${color}`} aria-label={label} title={label}>
          {icon}
        </span>
        <span>{check.description}</span>
      </p>
      {check.status === "failed" && check.feedback && (
        <p className="ml-6 text-sm text-red-800">{check.feedback}</p>
      )}
      {check.explanation && (
        <p className="ml-6 text-xs text-emerald-900">{check.explanation}</p>
      )}
      {check.hints.map((hint, index) => (
        <p
          key={hint}
          className="ml-6 rounded bg-blue-50 px-2 py-1 text-xs text-blue-950"
        >
          Hint {index + 1}: {hint}
        </p>
      ))}
      {check.status !== "passed" && check.hints.length < check.hints_total && (
        <button
          type="button"
          className="ml-6 text-xs text-blue-800 underline disabled:opacity-50"
          disabled={busy}
          onClick={onHint}
        >
          {check.hints.length ? "Show another hint" : "Show a hint"} (
          {check.hints.length}/{check.hints_total})
        </button>
      )}
    </li>
  );
}

function Assistant({ labId }: { labId: string }) {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<AssistantReply | null>(null);
  const [asked, setAsked] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function ask() {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      setReply(await api.askLabAssistant(labId, text));
      setAsked(text);
      setQuestion("");
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">Lab assistant</h3>
      <p className="text-xs text-slate-500">
        Explains concepts and your validation results. It sees this lab, your
        simulated resources and the hints you revealed, and it doesn't grade.
      </p>
      {reply && (
        <div className="rounded-md border border-slate-200 bg-white p-3 text-sm">
          <p className="text-xs text-slate-500">You asked: {asked}</p>
          <h4 className="mt-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Assistant · AI-generated
          </h4>
          <p className="mt-1 whitespace-pre-wrap">{reply.answer}</p>
          <p className="mt-2 text-xs text-slate-500">
            {reply.llm_model} via {reply.llm_provider}. {reply.notice}
          </p>
        </div>
      )}
      {error ? (
        <ErrorNotice
          error={error}
          onRetry={() => void ask()}
          retryLabel="Ask again"
        />
      ) : null}
      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          void ask();
        }}
      >
        <label className="sr-only" htmlFor="lab-question">
          Ask the lab assistant
        </label>
        <textarea
          id="lab-question"
          rows={2}
          maxLength={2000}
          value={question}
          placeholder="Why did my last check fail?"
          disabled={busy}
          onChange={(event) => setQuestion(event.target.value)}
          className="w-full rounded-md border border-slate-300 bg-white p-2 text-sm"
        />
        <button
          type="submit"
          className={buttonClass("secondary")}
          disabled={busy || !question.trim()}
        >
          {busy ? "Thinking…" : "Ask"}
        </button>
      </form>
    </section>
  );
}

export function LabPanel({ labId }: { labId: string }) {
  const { lab, changed } = useSandbox();
  const { data, error, loading, reload, setData } = useLoad(
    () => api.lab(labId),
    [labId],
  );
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  async function run(work: () => Promise<LabDetail>, touchesResources = false) {
    setBusy(true);
    setActionError(null);
    try {
      setData(await work());
      if (touchesResources) changed();
    } catch (failure) {
      setActionError(failure);
    } finally {
      setBusy(false);
      setConfirmReset(false);
    }
  }

  if (loading) return <Loading label="Loading lab…" />;
  if (error || !data) {
    return (
      <div className="p-4">
        <PageError error={error} onRetry={reload} />
      </div>
    );
  }

  const checks = data.tasks.flatMap((task) => task.checks);
  const passed = checks.filter((c) => c.status === "passed").length;
  return (
    <div className="space-y-4 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Guided lab · about {data.minutes} min
          </p>
          <h2 className="font-semibold">{data.title}</h2>
        </div>
        <a className="text-xs text-blue-800 underline" href={withoutLab()}>
          Close
        </a>
      </div>
      <p className="text-sm">{data.objective}</p>

      <div className="text-xs text-slate-600">
        <p className="font-semibold">AI-103 objectives</p>
        <ul className="mt-1 list-disc pl-5">
          {(data.syllabus.length
            ? data.syllabus.map((ref) => `${ref.code} ${ref.subskill}`)
            : data.syllabus_text
          ).map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
        <p className="mt-2 font-semibold">Prerequisites</p>
        <ul className="mt-1 list-disc pl-5">
          {data.prerequisites.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </div>

      <div className="space-y-2 rounded-md border border-slate-200 bg-white p-3 text-sm">
        <p>
          <span className="font-semibold">Scenario. </span>
          {data.scenario}
        </p>
        <p>
          <span className="font-semibold">Expected outcome. </span>
          {data.expected_outcome}
        </p>
      </div>

      {data.status === "not_started" ? (
        <button
          type="button"
          className={buttonClass()}
          disabled={busy}
          onClick={() => void run(() => api.startLab(labId), true)}
        >
          {busy ? "Starting…" : "Start lab"}
        </button>
      ) : (
        <>
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {data.instructions.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          {data.resource_group_id && (
            <a
              className="text-sm text-blue-800 underline"
              href={sandboxHref(lab, { id: data.resource_group_id })}
            >
              Open resource group {data.resource_group}
            </a>
          )}

          {data.tasks.map((task) => (
            <section key={task.id}>
              <h3 className="text-sm font-semibold">{task.title}</h3>
              <ul className="mt-1 space-y-2">
                {task.checks.map((check) => (
                  <Check
                    key={check.id}
                    check={check}
                    busy={busy}
                    onHint={() =>
                      void run(() =>
                        api.revealHint(labId, check.id, check.hints.length + 1),
                      )
                    }
                  />
                ))}
              </ul>
            </section>
          ))}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={buttonClass()}
              disabled={busy}
              onClick={() => void run(() => api.validateLab(labId, newId()))}
            >
              {busy ? "Working…" : "Validate"}
            </button>
            {data.last_validation && (
              <span className="text-sm text-slate-600" role="status">
                {passed} of {checks.length} checks passed
              </span>
            )}
          </div>
          {actionError ? <ErrorNotice error={actionError} /> : null}

          {data.completion && (
            <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-950">
              <p className="font-semibold">Lab complete</p>
              <p className="mt-1">{data.completion}</p>
            </div>
          )}
          {data.status === "completed" && !data.completion && (
            <p className="text-xs text-slate-600">
              Completed on {new Date(data.completed_at ?? "").toLocaleString()}.
              Your current configuration no longer passes every check.
            </p>
          )}

          {data.history.length > 0 && (
            <details className="text-xs text-slate-600">
              <summary className="cursor-pointer">
                Attempt history ({data.validations})
              </summary>
              <ul className="mt-1 space-y-0.5">
                {data.history.map((attempt) => (
                  <li key={attempt.id}>
                    {new Date(attempt.created_at).toLocaleString()}:{" "}
                    {attempt.passed_checks}/{attempt.total_checks}
                    {attempt.passed ? " (passed)" : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <Assistant labId={labId} />

          <div className="border-t border-slate-200 pt-3 text-xs">
            {confirmReset ? (
              <div className="space-y-2">
                <p>
                  Reset deletes resource group {data.resource_group} and
                  everything in it, then recreates the starter resources. Your
                  completion, attempts and hints are kept.
                </p>
                <button
                  type="button"
                  className="rounded-md bg-red-700 px-3 py-1.5 font-medium text-white"
                  disabled={busy}
                  onClick={() => void run(() => api.resetLab(labId), true)}
                >
                  Reset lab
                </button>{" "}
                <button
                  type="button"
                  className="underline"
                  onClick={() => setConfirmReset(false)}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="text-slate-600 underline"
                onClick={() => setConfirmReset(true)}
              >
                Reset this lab…
              </button>
            )}
          </div>
        </>
      )}

      <div className="text-xs text-slate-600">
        <p className="font-semibold">Microsoft Learn</p>
        <ul className="mt-1 list-disc pl-5">
          {data.docs.map((doc) => (
            <li key={doc.url}>
              <a
                className="underline"
                href={doc.url}
                target="_blank"
                rel="noreferrer"
              >
                {doc.title}
              </a>
            </li>
          ))}
        </ul>
        {data.approximations.length > 0 && (
          <>
            <p className="mt-2 font-semibold">
              How this lab differs from Azure
            </p>
            <ul className="mt-1 list-disc pl-5">
              {data.approximations.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
