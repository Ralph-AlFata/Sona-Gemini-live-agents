/**
 * HTTP client for the Drawing Command Service.
 *
 * Used by the Whiteboard's select/move tool so that user-initiated moves
 * are posted directly to the drawing service, which then broadcasts the
 * authoritative update back to all WebSocket subscribers.
 */

import type { DSLMessageRaw } from "./drawingSocket";

export interface SessionElementSnapshot {
  session_id: string;
  element_id: string;
  element_type: string;
  payload: Record<string, unknown>;
}

function getDrawingHttpUrl(): string {
  const fromEnv = import.meta.env.VITE_DRAWING_HTTP_BASE;
  if (typeof fromEnv === "string" && fromEnv.trim().length > 0) {
    return fromEnv.trim().replace(/\/+$/, "");
  }
  if (import.meta.env.DEV) {
    return "/api/drawing";
  }
  return `${window.location.protocol}//${window.location.hostname}:8002`;
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.trim().length > 0) {
      return body.detail;
    }
  } catch {
    // fall through
  }
  return `Drawing request failed (${response.status})`;
}

export async function postDraw(
  sessionId: string,
  operation: string,
  payload: Record<string, unknown>,
  authToken: string,
  options?: { elementId?: string },
): Promise<void> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${authToken}`,
  };
  const response = await fetch(`${getDrawingHttpUrl()}/draw`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      session_id: sessionId,
      operation,
      payload,
      ...(options?.elementId ? { element_id: options.elementId } : {}),
    }),
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response));
  }
}

export async function fetchSessionState(
  sessionId: string,
  authToken: string,
): Promise<DSLMessageRaw[]> {
  const response = await fetch(
    `${getDrawingHttpUrl()}/sessions/${encodeURIComponent(sessionId)}/state`,
    {
      method: "GET",
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
    },
  );
  if (!response.ok) {
    throw new Error(await readErrorDetail(response));
  }
  const body = (await response.json()) as { dsl_messages?: unknown };
  if (!Array.isArray(body.dsl_messages)) {
    return [];
  }
  return body.dsl_messages as DSLMessageRaw[];
}

export async function fetchSessionElements(
  sessionId: string,
  authToken: string,
): Promise<SessionElementSnapshot[]> {
  const response = await fetch(
    `${getDrawingHttpUrl()}/sessions/${encodeURIComponent(sessionId)}/elements`,
    {
      method: "GET",
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
    },
  );
  if (!response.ok) {
    throw new Error(await readErrorDetail(response));
  }
  const body = await response.json();
  if (!Array.isArray(body)) return [];
  return body as SessionElementSnapshot[];
}
