from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import auth


class _StubVerifier:
    async def verify(self, token: str) -> auth.AuthContext:
        if token == "good-token":
            return auth.AuthContext(
                student_id="student_from_token",
                claims={"sub": "student_from_token"},
            )
        raise auth.AuthError("Invalid or expired bearer token")


def _build_test_app(*, auth_enabled: bool) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        auth.SessionAuthMiddleware,
        settings=auth.AuthSettings(
            enabled=auth_enabled,
            audience=None,
        ),
        verifier=_StubVerifier(),
    )

    @app.get("/health")
    async def _health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/sessions/ping")
    async def _sessions_ping(request: Request) -> dict[str, str | None]:
        context = auth.get_auth_context(request)
        return {"student_id": context.student_id if context else None}

    return app


def test_sessions_path_requires_bearer_token_when_enabled() -> None:
    client = TestClient(_build_test_app(auth_enabled=True))
    response = client.get("/sessions/ping")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Authorization header"


def test_sessions_path_accepts_valid_bearer_token_when_enabled() -> None:
    client = TestClient(_build_test_app(auth_enabled=True))
    response = client.get(
        "/sessions/ping",
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"student_id": "student_from_token"}


def test_sessions_path_rejects_invalid_bearer_token_when_enabled() -> None:
    client = TestClient(_build_test_app(auth_enabled=True))
    response = client.get(
        "/sessions/ping",
        headers={"Authorization": "Bearer bad-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired bearer token"


def test_health_is_public_even_when_auth_enabled() -> None:
    client = TestClient(_build_test_app(auth_enabled=True))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_disabled_allows_sessions_without_token() -> None:
    client = TestClient(_build_test_app(auth_enabled=False))
    response = client.get("/sessions/ping")
    assert response.status_code == 200
    assert response.json() == {"student_id": None}
