from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main


class FakeFunctionCall:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeEvent:
    def __init__(self, text: str = "", calls: list[str] | None = None) -> None:
        self.content = SimpleNamespace(parts=[SimpleNamespace(text=text)] if text else [])
        self._calls = [FakeFunctionCall(name) for name in (calls or [])]

    def get_function_calls(self) -> list[FakeFunctionCall]:
        return self._calls


class FakeRunner:
    async def run_async(self, **_kwargs):  # type: ignore[no-untyped-def]
        yield FakeEvent(text="I can help with that.", calls=["draw_text"])
        yield FakeEvent(text="Here is the next step.", calls=["draw_text", "highlight_region"])


class FakeSessionService:
    def __init__(self) -> None:
        self._sessions: set[str] = set()
        self.create_calls = 0

    async def get_session(self, *, app_name: str, user_id: str, session_id: str):  # type: ignore[no-untyped-def]
        if (app_name, user_id, session_id) in self._sessions:
            return {"id": session_id}
        return None

    async def create_session(self, *, app_name: str, user_id: str, state: dict, session_id: str):  # type: ignore[no-untyped-def]
        self._sessions.add((app_name, user_id, session_id))
        self.create_calls += 1
        assert state.get("session_id") == session_id
        return {"id": session_id}


class FakeQueue:
    def close(self) -> None:
        return None


class FakeRuntime:
    def __init__(self, session_service: FakeSessionService) -> None:
        self.runner = FakeRunner()
        self.session_service = session_service
        self.chat_run_config = main.RunConfig(response_modalities=["TEXT"])
        self.live_request_queue = FakeQueue()


def test_chat_mock_mode_returns_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.settings, "chat_mode", "mock")
    monkeypatch.setattr(main, "_configure_gemini_environment", lambda: False)

    with TestClient(main.app) as client:
        response = client.post("/chat/s1", json={"text": "draw a line"})
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "s1"
        assert data["user_text"] == "draw a line"
        assert "Mock mode response" in data["assistant_text"]
        assert "draw_text" in data["tool_calls"]


def test_chat_gemini_mode_aggregates_text_tools_and_reuses_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_service = FakeSessionService()
    runtime = FakeRuntime(session_service)

    monkeypatch.setattr(main.settings, "chat_mode", "auto")
    monkeypatch.setattr(main, "_configure_gemini_environment", lambda: True)
    monkeypatch.setattr(main, "build_live_runtime", lambda: runtime)

    with TestClient(main.app) as client:
        first = client.post("/chat/dev-session", json={"text": "first prompt"})
        second = client.post("/chat/dev-session", json={"text": "second prompt"})

    assert first.status_code == 200
    payload = first.json()
    assert payload["assistant_text"] == "I can help with that.\nHere is the next step."
    assert payload["tool_calls"] == ["draw_text", "highlight_region"]
    assert second.status_code == 200
    assert session_service.create_calls == 1


def test_chat_empty_text_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.settings, "chat_mode", "mock")
    monkeypatch.setattr(main, "_configure_gemini_environment", lambda: False)

    with TestClient(main.app) as client:
        response = client.post("/chat/s2", json={"text": "   "})
        assert response.status_code == 422


def test_chat_mode_gemini_fails_startup_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main.settings, "chat_mode", "gemini")
    monkeypatch.setattr(main.settings, "google_genai_use_vertexai", False)
    monkeypatch.setattr(main.settings, "google_api_key", "")

    with pytest.raises(RuntimeError):
        with TestClient(main.app):
            pass
