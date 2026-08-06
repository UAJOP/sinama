"use client";

import type { FormEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  createConversation,
  resetConversation,
  sendConversationMessage,
  type AgentMode,
  type ConversationState,
  type ToolEvent,
} from "@/lib/api";


interface ChatMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
}

const MODE_LABELS: Record<AgentMode, string> = {
  healthy: "Healthy",
  broken_premature_submission: "Broken: Premature Claim Submission",
};

const PHASE_LABELS: Record<NonNullable<ConversationState>["phase"], string> = {
  awaiting_intent: "Talep bekleniyor",
  awaiting_policy: "Poliçe bekleniyor",
  awaiting_claim_details: "Hasar ayrıntısı bekleniyor",
  awaiting_damage_photo: "Fotoğraf bekleniyor",
  submitted: "Hasar gönderildi",
  handed_off: "İnsan desteğine aktarıldı",
};

function message(role: ChatMessage["role"], content: string): ChatMessage {
  return { id: crypto.randomUUID(), role, content };
}

function isPrematureSubmission(event: ToolEvent): boolean {
  return event.tool === "submit_claim" && event.arguments.status === "premature";
}

export default function Home() {
  const [mode, setMode] = useState<AgentMode>("healthy");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<ToolEvent[]>([]);
  const [conversationState, setConversationState] = useState<ConversationState | null>(null);
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestSerial = useRef(0);
  const transcriptEnd = useRef<HTMLDivElement>(null);

  const startConversation = useCallback(async (selectedMode: AgentMode) => {
    const serial = ++requestSerial.current;
    setIsLoading(true);
    setError(null);
    setConversationId(null);
    setMessages([]);
    setEvents([]);
    setConversationState(null);

    try {
      const response = await createConversation(selectedMode);
      if (serial !== requestSerial.current) return;
      setConversationId(response.conversation_id);
      setConversationState(response.state);
      setMessages([message("assistant", response.assistant_message)]);
    } catch (cause) {
      if (serial !== requestSerial.current) return;
      setError(cause instanceof Error ? cause.message : "Beklenmeyen bir bağlantı hatası oluştu.");
    } finally {
      if (serial === requestSerial.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    const startTimer = window.setTimeout(() => {
      void startConversation(mode);
    }, 0);

    return () => window.clearTimeout(startTimer);
  }, [mode, startConversation]);

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || !conversationId || isLoading) return;

    setDraft("");
    setError(null);
    setIsLoading(true);
    setMessages((current) => [...current, message("user", content)]);

    try {
      const response = await sendConversationMessage(conversationId, content);
      setConversationState(response.state);
      setEvents((current) => [...current, ...response.new_events]);
      setMessages((current) => [...current, message("assistant", response.assistant_message)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Mesaj gönderilemedi.");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleReset() {
    if (!conversationId || isLoading) return;
    const serial = ++requestSerial.current;
    setIsLoading(true);
    setError(null);

    try {
      const response = await resetConversation(conversationId);
      if (serial !== requestSerial.current) return;
      setConversationState(response.state);
      setEvents([]);
      setMessages([message("assistant", response.assistant_message)]);
      setDraft("");
    } catch (cause) {
      if (serial !== requestSerial.current) return;
      setError(cause instanceof Error ? cause.message : "Konuşma sıfırlanamadı.");
    } finally {
      if (serial === requestSerial.current) setIsLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">S</div>
          <div>
            <p className="eyebrow">AI AGENT RELIABILITY LAB</p>
            <h1>SINAMA</h1>
          </div>
        </div>
        <div className="built-in-badge">
          <span className="status-dot" aria-hidden="true" />
          <span><strong>Built-in Demo Agent</strong><small>Harici endpoint veya API key gerekmez</small></span>
        </div>
      </header>

      <section className="control-bar" aria-labelledby="mode-heading">
        <div>
          <p className="eyebrow" id="mode-heading">AGENT MODE</p>
          <p className="control-note">Mode değişikliği temiz bir konuşma başlatır.</p>
        </div>
        <div className="mode-switch" role="group" aria-label="Demo agent mode">
          {(Object.keys(MODE_LABELS) as AgentMode[]).map((option) => (
            <button
              className={`mode-option ${option === mode ? "active" : ""} ${option.startsWith("broken") ? "broken" : "healthy"}`}
              key={option}
              type="button"
              aria-pressed={option === mode}
              disabled={isLoading && option === mode}
              onClick={() => setMode(option)}
            >
              <span aria-hidden="true">{option === "healthy" ? "✓" : "⚠"}</span>
              {MODE_LABELS[option]}
            </button>
          ))}
        </div>
      </section>

      {error && (
        <div className="error-banner" role="alert">
          <div>
            <strong>Bağlantı sorunu</strong>
            <span>{error}</span>
          </div>
          {!conversationId && (
            <button type="button" onClick={() => void startConversation(mode)}>Tekrar dene</button>
          )}
        </div>
      )}

      <div className="workspace-grid">
        <section className="panel chat-panel" aria-labelledby="chat-title">
          <div className="panel-header">
            <div>
              <p className="eyebrow">MANUAL TEST SURFACE</p>
              <h2 id="chat-title">Demo Agent Chat</h2>
            </div>
            <button
              className="secondary-button"
              type="button"
              onClick={() => void handleReset()}
              disabled={!conversationId || isLoading}
            >
              ↻ Konuşmayı sıfırla
            </button>
          </div>

          <div className="transcript" aria-live="polite" aria-busy={isLoading}>
            {messages.length === 0 && isLoading ? (
              <div className="empty-state loading-state">
                <span className="spinner" aria-hidden="true" />
                Demo agent oturumu hazırlanıyor…
              </div>
            ) : (
              messages.map((item) => (
                <article className={`message ${item.role}`} key={item.id}>
                  <div className="message-meta">
                    <span>{item.role === "assistant" ? "DEMO AGENT" : "YOU"}</span>
                    <span>{item.role === "assistant" ? "S" : "K"}</span>
                  </div>
                  <p>{item.content}</p>
                </article>
              ))
            )}
            {isLoading && messages.length > 0 && (
              <div className="typing-indicator" aria-label="Demo agent yanıt hazırlıyor">
                <i /><i /><i />
              </div>
            )}
            <div ref={transcriptEnd} />
          </div>

          <form className="composer" onSubmit={handleSend}>
            <label htmlFor="customer-message">Müşteri mesajı</label>
            <div className="composer-row">
              <textarea
                id="customer-message"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="Örn. Arabamla kaza yaptım, hasar kaydı açmak istiyorum."
                rows={2}
                maxLength={2000}
                disabled={!conversationId || isLoading}
              />
              <button className="send-button" type="submit" disabled={!draft.trim() || !conversationId || isLoading}>
                Gönder <span aria-hidden="true">↗</span>
              </button>
            </div>
            <span className="composer-hint">Enter ile gönder · Shift+Enter ile yeni satır</span>
          </form>
        </section>

        <aside className="panel trace-panel" aria-labelledby="trace-title">
          <div className="panel-header trace-header">
            <div>
              <p className="eyebrow">STRUCTURED EVIDENCE</p>
              <h2 id="trace-title">Live Trace</h2>
            </div>
            <span className={`mode-pill ${mode.startsWith("broken") ? "broken" : "healthy"}`}>
              {mode === "healthy" ? "✓ HEALTHY" : "⚠ BROKEN"}
            </span>
          </div>

          <div className="state-strip" aria-label="Conversation state">
            <span>PHASE</span>
            <strong>{conversationState ? PHASE_LABELS[conversationState.phase] : "Bağlanıyor"}</strong>
          </div>

          <div className="trace-list" aria-live="polite">
            {events.length === 0 ? (
              <div className="empty-state">
                <div className="trace-placeholder" aria-hidden="true">{"{ }"}</div>
                <strong>Henüz agent event’i yok</strong>
                <span>Sohbet ilerledikçe backend tool çağrıları burada görünecek.</span>
              </div>
            ) : (
              events.map((event, index) => {
                const warning = isPrematureSubmission(event);
                return (
                  <article className={`trace-event ${warning ? "warning" : ""}`} key={event.id}>
                    <div className="event-rail" aria-hidden="true">
                      <span>{warning ? "!" : "✓"}</span>
                      {index < events.length - 1 && <i />}
                    </div>
                    <div className="event-content">
                      <div className="event-heading">
                        <code>{event.tool}</code>
                        <time dateTime={event.timestamp}>
                          {new Intl.DateTimeFormat("tr-TR", {
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          }).format(new Date(event.timestamp))}
                        </time>
                      </div>
                      <dl>
                        {Object.entries(event.arguments).map(([key, value]) => (
                          <div key={key}>
                            <dt>{key}</dt>
                            <dd>{String(value)}</dd>
                          </div>
                        ))}
                      </dl>
                      {warning && <p className="violation-label">POLICY VIOLATION · INTENTIONAL REGRESSION</p>}
                    </div>
                  </article>
                );
              })
            )}
          </div>

          <footer className="trace-footer">
            <span>{events.length} EVENT</span>
            <span>CONVERSATION · {conversationId ? conversationId.slice(0, 8) : "—"}</span>
          </footer>
        </aside>
      </div>
    </main>
  );
}
