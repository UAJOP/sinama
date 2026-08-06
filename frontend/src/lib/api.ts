export type AgentMode = "healthy" | "broken_premature_submission";

export type ConversationPhase =
  | "awaiting_intent"
  | "awaiting_policy"
  | "awaiting_claim_details"
  | "awaiting_damage_photo"
  | "submitted"
  | "handed_off";

export interface ToolEvent {
  id: string;
  tool:
    | "lookup_policy"
    | "collect_claim_details"
    | "request_document"
    | "submit_claim"
    | "handoff_to_human";
  arguments: Record<string, string | number | boolean | null>;
  timestamp: string;
}

export interface ConversationState {
  policy_number: string | null;
  policy_lookup_occurred: boolean;
  damage_description: string | null;
  damage_photo_exists: boolean;
  claim_submitted: boolean;
  phase: ConversationPhase;
  mode: AgentMode;
}

export interface ConversationResponse {
  conversation_id: string;
  mode: AgentMode;
  assistant_message: string;
  state: ConversationState;
  new_events: ToolEvent[];
}

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new Error("Backend'e ulaşılamadı. FastAPI servisinin 8000 portunda çalıştığını kontrol edin.");
  }

  if (!response.ok) {
    let detail = `API isteği başarısız oldu (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Keep the safe status-based message when the server does not return JSON.
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export function createConversation(mode: AgentMode): Promise<ConversationResponse> {
  return request("/api/demo-agent/conversations", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

export function sendConversationMessage(
  conversationId: string,
  message: string,
): Promise<ConversationResponse> {
  return request(`/api/demo-agent/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function resetConversation(conversationId: string): Promise<ConversationResponse> {
  return request(`/api/demo-agent/conversations/${conversationId}/reset`, {
    method: "POST",
  });
}
