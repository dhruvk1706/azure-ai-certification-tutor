import { createContext, useContext, useState, type ReactNode } from "react";
import {
  api,
  type ActionOutcome,
  type Properties,
  type ResourceDetail,
  type ResourceSummary,
  type ResourceType,
  type SandboxCatalog,
  type SandboxField,
} from "../api";
import {
  buttonClass,
  Card,
  Empty,
  ErrorNotice,
  Loading,
  PageError,
  useLoad,
} from "../ui";
import { LabPanel } from "./LabPanel";

/** Simulated Azure portal. Every write goes to the backend, which validates it. */

interface Sandbox {
  catalog: SandboxCatalog;
  lab: string | null;
  revision: number;
  changed: () => void;
}
const SandboxContext = createContext<Sandbox | null>(null);

export function useSandbox(): Sandbox {
  const value = useContext(SandboxContext);
  if (!value) throw new Error("useSandbox outside SandboxPage");
  return value;
}

export function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface Target {
  id?: number;
  view?: string;
  type?: string;
  parent?: number;
  q?: string;
}

/** A sandbox link that keeps the open lab beside it. */
export function sandboxHref(lab: string | null, target: Target = {}) {
  const params = new URLSearchParams();
  for (const key of ["view", "type", "parent", "q"] as const) {
    const value = target[key];
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  if (lab) params.set("lab", lab);
  const query = params.toString();
  return `#/sandbox${target.id ? `/${target.id}` : ""}${query ? `?${query}` : ""}`;
}

function go(href: string) {
  window.location.hash = href;
}

const STATE_STYLES: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-900",
  running: "bg-emerald-100 text-emerald-900",
  stopped: "bg-slate-200 text-slate-800",
  soft_deleted: "bg-amber-100 text-amber-900",
};
const STATE_LABELS: Record<string, string> = {
  succeeded: "Succeeded",
  running: "Running",
  stopped: "Stopped",
  soft_deleted: "Deleted (recoverable)",
};

