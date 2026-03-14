export interface SessionRecord {
  session_id: string;
  student_id: string;
  topic: string | null;
  status: "active" | "ended";
  created_at: string;
  updated_at: string;
  turn_count: number;
  last_turn_at: string | null;
}

function getSessionHttpBase(): string {
  const fromEnv = import.meta.env.VITE_SESSION_HTTP_BASE;
  if (typeof fromEnv === "string" && fromEnv.trim().length > 0) {
    return fromEnv.trim().replace(/\/+$/, "");
  }
  if (import.meta.env.DEV) {
    return "/api/session";
  }
  return `${window.location.protocol}//${window.location.hostname}:8003`;
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.trim().length > 0) {
      return body.detail;
    }
  } catch {
    // fall through to generic message
  }
  return `Session API request failed (${response.status})`;
}

async function sessionRequest<T>(
  path: string,
  authToken: string,
  init?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${authToken}`,
    ...(init?.body ? { "Content-Type": "application/json" } : {}),
    ...(init?.headers instanceof Headers
      ? Object.fromEntries(init.headers.entries())
      : (init?.headers as Record<string, string> | undefined)),
  };
  const response = await fetch(`${getSessionHttpBase()}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function listSessions(
  authToken: string,
  studentId: string,
): Promise<SessionRecord[]> {
  const query = new URLSearchParams({ student_id: studentId }).toString();
  return await sessionRequest<SessionRecord[]>(`/sessions?${query}`, authToken, {
    method: "GET",
  });
}

export async function createSession(
  authToken: string,
  studentId: string,
  name: string | null,
): Promise<SessionRecord> {
  const cleaned = typeof name === "string" ? name.trim() : "";
  return await sessionRequest<SessionRecord>("/sessions", authToken, {
    method: "POST",
    body: JSON.stringify({
      student_id: studentId,
      topic: cleaned.length > 0 ? cleaned : null,
    }),
  });
}

export async function renameSession(
  authToken: string,
  sessionId: string,
  name: string,
): Promise<SessionRecord> {
  const cleaned = name.trim();
  return await sessionRequest<SessionRecord>(`/sessions/${encodeURIComponent(sessionId)}`, authToken, {
    method: "PATCH",
    body: JSON.stringify({ topic: cleaned }),
  });
}

export async function deleteSession(authToken: string, sessionId: string): Promise<void> {
  await sessionRequest<void>(`/sessions/${encodeURIComponent(sessionId)}`, authToken, {
    method: "DELETE",
  });
}
