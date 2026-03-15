export type LiveConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting";

export interface LiveRunOptions {
  proactivity: boolean;
  affectiveDialog: boolean;
}

export interface LiveEventPayload {
  author?: string;
  interrupted?: boolean;
  inputTranscription?: {
    text?: string;
    finished?: boolean;
  };
  outputTranscription?: {
    text?: string;
    finished?: boolean;
  };
  content?: {
    parts?: Array<{
      text?: string;
      thought?: boolean;
      inlineData?: {
        mimeType?: string;
        data?: string;
      };
    }>;
  };
  error?: string;
  [key: string]: unknown;
}

type OnEvent = (event: LiveEventPayload) => void;
type OnStatus = (status: LiveConnectionStatus) => void;

const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 30000;

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let intentionalClose = false;

let currentUserId: string | null = null;
let currentSessionId: string | null = null;
let currentAuthToken: string | null = null;
let currentOptions: LiveRunOptions = {
  proactivity: false,
  affectiveDialog: false,
};
let onEventCallback: OnEvent | null = null;
let onStatusCallback: OnStatus | null = null;
let lastCanvasMetrics: { canvas_width_px: number; canvas_height_px: number } | null = null;

function setStatus(status: LiveConnectionStatus): void {
  onStatusCallback?.(status);
}

function getWsBasePath(): string {
  const fromEnv = import.meta.env.VITE_ORCHESTRATOR_WS_BASE;
  if (typeof fromEnv === "string" && fromEnv.trim().length > 0) {
    return fromEnv.trim().replace(/\/+$/, "");
  }
  if (import.meta.env.DEV) {
    return `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/orchestrator`;
  }
  return `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.hostname}:8001`;
}

function getWsUrl(
  userId: string,
  sessionId: string,
  options: LiveRunOptions,
  authToken: string | null,
): string {
  const params = new URLSearchParams();
  if (options.proactivity) params.set("proactivity", "true");
  if (options.affectiveDialog) params.set("affective_dialog", "true");
  if (authToken) params.set("auth_token", authToken);

  const basePath = getWsBasePath();
  const wsPath = `${basePath}/ws/${encodeURIComponent(userId)}/${encodeURIComponent(sessionId)}`;
  const query = params.toString();
  return query ? `${wsPath}?${query}` : wsPath;
}

function scheduleReconnect(): void {
  if (intentionalClose || !currentUserId || !currentSessionId) return;

  const delay = Math.min(BASE_DELAY_MS * Math.pow(2, reconnectAttempt), MAX_DELAY_MS);
  reconnectAttempt++;
  setStatus("reconnecting");

  reconnectTimer = setTimeout(() => {
    if (currentUserId && currentSessionId) {
      openSocket(currentUserId, currentSessionId, currentOptions, currentAuthToken);
    }
  }, delay);
}

function openSocket(
  userId: string,
  sessionId: string,
  options: LiveRunOptions,
  authToken: string | null,
): void {
  setStatus("connecting");
  const ws = new WebSocket(getWsUrl(userId, sessionId, options, authToken));
  socket = ws;

  ws.onopen = () => {
    if (socket !== ws) return;
    reconnectAttempt = 0;
    setStatus("connected");
    if (lastCanvasMetrics) {
      ws.send(JSON.stringify({ type: "canvas_metrics", ...lastCanvasMetrics }));
    }
  };

  ws.onmessage = (event: MessageEvent) => {
    if (socket !== ws) return;
    try {
      const parsed = JSON.parse(String(event.data)) as LiveEventPayload;
      onEventCallback?.(parsed);
    } catch {
      // Non-JSON message from server; ignore.
    }
  };

  ws.onclose = () => {
    if (socket !== ws) return;
    socket = null;
    if (intentionalClose) {
      setStatus("disconnected");
      return;
    }
    scheduleReconnect();
  };

  ws.onerror = () => {
    if (socket !== ws) return;
    // onclose handles reconnect behavior.
  };
}

export function connectLive(
  userId: string,
  sessionId: string,
  authToken: string,
  options: LiveRunOptions,
  onEvent: OnEvent,
  onStatus: OnStatus,
): void {
  disconnectLive();

  intentionalClose = false;
  reconnectAttempt = 0;
  currentUserId = userId;
  currentSessionId = sessionId;
  currentAuthToken = authToken;
  currentOptions = options;
  onEventCallback = onEvent;
  onStatusCallback = onStatus;

  openSocket(userId, sessionId, options, authToken);
}

export function disconnectLive(): void {
  intentionalClose = true;
  currentUserId = null;
  currentSessionId = null;
  currentAuthToken = null;
  onEventCallback = null;
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

export function sendAudioChunk(chunk: ArrayBuffer): boolean {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(chunk);
  return true;
}

export function sendActivityStart(): boolean {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify({ type: "activity_start" }));
  return true;
}

export function sendActivityEnd(): boolean {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify({ type: "activity_end" }));
  return true;
}

export function sendImageFrame(base64Data: string, mimeType: string): boolean {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(
    JSON.stringify({
      type: "image",
      data: base64Data,
      mimeType,
    }),
  );
  return true;
}

export function sendCanvasMetrics(canvasWidthPx: number, canvasHeightPx: number): boolean {
  if (!Number.isFinite(canvasWidthPx) || !Number.isFinite(canvasHeightPx)) return false;
  if (canvasWidthPx <= 0 || canvasHeightPx <= 0) return false;

  lastCanvasMetrics = {
    canvas_width_px: Math.round(canvasWidthPx),
    canvas_height_px: Math.round(canvasHeightPx),
  };

  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify({ type: "canvas_metrics", ...lastCanvasMetrics }));
  return true;
}

export function sendCanvasSnapshot(base64Data: string): boolean {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(
    JSON.stringify({
      type: "snapshot",
      data: base64Data,
    }),
  );
  return true;
}
