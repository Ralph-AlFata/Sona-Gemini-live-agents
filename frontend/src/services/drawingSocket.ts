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
let onMessageCallback: OnMessage | null = null;
let onStatusCallback: OnStatus | null = null;
let intentionalClose = false;

function getWsUrl(sessionId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  return `${protocol}//${host}/ws/drawing/${sessionId}`;
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
      openSocket(currentSessionId);
    }
  }, delay);
}

function openSocket(sessionId: string): void {
  setStatus("connecting");

  const ws = new WebSocket(getWsUrl(sessionId));

  ws.onopen = () => {
    reconnectAttempt = 0;
    setStatus("connected");
  };

  ws.onmessage = (event: MessageEvent) => {
    try {
      const data: DSLMessageRaw = JSON.parse(event.data as string);
      onMessageCallback?.(data);
    } catch {
      // Non-JSON message — ignore for now
    }
  };

  ws.onclose = () => {
    socket = null;
    if (!intentionalClose) {
      scheduleReconnect();
    } else {
      setStatus("disconnected");
    }
  };

  ws.onerror = () => {
    // onclose will fire after onerror — reconnect handled there
  };

  socket = ws;
}

export function connect(
  sessionId: string,
  onMessage: OnMessage,
  onStatus: OnStatus,
): void {
  disconnect();

  intentionalClose = false;
  reconnectAttempt = 0;
  currentSessionId = sessionId;
  onMessageCallback = onMessage;
  onStatusCallback = onStatus;

  openSocket(sessionId);
}

export function disconnect(): void {
  intentionalClose = true;
  currentSessionId = null;
  onMessageCallback = null;
  onStatusCallback = null;

  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  if (socket) {
    socket.close();
    socket = null;
  }

  setStatus("disconnected");
}
