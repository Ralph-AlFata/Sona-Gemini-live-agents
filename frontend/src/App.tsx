import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { Whiteboard } from "./components/Whiteboard";
import { MessageLog } from "./components/MessageLog";
import {
  connect,
  disconnect,
  type ConnectionStatus,
  type DSLMessageRaw,
} from "./services/drawingSocket";
import {
  type SessionElementSnapshot,
  fetchSessionElements,
} from "./services/drawingService";
import {
  type AuthSession,
  ensureValidSession,
  loadPersistedSession,
  signInWithEmail,
  signOut,
  signUpWithEmail,
} from "./services/firebaseAuth";
import {
  createSession,
  deleteSession,
  listSessions,
  renameSession,
  type SessionRecord,
} from "./services/sessionService";
import "./App.css";

export function App() {
  const [authSession, setAuthSession] = useState<AuthSession | null>(null);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [messages, setMessages] = useState<DSLMessageRaw[]>([]);
  const [sessionElements, setSessionElements] = useState<SessionElementSnapshot[]>([]);
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [sessionNameDraft, setSessionNameDraft] = useState("");
  const [sessionsBusy, setSessionsBusy] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  const activeSession = useMemo(
    () => sessions.find((session) => session.session_id === activeSessionId) ?? null,
    [activeSessionId, sessions],
  );
  const sessionId = activeSession?.session_id ?? "";
  const activeSessionIdRef = useRef("");

  useEffect(() => {
    activeSessionIdRef.current = sessionId;
  }, [sessionId]);

  const handleMessage = useCallback((msg: DSLMessageRaw) => {
    if (msg.session_id !== activeSessionIdRef.current) return;
    setMessages((prev) => [...prev, msg]);
  }, []);

  const handleStatus = useCallback((s: ConnectionStatus) => {
    setStatus(s);
  }, []);

  const isAuthExpiredError = useCallback((error: unknown): boolean => {
    if (!(error instanceof Error)) return false;
    return /expired bearer token|session expired|invalid or expired/i.test(error.message);
  }, []);

  const resetSessionState = useCallback(() => {
    activeSessionIdRef.current = "";
    setSessions([]);
    setActiveSessionId("");
    setSessionNameDraft("");
    setSessionsError(null);
    setMessages([]);
    setSessionElements([]);
    setStatus("disconnected");
  }, []);

  const switchSessionView = useCallback((next: SessionRecord | null) => {
    activeSessionIdRef.current = next?.session_id ?? "";
    setMessages([]);
    setSessionElements([]);
    if (!next) {
      setActiveSessionId("");
      setSessionNameDraft("");
      return;
    }
    setActiveSessionId(next.session_id);
    setSessionNameDraft(next.topic ?? "");
  }, []);

  const handleAuthFailure = useCallback(
    (message: string) => {
      signOut();
      setAuthSession(null);
      resetSessionState();
      setAuthError(message);
    },
    [resetSessionState],
  );

  const refreshAuthSession = useCallback(async (session: AuthSession): Promise<AuthSession> => {
    const refreshed = await ensureValidSession(session);
    if (!refreshed) {
      throw new Error("Session expired");
    }
    if (
      refreshed.idToken !== session.idToken ||
      refreshed.refreshToken !== session.refreshToken ||
      refreshed.userId !== session.userId
    ) {
      setAuthSession(refreshed);
    }
    return refreshed;
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const persisted = loadPersistedSession();
      const session = await ensureValidSession(persisted).catch(() => null);
      if (cancelled) return;
      setAuthSession(session);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadSessionsForUser = useCallback(async (session: AuthSession): Promise<void> => {
    setSessionsBusy(true);
    setSessionsError(null);
    try {
      const fresh = await refreshAuthSession(session);
      let items = await listSessions(fresh.idToken, fresh.userId);
      if (items.length === 0) {
        const created = await createSession(fresh.idToken, fresh.userId, "New session");
        items = [created];
      }
      setSessions(items);
      switchSessionView(items[0] ?? null);
    } catch (error) {
      if (isAuthExpiredError(error)) {
        handleAuthFailure("Session expired. Please sign in again.");
        return;
      }
      setSessionsError(error instanceof Error ? error.message : "Failed to load sessions");
      setSessions([]);
      switchSessionView(null);
    } finally {
      setSessionsBusy(false);
    }
  }, [handleAuthFailure, isAuthExpiredError, refreshAuthSession, switchSessionView]);

  useEffect(() => {
    if (!authSession) {
      setSessions([]);
      switchSessionView(null);
      return;
    }
    void loadSessionsForUser(authSession);
  }, [authSession, loadSessionsForUser, switchSessionView]);

  useEffect(() => {
    if (!authSession) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        await refreshAuthSession(authSession);
      } catch {
        if (cancelled) return;
        handleAuthFailure("Session expired. Please sign in again.");
      }
    };
    const timer = window.setInterval(() => {
      void refresh();
    }, 45_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [authSession, handleAuthFailure, refreshAuthSession]);

  useEffect(() => {
    if (!authSession || !sessionId) {
      disconnect();
      setStatus("disconnected");
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const fresh = await refreshAuthSession(authSession);
        if (cancelled) return;
        connect(sessionId, fresh.idToken, handleMessage, handleStatus);
      } catch {
        if (cancelled) return;
        handleAuthFailure("Session expired. Please sign in again.");
      }
    })();
    return () => {
      cancelled = true;
      disconnect();
    };
  }, [authSession, handleAuthFailure, handleMessage, handleStatus, refreshAuthSession, sessionId]);

  useEffect(() => {
    setMessages([]);
    setSessionElements([]);
  }, [sessionId]);

  useEffect(() => {
    if (!authSession || !sessionId) return;
    let cancelled = false;
    void (async () => {
      try {
        const fresh = await refreshAuthSession(authSession);
        const elements = await fetchSessionElements(sessionId, fresh.idToken);
        if (cancelled || activeSessionIdRef.current !== sessionId) return;
        setSessionElements(
          elements.filter((element) => element.session_id === activeSessionIdRef.current),
        );
        setMessages([]);
        setSessionsError(null);
      } catch (error) {
        if (cancelled || activeSessionIdRef.current !== sessionId) return;
        if (isAuthExpiredError(error)) {
          handleAuthFailure("Session expired. Please sign in again.");
          return;
        }
        setSessionsError(error instanceof Error ? error.message : "Failed to load canvas state");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authSession, handleAuthFailure, isAuthExpiredError, refreshAuthSession, sessionId]);

  async function submitAuth(mode: "signin" | "signup"): Promise<void> {
    setAuthError(null);
    setAuthBusy(true);
    try {
      const cleanedEmail = email.trim();
      const nextSession = (
        mode === "signin"
          ? await signInWithEmail(cleanedEmail, password)
          : await signUpWithEmail(cleanedEmail, password)
      );
      setAuthSession(nextSession);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Authentication failed");
    } finally {
      setAuthBusy(false);
    }
  }

  function handleSignOut(): void {
    signOut();
    setAuthSession(null);
    resetSessionState();
  }

  function handleSelectSession(sessionIdFromUi: string): void {
    const selected = sessions.find((session) => session.session_id === sessionIdFromUi) ?? null;
    switchSessionView(selected);
  }

  async function handleCreateSession(): Promise<void> {
    if (!authSession) return;
    const requestedName = window.prompt("Name for new session:", "New session");
    if (requestedName === null) return;
    setSessionsBusy(true);
    setSessionsError(null);
    try {
      const fresh = await refreshAuthSession(authSession);
      const created = await createSession(fresh.idToken, fresh.userId, requestedName);
      setSessions((prev) => [created, ...prev]);
      switchSessionView(created);
    } catch (error) {
      if (isAuthExpiredError(error)) {
        handleAuthFailure("Session expired. Please sign in again.");
        return;
      }
      setSessionsError(error instanceof Error ? error.message : "Failed to create session");
    } finally {
      setSessionsBusy(false);
    }
  }

  async function handleRenameSession(): Promise<void> {
    if (!authSession || !activeSession) return;
    const cleanedName = sessionNameDraft.trim();
    if (!cleanedName) {
      setSessionsError("Session name cannot be empty");
      return;
    }
    setSessionsBusy(true);
    setSessionsError(null);
    try {
      const fresh = await refreshAuthSession(authSession);
      const updated = await renameSession(fresh.idToken, activeSession.session_id, cleanedName);
      setSessions((prev) =>
        prev.map((item) => (item.session_id === updated.session_id ? updated : item)),
      );
      setSessionNameDraft(updated.topic ?? "");
    } catch (error) {
      if (isAuthExpiredError(error)) {
        handleAuthFailure("Session expired. Please sign in again.");
        return;
      }
      setSessionsError(error instanceof Error ? error.message : "Failed to rename session");
    } finally {
      setSessionsBusy(false);
    }
  }

  async function handleDeleteSession(): Promise<void> {
    if (!authSession || !activeSession) return;
    const confirmed = window.confirm(
      `Delete session "${activeSession.topic ?? activeSession.session_id}"?`,
    );
    if (!confirmed) return;

    setSessionsBusy(true);
    setSessionsError(null);
    try {
      const fresh = await refreshAuthSession(authSession);
      await deleteSession(fresh.idToken, activeSession.session_id);
      const remaining = sessions.filter((item) => item.session_id !== activeSession.session_id);
      if (remaining.length > 0) {
        const next = remaining[0];
        if (!next) {
          throw new Error("Failed to select next session after delete");
        }
        setSessions(remaining);
        switchSessionView(next);
      } else {
        const created = await createSession(fresh.idToken, fresh.userId, "New session");
        setSessions([created]);
        switchSessionView(created);
      }
    } catch (error) {
      if (isAuthExpiredError(error)) {
        handleAuthFailure("Session expired. Please sign in again.");
        return;
      }
      setSessionsError(error instanceof Error ? error.message : "Failed to delete session");
    } finally {
      setSessionsBusy(false);
    }
  }

  if (!authSession) {
    return (
      <div className="app app-auth">
        <section className="auth-card">
          <h1>Sona Sign In</h1>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submitAuth("signin");
            }}
          >
            <label>
              Email
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label>
              Password
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            {authError ? <p className="auth-error">{authError}</p> : null}
            <div className="auth-actions">
              <button type="submit" disabled={authBusy}>
                {authBusy ? "Working..." : "Sign In"}
              </button>
              <button
                type="button"
                disabled={authBusy}
                onClick={() => {
                  void submitAuth("signup");
                }}
              >
                Create Account
              </button>
            </div>
          </form>
        </section>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">Sona</span>
        <span className={`status-dot status-${status}`} />
        <span className="status-label">{status}</span>
        <span className="status-label">{authSession.email}</span>
        <label className="session-picker-wrap">
          session
          <select
            value={activeSessionId}
            onChange={(event) => handleSelectSession(event.target.value)}
            disabled={sessionsBusy || sessions.length === 0}
          >
            {sessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>
                {session.topic?.trim() || session.session_id}
              </option>
            ))}
          </select>
        </label>
        <input
          className="session-name-input"
          value={sessionNameDraft}
          onChange={(event) => setSessionNameDraft(event.target.value)}
          placeholder="Session name"
          disabled={!activeSessionId || sessionsBusy}
        />
        <button
          className="header-btn"
          onClick={() => {
            void handleRenameSession();
          }}
          disabled={!activeSessionId || sessionsBusy}
        >
          Rename
        </button>
        <button
          className="header-btn"
          onClick={() => {
            void handleCreateSession();
          }}
          disabled={sessionsBusy}
        >
          New
        </button>
        <button
          className="header-btn danger"
          onClick={() => {
            void handleDeleteSession();
          }}
          disabled={!activeSessionId || sessionsBusy}
        >
          Delete
        </button>
        <button className="header-logout" onClick={handleSignOut}>Sign Out</button>
      </header>
      {sessionsError ? <div className="session-error">{sessionsError}</div> : null}

      <main className="app-canvas">
        <section className="canvas-shell">
          {sessionId ? (
            <Whiteboard
              key={sessionId}
              messages={messages}
              initialElements={sessionElements}
              sessionId={sessionId}
              authToken={authSession.idToken}
            />
          ) : (
            <div className="canvas-empty">Create or select a session to start.</div>
          )}
        </section>
        {sessionId ? (
          <ChatPanel
            key={sessionId}
            userId={authSession.userId}
            sessionId={sessionId}
            authToken={authSession.idToken}
          />
        ) : null}
      </main>

      <MessageLog messages={messages} />
    </div>
  );
}
