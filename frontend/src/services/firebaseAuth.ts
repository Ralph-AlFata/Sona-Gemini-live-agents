/**
 * Lightweight Firebase email/password auth over the REST API.
 *
 * This avoids adding SDK dependencies while still returning Firebase ID tokens
 * that backend services can verify.
 */

export interface AuthSession {
  userId: string;
  email: string;
  idToken: string;
  refreshToken: string;
}

const STORAGE_KEY = "sona_auth_session";
const REFRESH_MARGIN_SECONDS = 60;

interface FirebaseAuthResponse {
  localId?: string;
  email?: string;
  idToken?: string;
  refreshToken?: string;
  error?: { message?: string };
}

interface RefreshResponse {
  user_id?: string;
  id_token?: string;
  refresh_token?: string;
  error?: { message?: string };
}

function getApiKey(): string {
  const key = import.meta.env.VITE_FIREBASE_API_KEY;
  if (typeof key !== "string" || key.trim().length === 0) {
    throw new Error("Missing VITE_FIREBASE_API_KEY");
  }
  return key.trim();
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  const payloadPart = parts.length >= 2 ? parts[1] : null;
  if (!payloadPart) return null;
  try {
    const normalized = payloadPart.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    const decoded = atob(padded);
    return JSON.parse(decoded) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function getTokenExpiryEpochSeconds(idToken: string): number | null {
  const payload = decodeJwtPayload(idToken);
  const exp = payload?.exp;
  if (typeof exp === "number" && Number.isFinite(exp)) {
    return exp;
  }
  if (typeof exp === "string") {
    const parsed = Number(exp);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function normalizeAuthResponse(body: FirebaseAuthResponse): AuthSession {
  const userId = body.localId;
  const email = body.email;
  const idToken = body.idToken;
  const refreshToken = body.refreshToken;
  if (!userId || !email || !idToken || !refreshToken) {
    throw new Error("Firebase auth response missing required fields");
  }
  return { userId, email, idToken, refreshToken };
}

function persistSession(session: AuthSession): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

function clearPersistedSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function loadPersistedSession(): AuthSession | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<AuthSession>;
    if (
      typeof parsed.userId !== "string" ||
      typeof parsed.email !== "string" ||
      typeof parsed.idToken !== "string" ||
      typeof parsed.refreshToken !== "string"
    ) {
      return null;
    }
    return {
      userId: parsed.userId,
      email: parsed.email,
      idToken: parsed.idToken,
      refreshToken: parsed.refreshToken,
    };
  } catch {
    return null;
  }
}

async function authenticate(
  endpoint: "signUp" | "signInWithPassword",
  email: string,
  password: string,
): Promise<AuthSession> {
  const apiKey = getApiKey();
  const response = await fetch(
    `https://identitytoolkit.googleapis.com/v1/accounts:${endpoint}?key=${encodeURIComponent(apiKey)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        password,
        returnSecureToken: true,
      }),
    },
  );

  const body = (await response.json()) as FirebaseAuthResponse;
  if (!response.ok) {
    const message = body.error?.message ?? "Firebase auth failed";
    throw new Error(message);
  }

  const session = normalizeAuthResponse(body);
  persistSession(session);
  return session;
}

async function refreshSessionTokens(session: AuthSession): Promise<AuthSession> {
  const apiKey = getApiKey();
  const response = await fetch(
    `https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(apiKey)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: session.refreshToken,
      }),
    },
  );
  const body = (await response.json()) as RefreshResponse;
  if (!response.ok) {
    clearPersistedSession();
    const message = body.error?.message ?? "Firebase token refresh failed";
    throw new Error(message);
  }
  const nextIdToken = body.id_token;
  const nextRefreshToken = body.refresh_token;
  const nextUserId = body.user_id;
  if (!nextIdToken || !nextRefreshToken || !nextUserId) {
    clearPersistedSession();
    throw new Error("Firebase token refresh response missing required fields");
  }
  const next: AuthSession = {
    ...session,
    userId: nextUserId,
    idToken: nextIdToken,
    refreshToken: nextRefreshToken,
  };
  persistSession(next);
  return next;
}

export async function ensureValidSession(
  session: AuthSession | null,
): Promise<AuthSession | null> {
  if (!session) return null;
  const exp = getTokenExpiryEpochSeconds(session.idToken);
  if (!exp) return refreshSessionTokens(session);
  const nowSeconds = Math.floor(Date.now() / 1000);
  const remaining = exp - nowSeconds;
  if (remaining > REFRESH_MARGIN_SECONDS) return session;
  return refreshSessionTokens(session);
}

export async function signInWithEmail(
  email: string,
  password: string,
): Promise<AuthSession> {
  return authenticate("signInWithPassword", email, password);
}

export async function signUpWithEmail(
  email: string,
  password: string,
): Promise<AuthSession> {
  return authenticate("signUp", email, password);
}

export function signOut(): void {
  clearPersistedSession();
}