function StateBadge({ state }: { state: string }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${STATE_STYLES[state] ?? "bg-slate-100"}`}
    >
      {STATE_LABELS[state] ?? state}
    </span>
  );
}

export function SimulatedBadge() {
  return (
    <span className="rounded bg-amber-300 px-2 py-0.5 text-xs font-bold tracking-wide text-amber-950 uppercase">
      Simulated
    </span>
  );
}

function regionLabel(catalog: SandboxCatalog, region: string | null) {
  return catalog.regions.find((r) => r.name === region)?.label ?? region ?? "";
}

function typeOf(catalog: SandboxCatalog, key: string): ResourceType {
  const found = catalog.types.find((t) => t.key === key);
  if (!found) throw new Error(`unknown type ${key}`);
  return found;
}

// --- Page ---

const NAV = [
  { view: "", label: "Home" },
  { view: "create", label: "Create a resource" },
  { view: "labs", label: "Guided labs" },
  { view: "deleted", label: "Deleted resources" },
];

export function SandboxPage({
  resourceId,
  params,
}: {
  resourceId?: number;
  params: URLSearchParams;
}) {
  const catalog = useLoad(() => api.sandboxCatalog(), []);
  const [revision, setRevision] = useState(0);
  const lab = params.get("lab");
  const view = resourceId ? "resource" : (params.get("view") ?? "");
  const q = params.get("q") ?? "";

  if (catalog.loading) return <Loading label="Opening the sandbox…" />;
  if (catalog.error || !catalog.data) {
    return <PageError error={catalog.error} onRetry={catalog.reload} />;
  }

  const context: Sandbox = {
    catalog: catalog.data,
    lab,
    revision,
    changed: () => setRevision((value) => value + 1),
  };

  let content: ReactNode;
  if (resourceId) content = <ResourceBlade key={resourceId} id={resourceId} />;
  else if (view === "create") {
    content = (
      <CreateView
        key={`${params.get("type")}-${params.get("parent")}`}
        typeKey={params.get("type")}
        parentId={Number(params.get("parent")) || undefined}
      />
    );
  } else if (view === "deleted") content = <DeletedView />;
  else if (view === "labs") content = <LabsView />;
  else content = <HomeView q={q} />;

  return (
    <SandboxContext.Provider value={context}>
      <div className="space-y-3">
        <p
          role="note"
          className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-950"
        >
          <span className="font-semibold">Simulated Azure sandbox. </span>
          {catalog.data.notice}
        </p>
        <div className="overflow-hidden rounded-lg border border-slate-300 bg-white">
          <div className="flex flex-wrap items-center gap-3 bg-slate-800 px-4 py-2 text-white">
            <span className="font-semibold">AI-103 Sandbox Portal</span>
            <SimulatedBadge />
            <form
              role="search"
              className="ml-auto flex min-w-40 flex-1 justify-end sm:max-w-sm"
              onSubmit={(event) => {
                event.preventDefault();
                const value = new FormData(event.currentTarget).get("q");
                go(sandboxHref(lab, { q: String(value ?? "").trim() }));
              }}
            >
              <input
                key={q}
                name="q"
                defaultValue={q}
                aria-label="Search resources"
                placeholder="Search resources"
                className="w-full min-w-0 rounded-md bg-slate-700 px-3 py-1 text-sm text-white placeholder:text-slate-300"
              />
            </form>
          </div>
          <div
            className={`grid ${lab ? "xl:grid-cols-[11rem_minmax(0,1fr)_26rem]" : "md:grid-cols-[11rem_minmax(0,1fr)]"}`}
          >
            <nav
              aria-label="Sandbox"
              className="border-b border-slate-200 bg-slate-50 p-2 md:border-r md:border-b-0"
            >
              <ul className="flex flex-wrap gap-1 text-sm md:flex-col">
                {NAV.map((item) => (
                  <li key={item.label}>
                    <a
                      href={sandboxHref(lab, { view: item.view })}
                      aria-current={view === item.view ? "page" : undefined}
                      className={`block rounded px-2 py-1.5 ${view === item.view ? "bg-blue-100 font-medium text-blue-900" : "text-slate-700 hover:bg-slate-200"}`}
                    >
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
            <section className="min-w-0 p-4">{content}</section>
            {lab && (
              <aside
                aria-label="Guided lab"
                className="border-t border-slate-200 bg-slate-50 xl:border-t-0 xl:border-l"
              >
                <LabPanel key={lab} labId={lab} />
              </aside>
            )}
          </div>
        </div>
      </div>
    </SandboxContext.Provider>
  );
}

// --- Lists ---

function ResourceTable({
  resources,
  empty,
}: {
  resources: ResourceSummary[];
  empty: ReactNode;
}) {
  const { catalog, lab } = useSandbox();
  if (!resources.length) return <>{empty}</>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-slate-500 uppercase">
          <tr>
            <th className="py-2 pr-3">Name</th>
            <th className="py-2 pr-3">Type</th>
            <th className="py-2 pr-3">Resource group</th>
            <th className="py-2 pr-3">Location</th>
            <th className="py-2">State</th>
          </tr>
        </thead>
        <tbody>
          {resources.map((resource) => (
            <tr key={resource.id} className="border-t border-slate-100">
              <td className="py-2 pr-3">
                <a
                  className="font-medium text-blue-800 underline"
                  href={sandboxHref(lab, { id: resource.id })}
                >
                  {resource.name}
                </a>
              </td>
              <td className="py-2 pr-3">{resource.type_label}</td>
              <td className="py-2 pr-3">{resource.resource_group ?? "–"}</td>
              <td className="py-2 pr-3">
                {regionLabel(catalog, resource.region)}
              </td>
              <td className="py-2">
                <StateBadge state={resource.state} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HomeView({ q }: { q: string }) {
  const { lab, revision } = useSandbox();
  const resources = useLoad(() => api.sandboxResources(q), [q, revision]);
  if (resources.loading && !resources.data) return <Loading />;
  if (resources.error || !resources.data) {
    return <ErrorNotice error={resources.error} onRetry={resources.reload} />;
  }
  const groups = resources.data.filter(
    (r) => r.resource_type === "resource_group",
  );
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-lg font-semibold">
          {q ? `Resources matching "${q}"` : "Your sandbox"}
        </h2>
        <a
          className={buttonClass()}
          href={sandboxHref(lab, { view: "create" })}
        >
          Create a resource
        </a>
        <a
          className={buttonClass("secondary")}
          href={sandboxHref(lab, { view: "labs" })}
        >
          Guided labs
        </a>
      </div>
      {!q && (
        <Card title="Resource groups">
          <ResourceTable
            resources={groups}
            empty={
              <p className="text-sm text-slate-500">No resource groups yet.</p>
            }
          />
        </Card>
      )}
      <Card title="All resources">
        <ResourceTable
          resources={resources.data}
          empty={
            <Empty title={q ? "Nothing matches" : "No resources yet"}>
              Create a resource, or start a guided lab to get starter resources.
            </Empty>
          }
        />
      </Card>
    </div>
  );
}

function DeletedView() {
  const { revision, changed } = useSandbox();
  const deleted = useLoad(() => api.sandboxDeleted(), [revision]);
  const [error, setError] = useState<unknown>(null);

  async function run(work: () => Promise<unknown>) {
    setError(null);
    try {
      await work();
      changed();
    } catch (failure) {
      setError(failure);
    }
  }

  if (deleted.loading && !deleted.data) return <Loading />;
  if (deleted.error || !deleted.data) {
    return <ErrorNotice error={deleted.error} onRetry={deleted.reload} />;
  }
  return (
    <Card title="Deleted resources">
      <p className="mb-3 text-sm text-slate-600">
        Deleted Foundry and Document Intelligence resources stay recoverable for
        48 hours, and their names stay reserved until then. Purging removes them
        for good and frees the name.
      </p>
      {error ? <ErrorNotice error={error} /> : null}
      {deleted.data.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing is waiting here.</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm">
          {deleted.data.map((resource) => (
            <li
              key={resource.id}
              className="flex flex-wrap items-center gap-2 py-2"
            >
              <span className="mr-auto">
                <span className="font-medium">{resource.name}</span>{" "}
                <span className="text-slate-500">
                  {resource.type_label}, from {resource.resource_group ?? "–"}
                </span>
              </span>
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() =>
                  void run(() => api.resourceAction(resource.id, "recover", {}))
                }
              >
                Recover {resource.name}
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() => void run(() => api.deleteResource(resource.id))}
              >
                Purge {resource.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const STATUS_LABELS = {
  not_started: "Not started",
  in_progress: "In progress",
  completed: "Completed",
};

function LabsView() {
  const { lab, revision } = useSandbox();
  const labs = useLoad(() => api.labs(), [revision]);
  if (labs.loading && !labs.data) return <Loading />;
  if (labs.error || !labs.data) {
    return <ErrorNotice error={labs.error} onRetry={labs.reload} />;
  }
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Guided labs</h2>
      <p className="text-sm text-slate-600">
        Each lab works in its own resource group, is graded automatically from
        your simulated resources, and maps to AI-103 objectives.
      </p>
      <ul className="grid gap-4 lg:grid-cols-2">
        {labs.data.map((item) => (
          <li
            key={item.id}
            className="flex flex-col rounded-lg border border-slate-200 p-4"
          >
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-medium">{item.title}</h3>
              <span className="shrink-0 rounded bg-slate-100 px-2 py-0.5 text-xs">
                {STATUS_LABELS[item.status]}
              </span>
            </div>
            <p className="mt-1 text-sm text-slate-600">{item.objective}</p>
            <p className="mt-2 text-xs text-slate-500">
              About {item.minutes} minutes
              {item.syllabus.length > 0 &&
                ` · Objectives ${item.syllabus.map((s) => s.code).join(", ")}`}
              {item.last_validation &&
                ` · Last check ${item.last_validation.passed_checks}/${item.last_validation.total_checks}`}
            </p>
            <a
              className={`${buttonClass(item.id === lab ? "secondary" : "primary")} mt-3 self-start`}
              href={sandboxHref(item.id, { view: "labs" })}
            >
              {item.id === lab ? "Open" : "Open lab"}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- Forms ---

function defaults(fields: SandboxField[]): Properties {
  return Object.fromEntries(
    fields.map((field) => [
      field.key,
      Array.isArray(field.default) ? [...field.default] : field.default,
    ]),
  );
}

function FieldInput({
  field,
  value,
  onChange,
  disabled,
  resources,
  idPrefix,
}: {
  field: SandboxField;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
  resources: ResourceSummary[];
  idPrefix: string;
}) {
  const id = `${idPrefix}-${field.key}`;
  const base =
    "mt-1 w-full rounded-md border border-slate-300 bg-white p-2 text-sm font-normal disabled:bg-slate-100";
  let input: ReactNode;
  if (field.kind === "bool") {
    return (
      <label className="flex items-start gap-2 text-sm" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          className="mt-1"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>
          {field.label}
          {field.help && (
            <span className="block text-xs text-slate-500">{field.help}</span>
          )}
        </span>
      </label>
    );
  }
  if (field.kind === "select") {
    input = (
      <select
        id={id}
        className={base}
        value={String(value ?? "")}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {field.options.map((option, index) => (
          <option key={String(option)} value={String(option)}>
            {field.labels[index] ?? String(option)}
          </option>
        ))}
      </select>
    );
  } else if (field.kind === "number") {
    input = (
      <input
        id={id}
        type="number"
        className={base}
        value={value === null || value === undefined ? "" : String(value)}
        min={field.minimum ?? undefined}
        max={field.maximum ?? undefined}
        step={field.integer ? 1 : 0.1}
        disabled={disabled}
        onChange={(event) =>
          onChange(
            event.target.value === "" ? null : Number(event.target.value),
          )
        }
      />
    );
  } else if (field.kind === "ref") {
    const candidates = resources.filter((r) =>
      field.refs.includes(r.resource_type),
    );
    input = (
      <select
        id={id}
        className={base}
        value={value === null || value === undefined ? "" : String(value)}
        disabled={disabled}
        onChange={(event) =>
          onChange(event.target.value ? Number(event.target.value) : null)
        }
      >
        <option value="">{field.required ? "Choose…" : "(none)"}</option>
        {candidates.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name} ({r.type_label}, {r.resource_group ?? "–"})
          </option>
        ))}
      </select>
    );
  } else if (field.kind === "strings") {
    input = (
      <textarea
        id={id}
        rows={3}
        className={base}
        value={((value as string[] | null) ?? []).join("\n")}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value.split("\n"))}
      />
    );
  } else if (field.kind === "list") {
    return (
      <fieldset className="text-sm">
        <legend className="font-medium">{field.label}</legend>
        <ListEditor
          field={field}
          rows={(value as Properties[] | null) ?? []}
          onChange={onChange}
          disabled={disabled}
          idPrefix={id}
        />
      </fieldset>
    );
  } else {
    const Tag = field.kind === "textarea" ? "textarea" : "input";
    input = (
      <Tag
        id={id}
        className={base}
        value={String(value ?? "")}
        maxLength={field.max_length}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        {...(field.kind === "textarea" ? { rows: 3 } : {})}
      />
    );
  }
  return (
    <div className="text-sm">
      <label className="font-medium" htmlFor={id}>
        {field.label}
        {!field.updatable && (
          <span className="ml-1 text-xs font-normal text-slate-500">
            (set at creation)
          </span>
        )}
      </label>
      {input}
      {field.help && (
        <p className="mt-1 text-xs text-slate-500">{field.help}</p>
      )}
    </div>
  );
}

function ListEditor({
  field,
  rows,
  onChange,
  disabled,
  idPrefix,
}: {
  field: SandboxField;
  rows: Properties[];
  onChange: (value: unknown) => void;
  disabled: boolean;
  idPrefix: string;
}) {
  function setCell(index: number, key: string, cell: unknown) {
    onChange(
      rows.map((row, i) => (i === index ? { ...row, [key]: cell } : row)),
    );
  }
  return (
    <div className="mt-1 space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-slate-500">
            <tr>
              {field.items.map((item) => (
                <th key={item.key} className="px-1 py-1 font-medium">
                  {item.label}
                </th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} className="border-t border-slate-100">
                {field.items.map((item) => {
                  const cellId = `${idPrefix}-${index}-${item.key}`;
                  const label = `${item.label}, row ${index + 1}`;
                  const cell = row[item.key];
                  return (
                    <td key={item.key} className="px-1 py-1">
                      {item.kind === "bool" ? (
                        <input
                          id={cellId}
                          aria-label={label}
                          type="checkbox"
                          checked={Boolean(cell)}
                          disabled={disabled}
                          onChange={(e) =>
                            setCell(index, item.key, e.target.checked)
                          }
                        />
                      ) : item.kind === "select" ? (
                        <select
                          id={cellId}
                          aria-label={label}
                          className="rounded border border-slate-300 p-1"
                          value={String(cell ?? "")}
                          disabled={disabled}
                          onChange={(e) =>
                            setCell(index, item.key, e.target.value)
                          }
                        >
                          {item.options.map((option) => (
                            <option key={String(option)}>
                              {String(option)}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          id={cellId}
                          aria-label={label}
                          className="w-24 rounded border border-slate-300 p-1"
                          type={item.kind === "number" ? "number" : "text"}
                          value={
                            cell === null || cell === undefined
                              ? ""
                              : String(cell)
                          }
                          disabled={disabled}
                          onChange={(e) =>
                            setCell(
                              index,
                              item.key,
                              item.kind === "number"
                                ? e.target.value === ""
                                  ? null
                                  : Number(e.target.value)
                                : e.target.value,
                            )
                          }
                        />
                      )}
                    </td>
                  );
                })}
                <td className="px-1">
                  <button
                    type="button"
                    className="text-red-700 underline disabled:opacity-50"
                    disabled={disabled}
                    onClick={() => onChange(rows.filter((_, i) => i !== index))}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button
        type="button"
        className={buttonClass("secondary")}
        disabled={disabled || rows.length >= field.max_items}
        onClick={() => onChange([...rows, defaults(field.items)])}
      >
        Add field
      </button>
    </div>
  );
}

function ResourceForm({
  type,
  initial,
  editing,
  submitLabel,
  children,
  onSubmit,
}: {
  type: ResourceType;
  initial?: Properties;
  editing: boolean;
  submitLabel: string;
  children?: ReactNode;
  onSubmit: (values: Properties) => Promise<void>;
}) {
  const { catalog, revision } = useSandbox();
  const resources = useLoad(() => api.sandboxResources(), [revision]);
  const [values, setValues] = useState<Properties>(
    () => initial ?? defaults(type.fields),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function set(key: string, value: unknown) {
    setValues((previous) => {
      const next = { ...previous, [key]: value };
      // A new model means its own versions: start from the first one.
      const model = catalog.models.find((m) => m.name === value);
      if (key === "model" && model) next.model_version = model.versions[0];
      return next;
    });
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const cleaned = Object.fromEntries(
        Object.entries(values).map(([key, value]) => [
          key,
          Array.isArray(value) && value.every((v) => typeof v === "string")
            ? value.map((v) => v.trim()).filter(Boolean)
            : value,
        ]),
      );
      await onSubmit(cleaned);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  const model =
    type.key === "model_deployment"
      ? catalog.models.find((m) => m.name === values.model)
      : undefined;
  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      {children}
      {type.fields.map((field) => (
        <FieldInput
          key={field.key}
          field={field}
          value={values[field.key]}
          onChange={(value) => set(field.key, value)}
          disabled={busy || (editing && !field.updatable)}
          resources={resources.data ?? []}
          idPrefix={editing ? "edit" : "new"}
        />
      ))}
      {model && (
        <p className="text-xs text-slate-500">
          {model.name} versions: {model.versions.join(", ")}.{" "}
          {model.max_dimensions &&
            `Embedding model, ${model.max_dimensions} dimensions by default.`}
        </p>
      )}
      {error ? <ErrorNotice error={error} /> : null}
      <button type="submit" className={buttonClass()} disabled={busy}>
        {busy ? "Saving…" : submitLabel}
      </button>
    </form>
  );
}

function CreateView({
  typeKey,
  parentId,
}: {
  typeKey: string | null;
  parentId?: number;
}) {
  const { catalog, lab, changed, revision } = useSandbox();
  const type = catalog.types.find((t) => t.key === typeKey);
  const resources = useLoad(() => api.sandboxResources(), [revision]);
  const [name, setName] = useState("");
  const [parent, setParent] = useState(parentId ? String(parentId) : "");

  if (!type) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Create a resource</h2>
        <ul className="grid gap-3 sm:grid-cols-2">
          {catalog.types.map((t) => (
            <li key={t.key} className="rounded-lg border border-slate-200 p-3">
              <a
                className="font-medium text-blue-800 underline"
                href={sandboxHref(lab, { view: "create", type: t.key })}
              >
                {t.label}
              </a>
              <p className="mt-1 text-xs text-slate-600">{t.description}</p>
              {t.parent && t.parent !== "resource_group" && (
                <p className="mt-1 text-xs text-slate-500">
                  Created inside a {typeOf(catalog, t.parent).label}.
                </p>
              )}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  const parents = (resources.data ?? []).filter(
    (r) => r.resource_type === type.parent,
  );
  return (
    <div className="max-w-2xl space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Create {type.label}</h2>
        <p className="text-sm text-slate-600">{type.description}</p>
        <p className="text-xs text-slate-500">{type.arm_type}</p>
      </div>
      <ResourceForm
        type={type}
        editing={false}
        submitLabel="Review and create"
        onSubmit={async (properties) => {
          const created = await api.createResource({
            resource_type: type.key,
            name,
            parent_id: parent ? Number(parent) : null,
            properties,
            client_request_id: newId(),
          });
          changed();
          go(sandboxHref(lab, { id: created.id }));
        }}
      >
        {type.parent && (
          <div className="text-sm">
            <label className="font-medium" htmlFor="new-parent">
              {typeOf(catalog, type.parent).label}
            </label>
            <select
              id="new-parent"
              className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2"
              value={parent}
              onChange={(event) => setParent(event.target.value)}
            >
              <option value="">Choose…</option>
              {parents.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                  {r.resource_type !== "resource_group" &&
                    ` (${r.resource_group ?? "–"})`}
                </option>
              ))}
            </select>
          </div>
        )}
        {!type.auto_name && (
          <div className="text-sm">
            <label className="font-medium" htmlFor="new-name">
              Name
            </label>
            <input
              id="new-name"
              className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2"
              value={name}
              maxLength={128}
              onChange={(event) => setName(event.target.value)}
            />
            <p className="mt-1 text-xs text-slate-500">{type.name_help}</p>
          </div>
        )}
      </ResourceForm>
    </div>
  );
}

// --- Resource blade ---

const ACTION_LABELS: Record<string, string> = {
  start: "Start",
  stop: "Stop",
  load_sample: "Load sample documents",
  test_connection: "Test connection",
  test_prompt: "Test prompt",
  test: "Run test",
};

function ResourceBlade({ id }: { id: number }) {
  const { catalog, lab, revision } = useSandbox();
  const { data, error, loading, reload, setData } = useLoad(
    () => api.sandboxResource(id),
    [id, revision],
  );
  const [tab, setTab] = useState("overview");

  if (loading && !data) return <Loading label="Loading resource…" />;
  if (error || !data) return <ErrorNotice error={error} onRetry={reload} />;

  const type = typeOf(catalog, data.resource_type);
  const soft = data.state === "soft_deleted";
  const tabs = [
    ["overview", "Overview"],
    ["settings", "Settings"],
    ...(data.actions.length
      ? [["operations", soft ? "Recover" : "Operations"]]
      : []),
    ...(soft ? [] : [["delete", "Delete"]]),
  ];

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs text-slate-500">
          <a className="underline" href={sandboxHref(lab)}>
            Home
          </a>
          {data.resource_group_id &&
            data.resource_type !== "resource_group" && (
              <>
                {" › "}
                <a
                  className="underline"
                  href={sandboxHref(lab, { id: data.resource_group_id })}
                >
                  {data.resource_group}
                </a>
              </>
            )}
          {data.parent_id && data.parent_id !== data.resource_group_id && (
            <>
              {" › "}
              <a
                className="underline"
                href={sandboxHref(lab, { id: data.parent_id })}
              >
                parent
              </a>
            </>
          )}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-semibold">{data.name}</h2>
          <StateBadge state={data.state} />
        </div>
        <p className="text-sm text-slate-600">{type.label}</p>
      </div>
      <div
        role="tablist"
        className="flex flex-wrap gap-1 border-b border-slate-200"
      >
        {tabs.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={tab === key}
            className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${tab === key ? "border-blue-700 font-medium text-blue-900" : "border-transparent text-slate-600"}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "overview" && <Overview resource={data} type={type} />}
      {tab === "settings" &&
        (type.updatable && !soft ? (
          <ResourceForm
            key={data.version}
            type={type}
            initial={data.properties}
            editing
            submitLabel="Save"
            onSubmit={async (properties) => {
              setData(await api.updateResource(id, properties, data.version));
            }}
          />
        ) : (
          <>
            <p className="text-sm text-slate-600">
              {soft
                ? "Recover this resource to change it."
                : `A ${type.label.toLowerCase()} can't be changed. Delete it and create a new one.`}
            </p>
            <Properties resource={data} type={type} />
          </>
        ))}
      {tab === "operations" && (
        <Operations
          resource={data}
          onDone={(outcome) => setData(outcome.resource)}
        />
      )}
      {tab === "delete" && <DeletePanel resource={data} type={type} />}
    </div>
  );
}

