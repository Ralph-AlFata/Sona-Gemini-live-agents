import { ChangeEvent, FormEvent, useRef, useState } from "react";
import { ChatImageInput, sendChatMessage } from "../services/orchestratorChat";

interface ChatTurn {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  toolCalls?: string[];
}

interface ChatPanelProps {
  sessionId: string;
}

async function readFileAsDataUrl(file: File): Promise<string> {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.onload = () => {
      if (typeof reader.result !== "string") {
        reject(new Error("Unexpected file reader result"));
        return;
      }
      resolve(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

function parseDataUrl(dataUrl: string): { mimeType: string; dataBase64: string } | null {
  const match = /^data:([^;]+);base64,(.+)$/i.exec(dataUrl);
  if (!match) {
    return null;
  }
  const mimeType = match[1];
  const dataBase64 = match[2];
  if (!mimeType || !dataBase64) {
    return null;
  }
  return { mimeType, dataBase64 };
}

export function ChatPanel({ sessionId }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [imageAttachment, setImageAttachment] = useState<ChatImageInput | null>(null);
  const [imageName, setImageName] = useState<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);

  function clearAttachment(): void {
    setImageAttachment(null);
    setImageName(null);
    if (imageInputRef.current) {
      imageInputRef.current.value = "";
    }
  }

  async function onImageChange(e: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = e.target.files?.[0];
    if (!file) {
      clearAttachment();
      return;
    }
    if (!file.type.startsWith("image/")) {
      setTurns((prev) => [
        ...prev,
        {
          id: `s-${Date.now()}`,
          role: "system",
          text: "Only image files are supported.",
        },
      ]);
      clearAttachment();
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setTurns((prev) => [
        ...prev,
        {
          id: `s-${Date.now()}`,
          role: "system",
          text: "Image exceeds 10 MB limit.",
        },
      ]);
      clearAttachment();
      return;
    }

    try {
      const dataUrl = await readFileAsDataUrl(file);
      const parsed = parseDataUrl(dataUrl);
      if (!parsed) {
        throw new Error("Invalid data URL");
      }
      setImageAttachment({
        mime_type: parsed.mimeType,
        data_base64: parsed.dataBase64,
        filename: file.name,
      });
      setImageName(file.name);
    } catch {
      setTurns((prev) => [
        ...prev,
        {
          id: `s-${Date.now()}`,
          role: "system",
          text: "Failed to load image attachment.",
        },
      ]);
      clearAttachment();
    }
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    const text = input.trim();
    if ((!text && !imageAttachment) || sending) return;
    const outgoingImage = imageAttachment;
    const outgoingImageName = imageName;

    const userTurn: ChatTurn = {
      id: `u-${Date.now()}`,
      role: "user",
      text: text
        ? (outgoingImageName ? `${text}\n[Image: ${outgoingImageName}]` : text)
        : `[Image: ${outgoingImageName ?? "attachment"}]`,
    };
    setTurns((prev) => [...prev, userTurn]);
    setInput("");
    clearAttachment();
    setSending(true);

    try {
      const resp = await sendChatMessage(
        sessionId,
        text,
        outgoingImage ? [outgoingImage] : [],
      );
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
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if ((input.trim() || imageAttachment) && !sending) {
                e.currentTarget.form?.requestSubmit();
              }
            }
          }}
          placeholder="Type a math prompt or attach an image... (Enter to send, Shift+Enter for newline)"
          disabled={sending}
          rows={3}
        />
        <div className="chat-attachments">
          <input
            ref={imageInputRef}
            type="file"
            accept="image/*"
            onChange={(e) => {
              void onImageChange(e);
            }}
            disabled={sending}
          />
          {imageName && (
            <div className="chat-attachment-row">
              <span>Attached: {imageName}</span>
              <button
                type="button"
                onClick={clearAttachment}
                disabled={sending}
              >
                Remove
              </button>
            </div>
          )}
        </div>
        <button type="submit" disabled={sending || (!input.trim() && !imageAttachment)}>
          {sending ? "Sending..." : "Send"}
        </button>
      </form>
    </aside>
  );
}
