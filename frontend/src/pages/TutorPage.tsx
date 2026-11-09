import { useEffect, useRef, useState } from "react";
import { api, type Message, type ScopeLevel } from "../api";
import {
  buttonClass,
  Card,
  Empty,
  ErrorNotice,
  Loading,
  PageError,
  SyllabusReferences,
  useLoad,
} from "../ui";
import { TopicOptions } from "./LessonsPage";

const MAX_MESSAGE_LENGTH = 4000;
const QUICK_REPLIES = [
  "Can you explain that more simply?",
  "Can you give a practical Azure example of that?",
];

function newMessageId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function MessageBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="ml-auto max-w-[85%] rounded-lg bg-blue-700 px-4 py-2 text-sm whitespace-pre-wrap text-white">
        {message.content}
      </div>
    );
  }
  return (
    <div className="max-w-[95%] space-y-2">
      <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
        <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
          Tutor explanation · AI-generated
        </h3>
        <p className="mt-1 text-sm leading-6 whitespace-pre-wrap">
          {message.content}
        </p>
        {message.llm_model && (
          <p className="mt-2 text-xs text-slate-500">
            {message.llm_model} via {message.llm_provider}
          </p>
        )}
      </div>
      {message.references.length ? (
        <SyllabusReferences references={message.references} numbered />
      ) : (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          No syllabus reference matched this question, so this answer has no
          syllabus source.
        </p>
      )}
    </div>
  );
}

function Conversation({ id, onSent }: { id: number; onSent: () => void }) {
  const { data, error, loading, reload, setData } = useLoad(
    () => api.conversation(id),
    [id],
  );
  const [draft, setDraft] = useState("");
  // Kept per message so a retry can't store the same exchange twice.
  const pendingId = useRef<string | null>(null);
  const [sending, setSending] = useState<string | null>(null);
  const [sendError, setSendError] = useState<unknown>(null);
  const end = useRef<HTMLDivElement>(null);

  const messageCount = data?.messages.length;
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [messageCount, sending]);

  async function send(content: string) {
    const text = content.trim();
    if (!text || sending || !data) return;
    pendingId.current ??= newMessageId();
    setSending(text);
    setDraft("");
    setSendError(null);
    try {
      const exchange = await api.sendMessage(id, text, pendingId.current);
      pendingId.current = null;
      setData({
        ...data,
        messages: [
          ...data.messages,
          exchange.user_message,
          exchange.assistant_message,
        ],
      });
      onSent();
    } catch (failure) {
      // The draft stays, so nothing the learner typed is lost.
      setDraft(text);
      setSendError(failure);
    } finally {
      setSending(null);
    }
  }

  if (loading) return <Loading label="Loading conversation…" />;
  if (error || !data) return <PageError error={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-slate-500">
        Answers are grounded in syllabus version {data.version_number}.
      </p>
      {data.messages.length === 0 && !sending && (
        <Empty title="Ask your first question">
          For example: how do I choose a retrieval approach?
        </Empty>
      )}
      <div className="flex flex-col gap-4">
        {data.messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {sending && (
          <>
            <div className="ml-auto max-w-[85%] rounded-lg bg-blue-700 px-4 py-2 text-sm whitespace-pre-wrap text-white">
              {sending}
            </div>
            <Loading label="The tutor is thinking…" />
          </>
        )}
        <div ref={end} />
      </div>

      {sendError ? (
        <ErrorNotice
          error={sendError}
          onRetry={() => void send(draft)}
          retryLabel="Send again"
        />
      ) : null}

      {data.messages.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {QUICK_REPLIES.map((reply) => (
            <button
              key={reply}
              type="button"
              className={buttonClass("secondary")}
              disabled={Boolean(sending)}
              onClick={() => {
                pendingId.current = null;
                void send(reply);
              }}
            >
              {reply}
            </button>
          ))}
        </div>
      )}

      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
      >
        <label className="block text-sm font-medium" htmlFor="tutor-message">
          Your question
        </label>
        <textarea
          id="tutor-message"
          rows={3}
          value={draft}
          maxLength={MAX_MESSAGE_LENGTH}
          disabled={Boolean(sending)}
          onChange={(event) => {
            // New text is a new message, so it gets its own identity.
            pendingId.current = null;
            setDraft(event.target.value);
          }}
          className="w-full rounded-md border border-slate-300 bg-white p-2 text-sm"
        />
        <button
          type="submit"
          className={buttonClass()}
          disabled={!draft.trim() || Boolean(sending)}
        >
          {sending ? "Sending…" : "Send"}
        </button>
      </form>
    </div>
  );
}

export function TutorPage({ conversationId }: { conversationId?: number }) {
  const conversations = useLoad(() => api.conversations(), []);
  const syllabus = useLoad(() => api.syllabus(), []);
  const [scope, setScope] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);

  async function create() {
    setCreating(true);
    setCreateError(null);
    try {
      const [level, id] = scope.split(":");
      const conversation = await api.createConversation(
        scope
          ? { scope_level: level as ScopeLevel, scope_id: Number(id) }
          : undefined,
      );
      window.location.hash = `#/tutor/${conversation.id}`;
      setScope("");
      conversations.reload();
    } catch (failure) {
      setCreateError(failure);
    } finally {
      setCreating(false);
    }
  }

  if (syllabus.loading) return <Loading />;
  if (syllabus.error || !syllabus.data) {
    return <PageError error={syllabus.error} onRetry={syllabus.reload} />;
  }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[20rem_1fr]">
      <aside className="space-y-5">
        <Card title="New conversation">
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <label className="block text-sm font-medium">
              Topic (optional)
              <select
                value={scope}
                onChange={(event) => setScope(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 font-normal"
              >
                <option value="">Any part of the syllabus</option>
                <TopicOptions syllabus={syllabus.data} />
              </select>
            </label>
            <button type="submit" className={buttonClass()} disabled={creating}>
              {creating ? "Starting…" : "Start conversation"}
            </button>
            {createError ? <ErrorNotice error={createError} /> : null}
          </form>
        </Card>

        <Card title="Conversations">
          {conversations.loading && !conversations.data && <Loading />}
          {conversations.error ? (
            <ErrorNotice
              error={conversations.error}
              onRetry={conversations.reload}
            />
          ) : null}
          {conversations.data?.length === 0 && (
            <p className="text-sm text-slate-500">No conversations yet.</p>
          )}
          <ul className="space-y-2 text-sm">
            {conversations.data?.map((conversation) => (
              <li key={conversation.id}>
                <a
                  className="font-medium text-blue-800 underline"
                  href={`#/tutor/${conversation.id}`}
                  aria-current={
                    conversation.id === conversationId ? "page" : undefined
                  }
                >
                  {conversation.title ?? "New conversation"}
                </a>
              </li>
            ))}
          </ul>
        </Card>
      </aside>

      <div>
        {conversationId ? (
          <Conversation
            key={conversationId}
            id={conversationId}
            onSent={conversations.reload}
          />
        ) : (
          <Empty title="No conversation open">
            Start a conversation, or choose one from the list.
          </Empty>
        )}
      </div>
    </div>
  );
}
