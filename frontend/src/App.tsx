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

const MOBILE_SIDEBAR_QUERY = "(max-width: 980px)";

function isMobileSidebarViewport(): boolean {
  return window.matchMedia(MOBILE_SIDEBAR_QUERY).matches;
}

function displaySessionName(session: SessionRecord): string {
  const label = session.topic?.trim();
  if (label && label.length > 0) return label;
  return `Session ${session.session_id.slice(0, 6)}`;
}

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
  const [sessionsBusy, setSessionsBusy] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sessionMenuId, setSessionMenuId] = useState<string | null>(null);

  const activeSession = useMemo(
    () => sessions.find((session) => session.session_id === activeSessionId) ?? null,
    [activeSessionId, sessions],
  );
  const sessionId = activeSession?.session_id ?? "";
  const showSidebarBackdrop = sidebarOpen && isMobileSidebarViewport();
  const activeSessionIdRef = useRef("");

  useEffect(() => {
    activeSessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    setSessionMenuId(null);
  }, [activeSessionId]);

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
    setSessionsError(null);
    setMessages([]);
    setSessionElements([]);
    setStatus("disconnected");
    setSidebarOpen(false);
    setSessionMenuId(null);
  }, []);

  const switchSessionView = useCallback((next: SessionRecord | null) => {
    activeSessionIdRef.current = next?.session_id ?? "";
    setMessages([]);
    setSessionElements([]);
    setSessionMenuId(null);
    if (!next) {
      setActiveSessionId("");
      return;
    }
    setActiveSessionId(next.session_id);
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
      setSidebarOpen(false);
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
    if (isMobileSidebarViewport()) {
      setSidebarOpen(false);
    }
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
      if (isMobileSidebarViewport()) {
        setSidebarOpen(false);
      }
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

  async function handleRenameSession(target: SessionRecord): Promise<void> {
    if (!authSession) return;
    const requestedName = window.prompt(
      "Rename session:",
      target.topic?.trim() || displaySessionName(target),
    );
    if (requestedName === null) return;
    const cleanedName = requestedName.trim();
    if (!cleanedName) {
      setSessionsError("Session name cannot be empty");
      return;
    }
    setSessionsBusy(true);
    setSessionsError(null);
    try {
      const fresh = await refreshAuthSession(authSession);
      const updated = await renameSession(fresh.idToken, target.session_id, cleanedName);
      setSessions((prev) =>
        prev.map((item) => (item.session_id === updated.session_id ? updated : item)),
      );
      setSessionMenuId(null);
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

  async function handleDeleteSession(target: SessionRecord): Promise<void> {
    if (!authSession) return;
    const confirmed = window.confirm(
      `Delete session "${target.topic?.trim() || target.session_id}"?`,
    );
    if (!confirmed) return;

    setSessionsBusy(true);
    setSessionsError(null);
    try {
      const fresh = await refreshAuthSession(authSession);
      await deleteSession(fresh.idToken, target.session_id);

      const remaining = sessions.filter((item) => item.session_id !== target.session_id);
      const deletedActive = target.session_id === activeSession?.session_id;
      setSessions(remaining);

      if (deletedActive) {
        if (remaining.length > 0) {
          const next = remaining[0];
          if (!next) {
            throw new Error("Failed to select next session after delete");
          }
          switchSessionView(next);
        } else {
          const created = await createSession(fresh.idToken, fresh.userId, "New session");
          setSessions([created]);
          switchSessionView(created);
        }
      }
      setSessionMenuId(null);
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
        <div className="header-left">
          <button
            className="nav-toggle"
            aria-label={sidebarOpen ? "Close sessions" : "Open sessions"}
            onClick={() => {
              setSidebarOpen((prev) => !prev);
            }}
          >
            <span />
            <span />
            <span />
          </button>
          <div className="brand-stack">
            <span className="app-title">Sona</span>
            <span className="app-subtitle">
              {activeSession ? displaySessionName(activeSession) : "Live whiteboard tutor"}
            </span>
          </div>
        </div>

        <div className="header-right">
          <span className={`status-pill status-${status}`}>
            <span className="status-dot" />
            {status}
          </span>
          <span className="header-email" title={authSession.email}>
            {authSession.email}
          </span>
          <button className="header-logout" onClick={handleSignOut}>Sign Out</button>
        </div>
      </header>

      {sessionsError ? <div className="session-error">{sessionsError}</div> : null}

      <div className={`app-layout ${sidebarOpen ? "sidebar-open" : ""}`}>
        <aside className={`session-sidebar ${sidebarOpen ? "open" : ""}`}>
          <div className="session-sidebar-header">
            <h2>Your Sessions</h2>
            <button
              className="session-new-btn"
              onClick={() => {
                void handleCreateSession();
              }}
              disabled={sessionsBusy}
            >
              + New
            </button>
          </div>

          <div className="session-list-wrap">
            {sessions.length === 0 ? (
              <p className="session-empty">No sessions yet.</p>
            ) : (
              <ul className="session-list">
                {sessions.map((session) => {
                  const isActive = session.session_id === activeSessionId;
                  const isMenuOpen = sessionMenuId === session.session_id;
                  return (
                    <li
                      key={session.session_id}
                      className={`session-list-item ${isActive ? "active" : ""}`}
                    >
                      <button
                        className="session-select-btn"
                        onClick={() => handleSelectSession(session.session_id)}
                      >
                        <span className="session-title">{displaySessionName(session)}</span>
                        <span className="session-meta">{session.session_id.slice(0, 8)}</span>
                      </button>

                      <div className={`session-row-actions ${isMenuOpen ? "open" : ""}`}>
                        <button
                          className="session-action-btn"
                          title="Session menu"
                          aria-label="Open session options"
                          onClick={() => {
                            setSessionMenuId((prev) =>
                              prev === session.session_id ? null : session.session_id,
                            );
                          }}
                        >
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <circle cx="6" cy="12" r="1.5" />
                            <circle cx="12" cy="12" r="1.5" />
                            <circle cx="18" cy="12" r="1.5" />
                          </svg>
                        </button>
                        <button
                          className="session-action-btn danger"
                          title="Delete session"
                          aria-label="Delete session"
                          onClick={() => {
                            void handleDeleteSession(session);
                          }}
                          disabled={sessionsBusy}
                        >
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M4 7h16" />
                            <path d="M9 7V5h6v2" />
                            <path d="M8 7l1 12h6l1-12" />
                            <path d="M10 11v5" />
                            <path d="M14 11v5" />
                          </svg>
                        </button>
                      </div>

                      {isMenuOpen ? (
                        <div className="session-popover">
                          <button
                            onClick={() => {
                              void handleRenameSession(session);
                            }}
                            disabled={sessionsBusy}
                          >
                            Rename
                          </button>
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </aside>

        {showSidebarBackdrop ? (
          <button
            className="sidebar-backdrop"
            aria-label="Close sessions"
            onClick={() => setSidebarOpen(false)}
          />
        ) : null}

        <section className="workspace-main">
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
        </section>
      </div>

      <MessageLog messages={messages} />
    </div>
  );
}