function Properties({
  resource,
  type,
}: {
  resource: ResourceDetail;
  type: ResourceType;
}) {
  return (
    <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[14rem_1fr]">
      {type.fields
        .filter((field) => field.kind !== "list")
        .map((field) => {
          const value = resource.properties[field.key];
          const shown =
            field.kind === "ref"
              ? (resource.references[field.key] ?? "(none)")
              : Array.isArray(value)
                ? value.join(", ") || "(none)"
                : typeof value === "boolean"
                  ? value
                    ? "Yes"
                    : "No"
                  : String(value ?? "") || "(none)";
          return (
            <div key={field.key} className="contents">
              <dt className="text-slate-500">{field.label}</dt>
              <dd className="break-words">{shown}</dd>
            </div>
          );
        })}
    </dl>
  );
}

function Overview({
  resource,
  type,
}: {
  resource: ResourceDetail;
  type: ResourceType;
}) {
  const { catalog, lab } = useSandbox();
  const childTypes = catalog.types.filter((t) => t.parent === type.key);
  const result = resource.outputs.result as AnalysisOutput | undefined;
  const lastTest = resource.outputs.last_test as
    Record<string, unknown> | undefined;
  const fields = resource.properties.fields as Properties[] | undefined;
  return (
    <div className="space-y-4">
      {resource.issues.length > 0 && (
        <ul className="space-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950">
          {resource.issues.map((issue) => (
            <li key={issue}>⚠ {issue}</li>
          ))}
        </ul>
      )}
      <Card title="Essentials">
        <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[12rem_1fr]">
          <dt className="text-slate-500">Resource group</dt>
          <dd>{resource.resource_group ?? "–"}</dd>
          <dt className="text-slate-500">Type</dt>
          <dd>{type.arm_type}</dd>
          <dt className="text-slate-500">Resource ID</dt>
          <dd className="font-mono text-xs break-all">{resource.arm_id}</dd>
          {resource.overview.map((item) => (
            <div key={item.label} className="contents">
              <dt className="text-slate-500">{item.label}</dt>
              <dd className="break-words">{item.value}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <Card title="Configuration">
        <Properties resource={resource} type={type} />
        {fields && (
          <table className="mt-3 w-full text-left text-xs">
            <thead className="text-slate-500">
              <tr>
                <th>Field</th>
                <th>Type</th>
                <th>Attributes</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => (
                <tr
                  key={String(field.name)}
                  className="border-t border-slate-100"
                >
                  <td className="py-1">{String(field.name)}</td>
                  <td>
                    {String(field.type)}
                    {field.dimensions
                      ? ` (${String(field.dimensions)} dims)`
                      : ""}
                  </td>
                  <td>
                    {[
                      "key",
                      "searchable",
                      "filterable",
                      "sortable",
                      "facetable",
                      "retrievable",
                    ]
                      .filter((a) => field[a])
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {result && <AnalysisResult result={result} />}
      {lastTest && (
        <Card title="Last test">
          <TestResult result={lastTest} />
        </Card>
      )}
      {childTypes.length > 0 && resource.state !== "soft_deleted" && (
        <Card title="Contains">
          <ResourceTable
            resources={resource.children}
            empty={<p className="text-sm text-slate-500">Nothing yet.</p>}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            {childTypes.map((child) => (
              <a
                key={child.key}
                className={buttonClass("secondary")}
                href={sandboxHref(lab, {
                  view: "create",
                  type: child.key,
                  parent: resource.id,
                })}
              >
                Add {child.label.toLowerCase()}
              </a>
            ))}
          </div>
        </Card>
      )}
      <p className="text-xs text-slate-500">
        {type.note && <>Simulation note: {type.note} </>}
        <a
          className="underline"
          href={type.docs_url}
          target="_blank"
          rel="noreferrer"
        >
          Microsoft Learn reference
        </a>
      </p>
    </div>
  );
}

interface AnalysisOutput {
  model_id: string;
  pages_analyzed: number;
  total_pages: number;
  content_format: string;
  content: string;
  tables: number;
  fields: Record<string, { value: string; confidence: number }>;
  notes: string[];
  notice: string;
}

function AnalysisResult({ result }: { result: AnalysisOutput }) {
  const fields = Object.entries(result.fields);
  return (
    <Card title="Analysis result">
      <p className="text-sm">
        {result.model_id}: {result.pages_analyzed} of {result.total_pages}{" "}
        pages, {result.tables} tables, {result.content_format} output.
      </p>
      <ul className="mt-2 list-disc pl-5 text-sm text-slate-700">
        {result.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
      {fields.length > 0 && (
        <table className="mt-3 text-left text-sm">
          <tbody>
            {fields.map(([name, field]) => (
              <tr key={name}>
                <th className="pr-4 font-medium">{name}</th>
                <td className="pr-4">{field.value}</td>
                <td className="text-xs text-slate-500">
                  confidence {field.confidence}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <pre className="mt-3 overflow-x-auto rounded bg-slate-100 p-2 text-xs whitespace-pre-wrap">
        {result.content}
      </pre>
      <p className="mt-2 text-xs text-slate-500">{result.notice}</p>
    </Card>
  );
}

export function TestResult({ result }: { result: Record<string, unknown> }) {
  const steps = (result.steps as string[] | undefined) ?? [];
  const reasons = (result.reasons as string[] | undefined) ?? [];
  const missed = (result.missed as string[] | undefined) ?? [];
  const citations = (result.citations as string[] | undefined) ?? [];
  const error = result.error as string | null | undefined;
  const verdict = error
    ? "Failed"
    : result.blocked
      ? "Blocked by the content filter"
      : result.grounded === false
        ? "Answered without grounding"
        : "Succeeded";
  return (
    <div className="space-y-2 text-sm" role="status">
      <p className={`font-medium ${error ? "text-red-800" : "text-slate-900"}`}>
        {verdict}
        {result.keyless === true && " · keyless"}
      </p>
      {typeof result.prompt === "string" && (
        <p className="text-slate-600">Prompt: {result.prompt}</p>
      )}
      {typeof result.question === "string" && (
        <p className="text-slate-600">Question: {result.question}</p>
      )}
      {steps.length > 0 && (
        <ol className="list-decimal pl-5 text-slate-700">
          {steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      )}
      {error && <p className="text-red-800">{error}</p>}
      {reasons.length > 0 && <p>Blocked because: {reasons.join("; ")}.</p>}
      {missed.length > 0 && (
        <p className="text-amber-900">Not checked: {missed.join("; ")}.</p>
      )}
      {typeof result.answer === "string" && <p>{result.answer}</p>}
      {citations.length > 0 && (
        <p className="text-xs text-slate-600">
          Sources: {citations.join(", ")}
        </p>
      )}
      {typeof result.notice === "string" && (
        <p className="text-xs text-slate-500">{result.notice}</p>
      )}
    </div>
  );
}

function Operations({
  resource,
  onDone,
}: {
  resource: ResourceDetail;
  onDone: (outcome: ActionOutcome) => void;
}) {
  const { catalog, lab, changed } = useSandbox();
  const [prompt, setPrompt] = useState(Object.keys(catalog.sample_prompts)[0]);
  const [question, setQuestion] = useState(
    Object.keys(catalog.sample_questions)[0],
  );
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run(action: string) {
    setBusy(true);
    setError(null);
    try {
      if (action === "purge") {
        await api.deleteResource(resource.id);
        changed();
        go(sandboxHref(lab, { view: "deleted" }));
        return;
      }
      const input: Record<string, string> =
        action === "test_prompt"
          ? { prompt_id: prompt }
          : action === "test"
            ? { question_id: question }
            : {};
      const outcome = await api.resourceAction(resource.id, action, input);
      setResult(outcome.result);
      onDone(outcome);
      changed();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {resource.actions.map((action) => (
        <div key={action} className="flex flex-wrap items-end gap-2">
          {action === "test_prompt" && (
            <label className="text-sm font-medium">
              Sample prompt
              <select
                className="mt-1 block rounded-md border border-slate-300 bg-white p-2 font-normal"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
              >
                {Object.entries(catalog.sample_prompts).map(([key, text]) => (
                  <option key={key} value={key}>
                    {text}
                  </option>
                ))}
              </select>
            </label>
          )}
          {action === "test" && (
            <label className="text-sm font-medium">
              Sample question
              <select
                className="mt-1 block rounded-md border border-slate-300 bg-white p-2 font-normal"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
              >
                {Object.entries(catalog.sample_questions).map(([key, text]) => (
                  <option key={key} value={key}>
                    {text}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            className={buttonClass(
              action === "purge" ? "secondary" : "primary",
            )}
            disabled={busy}
            onClick={() => void run(action)}
          >
            {action === "recover"
              ? "Recover"
              : action === "purge"
                ? "Purge permanently"
                : (ACTION_LABELS[action] ?? action)}
          </button>
        </div>
      ))}
      {error ? <ErrorNotice error={error} /> : null}
      {result && (
        <Card title="Result">
          <TestResult result={result} />
        </Card>
      )}
    </div>
  );
}

function DeletePanel({
  resource,
  type,
}: {
  resource: ResourceDetail;
  type: ResourceType;
}) {
  const { lab, changed } = useSandbox();
  const group = resource.resource_type === "resource_group";
  const [typed, setTyped] = useState("");
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteResource(resource.id, group ? typed : undefined);
      changed();
      go(
        sandboxHref(
          lab,
          !group && resource.resource_group_id
            ? { id: resource.resource_group_id }
            : {},
        ),
      );
    } catch (failure) {
      setError(failure);
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl space-y-3 text-sm">
      {group ? (
        <p>
          Deleting a resource group deletes every resource in it. Foundry and
          Document Intelligence resources inside it become recoverable deleted
          resources.
        </p>
      ) : type.soft_delete ? (
        <p>
          This resource will stay recoverable for 48 hours under Deleted
          resources, and its name stays reserved until you purge it.
        </p>
      ) : (
        <p>
          This deletes {resource.name}
          {resource.children.length > 0 &&
            ` and the ${resource.children.length} resources inside it`}
          . It can't be undone.
        </p>
      )}
      {group && (
        <label className="block font-medium">
          Type the resource group name to confirm
          <input
            className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 font-normal"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        </label>
      )}
      {error ? <ErrorNotice error={error} /> : null}
      {group || armed ? (
        <button
          type="button"
          className="rounded-md bg-red-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-800 disabled:opacity-50"
          disabled={busy || (group && typed !== resource.name)}
          onClick={() => void remove()}
        >
          {group ? "Delete resource group" : "Confirm delete"}
        </button>
      ) : (
        <button
          type="button"
          className={buttonClass("secondary")}
          onClick={() => setArmed(true)}
        >
          Delete {resource.name}
        </button>
      )}
    </div>
  );
}
