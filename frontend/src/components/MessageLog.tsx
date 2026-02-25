import { useEffect, useRef, useState } from "react";
import type { DSLMessageRaw } from "../services/drawingSocket";

interface MessageLogProps {
  messages: DSLMessageRaw[];
}

const MAX_VISIBLE = 50;

export function MessageLog({ messages }: MessageLogProps) {
  const [visible, setVisible] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const recent = messages.slice(-MAX_VISIBLE);

  return (
    <div style={containerStyle}>
      <button
        onClick={() => setVisible((v) => !v)}
        style={toggleStyle}
      >
        {visible ? "Hide Log" : "Show Log"}
      </button>

      {visible && (
        <div ref={scrollRef} style={logStyle}>
          {recent.length === 0 ? (
            <div style={emptyStyle}>Waiting for messages...</div>
          ) : (
            recent.map((msg, i) => (
              <div key={`${msg.id}-${i}`} style={entryStyle}>
                <span style={typeStyle}>{msg.type}</span>
                <span style={idStyle}>#{msg.id}</span>
                <pre style={payloadStyle}>
                  {JSON.stringify(msg.payload, null, 2)}
                </pre>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

const containerStyle: React.CSSProperties = {
  position: "fixed",
  bottom: 16,
  right: 16,
  zIndex: 1000,
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-end",
  gap: 8,
};

const toggleStyle: React.CSSProperties = {
  padding: "6px 12px",
  fontSize: 12,
  fontWeight: 600,
  border: "1px solid #ccc",
  borderRadius: 6,
  background: "#fff",
  cursor: "pointer",
};

const logStyle: React.CSSProperties = {
  width: 360,
  maxHeight: 320,
  overflowY: "auto",
  background: "#1e1e1e",
  color: "#d4d4d4",
  borderRadius: 8,
  padding: 12,
  fontSize: 12,
  fontFamily: "monospace",
  boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
};

const emptyStyle: React.CSSProperties = {
  color: "#888",
  fontStyle: "italic",
};

const entryStyle: React.CSSProperties = {
  marginBottom: 8,
  borderBottom: "1px solid #333",
  paddingBottom: 6,
};

const typeStyle: React.CSSProperties = {
  color: "#569cd6",
  fontWeight: 700,
  marginRight: 8,
};

const idStyle: React.CSSProperties = {
  color: "#888",
  fontSize: 10,
};

const payloadStyle: React.CSSProperties = {
  margin: "4px 0 0",
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
  fontSize: 11,
  lineHeight: 1.4,
};
