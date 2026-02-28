import { FormEvent, useState } from "react";
import { sendChatMessage } from "../services/orchestratorChat";

interface ChatTurn {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  toolCalls?: string[];
}

interface ChatPanelProps {
  sessionId: string;
}

export function ChatPanel({ sessionId }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [turns, setTurns] = useState<ChatTurn[]>([]);

  async function onSubmit(e: FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    const userTurn: ChatTurn = {
      id: `u-${Date.now()}`,
      role: "user",
      text,
    };
    setTurns((prev) => [...prev, userTurn]);
    setInput("");
    setSending(true);

    try {
      const resp = await sendChatMessage(sessionId, text);
      setTurns((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          text: resp.assistant_text || "(No text response)",
          toolCalls: resp.tool_calls,
        },
      ]);
    } catch (err) {
      setTurns((prev) => [
        ...prev,
        {
          id: `s-${Date.now()}`,
          role: "system",
          text: `Request failed: ${String(err)}`,
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <aside className="chat-panel">
      <div className="chat-header">
        <strong>Agent Chat</strong>
        <span className="chat-session">session: {sessionId}</span>
      </div>

      <div className="chat-log">
        {turns.length === 0 ? (
          <div className="chat-empty">Ask Sona a question to test tools.</div>
        ) : (
          turns.map((turn) => (
            <div key={turn.id} className={`chat-turn chat-${turn.role}`}>
              <div className="chat-role">{turn.role}</div>
              <div className="chat-text">{turn.text}</div>
              {turn.toolCalls && turn.toolCalls.length > 0 && (
                <div className="chat-tools">
                  tools: {turn.toolCalls.join(", ")}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <form onSubmit={onSubmit} className="chat-form">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a math prompt..."
          disabled={sending}
          rows={3}
        />
        <button type="submit" disabled={sending || input.trim().length === 0}>
          {sending ? "Sending..." : "Send"}
        </button>
      </form>
    </aside>
  );
}
