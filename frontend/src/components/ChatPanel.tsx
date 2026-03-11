import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  connectLive,
  disconnectLive,
  sendActivityEnd,
  sendActivityStart,
  sendAudioChunk,
  sendImageFrame,
  type LiveConnectionStatus,
  type LiveEventPayload,
} from "../services/orchestratorLive";
import { startAudioPlayerWorklet } from "../services/audio-player";
import { startAudioRecorderWorklet, stopMicrophone } from "../services/audio-recorder";

const USER_ID = "demo-user";
const MAX_TURNS = 80;

interface LiveTurn {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
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
  if (!match) return null;
  const mimeType = match[1];
  const dataBase64 = match[2];
  if (!mimeType || !dataBase64) return null;
  return { mimeType, dataBase64 };
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  let standardBase64 = base64.replace(/-/g, "+").replace(/_/g, "/");
  while (standardBase64.length % 4 !== 0) {
    standardBase64 += "=";
  }
  const binaryString = window.atob(standardBase64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

export function ChatPanel({ sessionId }: ChatPanelProps) {
  const [status, setStatus] = useState<LiveConnectionStatus>("disconnected");
  const [turns, setTurns] = useState<LiveTurn[]>([]);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [proactivity, setProactivity] = useState(false);
  const [affectiveDialog, setAffectiveDialog] = useState(false);

  const playerNodeRef = useRef<AudioWorkletNode | null>(null);
  const playerContextRef = useRef<AudioContext | null>(null);
  const recorderNodeRef = useRef<AudioWorkletNode | null>(null);
  const recorderContextRef = useRef<AudioContext | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const isSpeakingRef = useRef(false);

  const addTurn = useCallback((role: LiveTurn["role"], text: string) => {
    const clean = text.trim();
    if (!clean) return;
    const nextTurn: LiveTurn = {
      id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role,
      text: clean,
    };
    setTurns((prev) => [...prev, nextTurn].slice(-MAX_TURNS));
  }, []);

  const handleEvent = useCallback((event: LiveEventPayload) => {
    if (event.error) {
      addTurn("system", `Live error: ${event.error}`);
    }

    if (event.inputTranscription?.finished && event.inputTranscription.text) {
      addTurn("user", event.inputTranscription.text);
    }
    if (event.outputTranscription?.finished && event.outputTranscription.text) {
      addTurn("assistant", event.outputTranscription.text);
    }

    const parts = event.content?.parts ?? [];
    for (const part of parts) {
      const audioData = part.inlineData?.data;
      const mimeType = part.inlineData?.mimeType ?? "";
      if (audioData && mimeType.startsWith("audio/pcm") && playerNodeRef.current) {
        playerNodeRef.current.port.postMessage(base64ToArrayBuffer(audioData));
      }
      if (part.text && !part.thought && !event.outputTranscription?.text) {
        addTurn("assistant", part.text);
      }
    }
  }, [addTurn]);

  useEffect(() => {
    connectLive(
      USER_ID,
      sessionId,
      { proactivity, affectiveDialog },
      handleEvent,
      setStatus,
    );

    return () => {
      disconnectLive();
    };
  }, [affectiveDialog, handleEvent, proactivity, sessionId]);

  async function startAudio(): Promise<void> {
    if (audioEnabled) return;
    try {
      const [playerNode, playerContext] = await startAudioPlayerWorklet();
      const [recorderNode, recorderContext, micStream] = await startAudioRecorderWorklet(
        (pcmData) => {
          if (isSpeakingRef.current) {
            void sendAudioChunk(pcmData);
          }
        },
      );
      playerNodeRef.current = playerNode;
      playerContextRef.current = playerContext;
      recorderNodeRef.current = recorderNode;
      recorderContextRef.current = recorderContext;
      micStreamRef.current = micStream;
      setAudioEnabled(true);
      addTurn("system", "Audio streaming started.");
    } catch (error) {
      addTurn("system", `Failed to start audio: ${String(error)}`);
    }
  }

  async function stopAudio(): Promise<void> {
    if (recorderNodeRef.current) {
      recorderNodeRef.current.disconnect();
      recorderNodeRef.current = null;
    }
    if (playerNodeRef.current) {
      playerNodeRef.current.port.postMessage({ command: "endOfAudio" });
      playerNodeRef.current.disconnect();
      playerNodeRef.current = null;
    }
    stopMicrophone(micStreamRef.current);
    micStreamRef.current = null;

    if (recorderContextRef.current) {
      await recorderContextRef.current.close();
      recorderContextRef.current = null;
    }
    if (playerContextRef.current) {
      await playerContextRef.current.close();
      playerContextRef.current = null;
    }

    setAudioEnabled(false);
    addTurn("system", "Audio streaming stopped.");
  }

  function startSpeaking(): void {
    if (!audioEnabled || isSpeakingRef.current) return;
    // Flush any buffered assistant audio so a new user turn starts clean.
    if (playerNodeRef.current) {
      playerNodeRef.current.port.postMessage({ command: "endOfAudio" });
    }
    isSpeakingRef.current = true;
    setIsSpeaking(true);
    const sent = sendActivityStart();
    if (!sent) {
      isSpeakingRef.current = false;
      setIsSpeaking(false);
    }
  }

  function stopSpeaking(): void {
    if (!isSpeakingRef.current) return;
    isSpeakingRef.current = false;
    setIsSpeaking(false);
    sendActivityEnd();
  }

  useEffect(() => {
    return () => {
      void stopAudio();
    };
  }, []);

  async function onImageChange(e: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      addTurn("system", "Only image files are supported.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      addTurn("system", "Image exceeds 10 MB limit.");
      return;
    }

    try {
      const dataUrl = await readFileAsDataUrl(file);
      const parsed = parseDataUrl(dataUrl);
      if (!parsed) {
        throw new Error("Invalid data URL");
      }
      const sent = sendImageFrame(parsed.dataBase64, parsed.mimeType);
      if (!sent) {
        addTurn("system", "Image was not sent (live socket disconnected).");
      } else {
        addTurn("user", `[Image] ${file.name}`);
      }
    } catch {
      addTurn("system", "Failed to load image attachment.");
    } finally {
      e.target.value = "";
    }
  }

  return (
    <aside className="chat-panel">
      <div className="chat-header">
        <strong>Live Agent</strong>
        <span className="chat-session">session: {sessionId}</span>
        <span className="chat-session">status: {status}</span>
      </div>

      <div className="chat-controls">
        <label className="chat-toggle">
          <input
            type="checkbox"
            checked={proactivity}
            onChange={(e) => setProactivity(e.target.checked)}
          />
          proactivity
        </label>
        <label className="chat-toggle">
          <input
            type="checkbox"
            checked={affectiveDialog}
            onChange={(e) => setAffectiveDialog(e.target.checked)}
          />
          affective dialog
        </label>
      </div>

      <div className="chat-log">
        {turns.length === 0 ? (
          <div className="chat-empty">Start audio and speak to Sona.</div>
        ) : (
          turns.map((turn) => (
            <div key={turn.id} className={`chat-turn chat-${turn.role}`}>
              <div className="chat-role">{turn.role}</div>
              <div className="chat-text">{turn.text}</div>
            </div>
          ))
        )}
      </div>

      <div className="chat-form">
        <button
          type="button"
          onClick={() => {
            if (audioEnabled) {
              void stopAudio();
            } else {
              void startAudio();
            }
          }}
        >
          {audioEnabled ? "Stop Audio" : "Start Audio"}
        </button>
        {audioEnabled && (
          <button
            type="button"
            className={`push-to-talk ${isSpeaking ? "speaking" : ""}`}
            onMouseDown={startSpeaking}
            onMouseUp={stopSpeaking}
            onMouseLeave={stopSpeaking}
            onTouchStart={(e) => {
              e.preventDefault();
              startSpeaking();
            }}
            onTouchEnd={(e) => {
              e.preventDefault();
              stopSpeaking();
            }}
          >
            {isSpeaking ? "Speaking..." : "Hold to Talk"}
          </button>
        )}
        <div className="chat-attachments">
          <input
            type="file"
            accept="image/*"
            onChange={(e) => {
              void onImageChange(e);
            }}
          />
        </div>
      </div>
    </aside>
  );
}
