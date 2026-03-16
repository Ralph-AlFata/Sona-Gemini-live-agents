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
  const [authSession, setAuthSessionRaw] = useState<AuthSession | null>(null);
  const authSessionRef = useRef<AuthSession | null>(null);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<"signin" | "signup">("signin");
  const authUserIdRef = useRef<string | null>(null);

  // Update both state (for UI) and ref (for async reads) together
  const setAuthSession = useCallback((session: AuthSession | null) => {
    authSessionRef.current = session;
    setAuthSessionRaw(session);
  }, []);

  /** Stable getter — always returns the latest token without causing re-renders. */
  const getAuthToken = useCallback((): string => {
    return authSessionRef.current?.idToken ?? "";
  }, []);
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
  const snapshotExporterRef = useRef<(() => Promise<string | null>) | null>(null);

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
      authUserIdRef.current = null;
      setAuthSession(null);
      resetSessionState();
      setAuthError(message);
    },
    [resetSessionState],
  );

  /** Refresh the token silently — updates the ref + localStorage but does NOT
   *  trigger React re-renders, so WebSocket connections stay stable. */
  const refreshAuthSession = useCallback(async (session: AuthSession): Promise<AuthSession> => {
    const refreshed = await ensureValidSession(session);
    if (!refreshed) {
      throw new Error("Session expired");
    }
    // Always keep the ref current so async code reads the latest token
    authSessionRef.current = refreshed;
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
      authUserIdRef.current = null;
      setSessions([]);
      switchSessionView(null);
      return;
    }
    // Only reload sessions on sign-in / user change, not on token refreshes
    if (authUserIdRef.current === authSession.userId) return;
    authUserIdRef.current = authSession.userId;
    void loadSessionsForUser(authSession);
  }, [authSession, loadSessionsForUser, switchSessionView]);

  useEffect(() => {
    if (!authSession) return;
    let cancelled = false;
    const refresh = async () => {
      const current = authSessionRef.current;
      if (!current) return;
      try {
        await refreshAuthSession(current);
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
    // Only re-create timer on login/logout, not on token refreshes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authSession?.userId, handleAuthFailure, refreshAuthSession]);

  useEffect(() => {
    if (!authSession || !sessionId) {
      disconnect();
      setStatus("disconnected");
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const current = authSessionRef.current;
        if (!current) return;
        const fresh = await refreshAuthSession(current);
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
    // Reconnect on session change or login/logout, NOT on token refresh
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authSession?.userId, handleAuthFailure, handleMessage, handleStatus, refreshAuthSession, sessionId]);

  useEffect(() => {
    setMessages([]);
    setSessionElements([]);
  }, [sessionId]);

  useEffect(() => {
    if (!authSession || !sessionId) return;
    let cancelled = false;
    void (async () => {
      try {
        const current = authSessionRef.current;
        if (!current) return;
        const fresh = await refreshAuthSession(current);
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
    // Only refetch on session change or login/logout
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authSession?.userId, handleAuthFailure, isAuthExpiredError, refreshAuthSession, sessionId]);

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
    const isSignUp = authMode === "signup";
    return (
      <div className="app app-auth">
        <section className="auth-card">
          <div className="auth-logo">
            <div className="auth-logo-icon">S</div>
          </div>
          <h1 className="auth-title">
            {isSignUp ? "Create your account" : "Welcome back"}
          </h1>
          <p className="auth-subtitle">
            {isSignUp
              ? "Start learning math with your AI tutor"
              : "Sign in to continue learning"}
          </p>

          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submitAuth(isSignUp ? "signup" : "signin");
            }}
          >
            <label>
              Email
              <input
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label>
              Password
              <input
                type="password"
                autoComplete={isSignUp ? "new-password" : "current-password"}
                placeholder={isSignUp ? "Create a password" : "Enter your password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={6}
              />
            </label>

            {authError ? (
              <div className="auth-error" role="alert">
                <span className="auth-error-icon">!</span>
                {authError}
              </div>
            ) : null}

            <button className="auth-submit" type="submit" disabled={authBusy}>
              {authBusy ? (
                <span className="auth-spinner" />
              ) : isSignUp ? (
                "Create Account"
              ) : (
                "Sign In"
              )}
            </button>
          </form>

          <div className="auth-divider">
            <span>or</span>
          </div>

          <button
            className="auth-switch"
            type="button"
            onClick={() => {
              setAuthMode(isSignUp ? "signin" : "signup");
              setAuthError(null);
            }}
          >
            {isSignUp
              ? "Already have an account? Sign in"
              : "New here? Create an account"}
          </button>
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
                  getAuthToken={getAuthToken}
                  onSnapshotExporterChange={(exporter) => {
                    snapshotExporterRef.current = exporter;
                  }}
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
                getAuthToken={getAuthToken}
                requestCanvasSnapshot={async () => {
                  return await snapshotExporterRef.current?.() ?? null;
                }}
              />
            ) : null}
          </main>
        </section>
      </div>

      <MessageLog messages={messages} />
    </div>
  );
}
