from __future__ import annotations

import httpx
import pytest

from session_client import SessionServiceClient


@pytest.mark.asyncio
async def test_get_session_returns_none_for_404() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=404, json={"detail": "not found"})

    client = SessionServiceClient("http://session:8003")
    client._client = httpx.AsyncClient(
        base_url="http://session:8003",
        transport=httpx.MockTransport(handler),
        timeout=3.0,
    )

    result = await client.get_session("missing-session")
    assert result is None
    await client.close()


@pytest.mark.asyncio
async def test_create_session_posts_expected_payload() -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(
            status_code=201,
            json={
                "session_id": "dev-session",
                "student_id": "demo-user",
                "topic": None,
                "status": "active",
                "created_at": "2026-03-12T00:00:00+00:00",
                "updated_at": "2026-03-12T00:00:00+00:00",
                "turns": [],
                "latest_snapshot": None,
            },
        )

    client = SessionServiceClient("http://session:8003")
    client._client = httpx.AsyncClient(
        base_url="http://session:8003",
        transport=httpx.MockTransport(handler),
        timeout=3.0,
    )

    await client.create_session(
        session_id="dev-session",
        student_id="demo-user",
        auth_token="token-abc",
    )

    assert captured["path"] == "/sessions"
    assert "\"session_id\":\"dev-session\"" in captured["body"]
    assert "\"student_id\":\"demo-user\"" in captured["body"]
    assert captured["auth"] == "Bearer token-abc"
    await client.close()


@pytest.mark.asyncio
async def test_append_turn_posts_expected_payload() -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        return httpx.Response(
            status_code=200,
            json={
                "session_id": "dev-session",
                "student_id": "demo-user",
                "topic": None,
                "status": "active",
                "created_at": "2026-03-12T00:00:00+00:00",
                "updated_at": "2026-03-12T00:00:00+00:00",
                "turns": [
                    {
                        "turn_id": "t1",
                        "role": "student",
                        "content": "hello",
                        "timestamp": "2026-03-12T00:00:01+00:00",
                    }
                ],
                "latest_snapshot": None,
            },
        )

    client = SessionServiceClient("http://session:8003")
    client._client = httpx.AsyncClient(
        base_url="http://session:8003",
        transport=httpx.MockTransport(handler),
        timeout=3.0,
    )

    await client.append_turn(
        session_id="dev-session",
        role="student",
        content="hello",
    )

    assert captured["path"] == "/sessions/dev-session/turns"
    assert "\"role\":\"student\"" in captured["body"]
    assert "\"content\":\"hello\"" in captured["body"]
    await client.close()
