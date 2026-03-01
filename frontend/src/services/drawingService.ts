/**
 * HTTP client for the Drawing Command Service.
 *
 * Used by the Whiteboard's select/move tool so that user-initiated moves
 * are posted directly to the drawing service, which then broadcasts the
 * authoritative update back to all WebSocket subscribers.
 */

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

export async function postDraw(
  sessionId: string,
  operation: string,
  payload: Record<string, unknown>,
): Promise<void> {
  await fetch(`${getDrawingHttpUrl()}/draw`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      operation,
      payload,
    }),
  });
}
