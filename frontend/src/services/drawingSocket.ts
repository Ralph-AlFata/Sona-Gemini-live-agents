/**
 * Single WebSocket service layer for the drawing command stream.
 *
 * Per CLAUDE.md: "WebSocket connection managed in a single service layer,
 * not scattered across components."
 */

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "reconnecting";

export interface DSLMessageRaw {
  version: string;
  id: string;
  session_id: string;
  type: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

type OnMessage = (message: DSLMessageRaw) => void;
type OnStatus = (status: ConnectionStatus) => void;

const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 30000;

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let currentSessionId: string | null = null;
let currentAuthToken: string | null = null;
let onMessageCallback: OnMessage | null = null;
let onStatusCallback: OnStatus | null = null;
let intentionalClose = false;

function getWsUrl(sessionId: string, authToken: string | null): string {
  // In production, VITE_DRAWING_WS_BASE points directly to the drawing service
  // (e.g. "wss://sona-drawing-xxx-uc.a.run.app"). In dev it falls back to the
  // Vite proxy on the same host ("/ws/drawing/<id>").
  const drawingWsBase = import.meta.env.VITE_DRAWING_WS_BASE as string | undefined;
  let base: string;
  if (drawingWsBase) {
    // Strip trailing slash, then append the WS path
    base = `${drawingWsBase.replace(/\/$/, "")}/ws/${sessionId}`;
  } else {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    base = `${protocol}//${host}/ws/drawing/${sessionId}`;
  }
  if (!authToken) return base;
  return `${base}?auth_token=${encodeURIComponent(authToken)}`;
}

function setStatus(status: ConnectionStatus): void {
  onStatusCallback?.(status);
}

function scheduleReconnect(): void {
  if (intentionalClose || !currentSessionId) return;

  const delay = Math.min(BASE_DELAY_MS * Math.pow(2, reconnectAttempt), MAX_DELAY_MS);
  reconnectAttempt++;
  setStatus("reconnecting");

  reconnectTimer = setTimeout(() => {
    if (currentSessionId) {
      openSocket(currentSessionId, currentAuthToken);
    }
  }, delay);
}

function openSocket(sessionId: string, authToken: string | null): void {
  setStatus("connecting");

  const ws = new WebSocket(getWsUrl(sessionId, authToken));
  socket = ws;

  ws.onopen = () => {
    if (socket !== ws) return;
    reconnectAttempt = 0;
    setStatus("connected");
  };

  ws.onmessage = (event: MessageEvent) => {
    if (socket !== ws) return;
    try {
      const data: DSLMessageRaw = JSON.parse(event.data as string);
      onMessageCallback?.(data);
    } catch {
      // Non-JSON message — ignore for now
    }
  };

  ws.onclose = () => {
    if (socket !== ws) return;
    socket = null;
    if (!intentionalClose) {
      scheduleReconnect();
    } else {
      setStatus("disconnected");
    }
  };

  ws.onerror = () => {
    if (socket !== ws) return;
    // onclose will fire after onerror — reconnect handled there
  };
}

export function connect(
  sessionId: string,
  authToken: string,
  onMessage: OnMessage,
  onStatus: OnStatus,
): void {
  disconnect();

  intentionalClose = false;
  reconnectAttempt = 0;
  currentSessionId = sessionId;
  currentAuthToken = authToken;
  onMessageCallback = onMessage;
  onStatusCallback = onStatus;

  openSocket(sessionId, authToken);
}

export function disconnect(): void {
  intentionalClose = true;
  currentSessionId = null;
  currentAuthToken = null;
  onMessageCallback = null;
  onStatusCallback = null;

  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  const socketToClose = socket;
  socket = null;
  if (socketToClose) {
    socketToClose.close();
  }

  setStatus("disconnected");
}
