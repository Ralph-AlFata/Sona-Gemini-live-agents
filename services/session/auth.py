"""Authentication middleware for session service routes."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import HTTPException, Request, status
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthSettings:
    """Environment-driven auth settings for session routes."""

    enabled: bool
    audience: str | None


@dataclass(frozen=True)
class AuthContext:
    """Authenticated user context attached to a request."""

    student_id: str
    claims: dict[str, object]


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> AuthContext:
        ...


class AuthError(Exception):
    """Raised when bearer token validation fails."""


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_auth_settings() -> AuthSettings:
    """Load auth settings from environment variables."""
    enabled = _parse_bool_env("SESSION_AUTH_ENABLED", False)
    audience = os.environ.get("SESSION_AUTH_AUDIENCE")
    return AuthSettings(
        enabled=enabled,
        audience=audience if audience else None,
    )


def _extract_student_id_from_claims(claims: dict[str, object]) -> str:
    for key in ("uid", "user_id", "sub"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise AuthError("Token is missing a usable subject claim (uid/user_id/sub)")


class FirebaseTokenVerifier:
    """Verifies Firebase ID tokens."""

    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings
        self._request = GoogleAuthRequest()

    async def verify(self, token: str) -> AuthContext:
        claims = await asyncio.to_thread(self._verify_claims, token)
        student_id = _extract_student_id_from_claims(claims)
        return AuthContext(
            student_id=student_id,
            claims=claims,
        )

    def _verify_claims(self, token: str) -> dict[str, object]:
        try:
            verified = id_token.verify_firebase_token(
                token,
                self._request,
                audience=self._settings.audience,
            )
        except Exception as exc:  # pragma: no cover - google-auth handles typed errors
            raise AuthError("Invalid or expired bearer token") from exc
        if not isinstance(verified, dict):
            raise AuthError("Token claims payload is not a JSON object")
        return {str(key): value for key, value in verified.items()}


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate /sessions* routes and attach AuthContext to request.state."""

    def __init__(
        self,
        app: Any,
        *,
        settings: AuthSettings | None = None,
        verifier: TokenVerifier | None = None,
    ) -> None:
        super().__init__(app)
        self._settings = settings or load_auth_settings()
        self._verifier = verifier or FirebaseTokenVerifier(self._settings)
        logger.info(
            "Session auth middleware initialised (enabled=%s, audience=%s)",
            self._settings.enabled,
            self._settings.audience or "<unset>",
        )

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request.state.auth_context = None
        request.state.session_auth_enabled = self._settings.enabled
        if not request.url.path.startswith("/sessions"):
            return await call_next(request)
        if not self._settings.enabled:
            return await call_next(request)

        header_value = request.headers.get("authorization")
        if not header_value:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing Authorization header"},
            )

        scheme, _, token = header_value.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid Authorization header; expected Bearer token"},
            )

        try:
            auth_context = await self._verifier.verify(token.strip())
        except AuthError as exc:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": str(exc)},
            )

        request.state.auth_context = auth_context
        return await call_next(request)


def get_auth_context(request: Request) -> AuthContext | None:
    """Return request auth context if middleware set one."""
    raw = getattr(request.state, "auth_context", None)
    return raw if isinstance(raw, AuthContext) else None


def require_auth_context(request: Request) -> AuthContext:
    """Require an authenticated context on the current request."""
    auth_context = get_auth_context(request)
    if auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return auth_context
