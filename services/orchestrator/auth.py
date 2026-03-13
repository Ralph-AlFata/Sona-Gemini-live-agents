"""Firebase token verification for orchestrator service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token


@dataclass(frozen=True)
class AuthContext:
    student_id: str
    claims: dict[str, object]


class AuthError(Exception):
    """Raised when auth token validation fails."""


class FirebaseTokenVerifier:
    def __init__(self, *, audience: str | None = None) -> None:
        self._audience = audience
        self._request = GoogleAuthRequest()

    async def verify(self, token: str) -> AuthContext:
        claims = await asyncio.to_thread(self._verify_claims, token)
        student_id = _extract_student_id(claims)
        return AuthContext(student_id=student_id, claims=claims)

    def _verify_claims(self, token: str) -> dict[str, object]:
        try:
            verified = id_token.verify_firebase_token(
                token,
                self._request,
                audience=self._audience,
            )
        except Exception as exc:  # pragma: no cover - google-auth handles typed errors
            raise AuthError("Invalid or expired bearer token") from exc
        if not isinstance(verified, dict):
            raise AuthError("Token claims payload is not a JSON object")
        return {str(key): value for key, value in verified.items()}


def _extract_student_id(claims: dict[str, object]) -> str:
    for key in ("uid", "user_id", "sub"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise AuthError("Token is missing a usable subject claim (uid/user_id/sub)")
