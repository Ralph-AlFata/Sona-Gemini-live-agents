export interface ChatResponse {
  session_id: string;
  user_text: string;
  assistant_text: string;
  tool_calls: string[];
}

function getBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_ORCHESTRATOR_HTTP_BASE;
  if (typeof fromEnv === "string" && fromEnv.trim().length > 0) {
    return fromEnv.trim().replace(/\/+$/, "");
  }
  if (import.meta.env.DEV) {
    return "/api/orchestrator";
  }
  return `${window.location.protocol}//${window.location.hostname}:8001`;
}

export async function sendChatMessage(
  sessionId: string,
  text: string,
): Promise<ChatResponse> {
  const base = getBaseUrl();
  const response = await fetch(
    `${base}/chat/${encodeURIComponent(sessionId)}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ text }),
    },
  );

  const data = (await response.json()) as ChatResponse | { detail?: string };
  if (!response.ok) {
    const detail = typeof data === "object" && data && "detail" in data
      ? String(data.detail ?? "Unknown error")
      : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return data as ChatResponse;
}
