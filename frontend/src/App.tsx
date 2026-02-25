import { useCallback, useEffect, useRef, useState } from "react";
import { Whiteboard } from "./components/Whiteboard";
import { MessageLog } from "./components/MessageLog";
import {
  connect,
  disconnect,
  type ConnectionStatus,
  type DSLMessageRaw,
} from "./services/drawingSocket";
import "./App.css";

const SESSION_ID = "dev-session";

export function App() {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [messages, setMessages] = useState<DSLMessageRaw[]>([]);
  const connectedRef = useRef(false);

  const handleMessage = useCallback((msg: DSLMessageRaw) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const handleStatus = useCallback((s: ConnectionStatus) => {
    setStatus(s);
  }, []);

  useEffect(() => {
    if (connectedRef.current) return;
    connectedRef.current = true;

    connect(SESSION_ID, handleMessage, handleStatus);
    return () => {
      connectedRef.current = false;
      disconnect();
    };
  }, [handleMessage, handleStatus]);

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">Sona</span>
        <span className={`status-dot status-${status}`} />
        <span className="status-label">{status}</span>
      </header>

      <main className="app-canvas">
        <Whiteboard messages={messages} />
      </main>

      <MessageLog messages={messages} />
    </div>
  );
}
