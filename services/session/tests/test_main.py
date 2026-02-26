from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main
from models import CanvasSnapshot, Session, SessionCreate


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sessions: dict[str, Session] = {}

    def _noop() -> None:
        return None

    async def _noop_async() -> None:
        return None

    async def _create_session(payload: SessionCreate) -> Session:
        session = Session(
            student_id=payload.student_id,
            topic=payload.topic,
        )
        sessions[session.session_id] = session
        return session

    async def _get_session(session_id: str) -> Session | None:
        return sessions.get(session_id)

    async def _append_turn(session_id: str, turn: Any) -> Session:
        session = sessions[session_id]
        session.turns.append(turn)
        session.updated_at = datetime.now(tz=timezone.utc)
        return session

    async def _update_snapshot_url(session_id: str, snapshot: CanvasSnapshot) -> Session:
        session = sessions[session_id]
        session.latest_snapshot = snapshot
        session.updated_at = datetime.now(tz=timezone.utc)
        return session

    async def _delete_session(session_id: str) -> bool:
        return sessions.pop(session_id, None) is not None

    async def _upload_canvas_snapshot(session_id: str, png_bytes: bytes) -> CanvasSnapshot:
        return CanvasSnapshot(
            gcs_path=f"snapshots/{session_id}/unit-test.png",
            public_url=f"https://storage.googleapis.com/sona-canvases/snapshots/{session_id}/unit-test.png",
        )

    monkeypatch.setattr(main.fs, "init_firestore_client", _noop)
    monkeypatch.setattr(main.fs, "close_firestore_client", _noop_async)
    monkeypatch.setattr(main.st, "init_storage_client", _noop)
    monkeypatch.setattr(main.st, "close_storage_client", _noop)
    monkeypatch.setattr(main.fs, "create_session", _create_session)
    monkeypatch.setattr(main.fs, "get_session", _get_session)
    monkeypatch.setattr(main.fs, "append_turn", _append_turn)
    monkeypatch.setattr(main.fs, "update_snapshot_url", _update_snapshot_url)
    monkeypatch.setattr(main.fs, "delete_session", _delete_session)
    monkeypatch.setattr(main.st, "upload_canvas_snapshot", _upload_canvas_snapshot)

    with TestClient(main.app) as test_client:
        yield test_client


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "session"}


def test_create_session(client: TestClient) -> None:
    response = client.post(
        "/sessions",
        json={"student_id": "student_local_01", "topic": "Pythagorean theorem"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["student_id"] == "student_local_01"
    assert body["topic"] == "Pythagorean theorem"
    assert body["status"] == "active"
    assert isinstance(body["session_id"], str) and len(body["session_id"]) > 0


def test_get_session_not_found(client: TestClient) -> None:
    response = client.get("/sessions/does-not-exist")
    assert response.status_code == 404


def test_append_turn_success(client: TestClient) -> None:
    created = client.post("/sessions", json={"student_id": "s1", "topic": "triangles"})
    session_id = created.json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/turns",
        json={"role": "student", "content": "Teach me right triangles"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["turns"]) == 1
    assert body["turns"][0]["role"] == "student"
    assert body["turns"][0]["content"] == "Teach me right triangles"


def test_append_turn_not_found(client: TestClient) -> None:
    response = client.post(
        "/sessions/missing/turns",
        json={"role": "student", "content": "hello"},
    )
    assert response.status_code == 404


def test_upload_snapshot_success(client: TestClient) -> None:
    created = client.post("/sessions", json={"student_id": "s2", "topic": "circles"})
    session_id = created.json()["session_id"]

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01\xe2!\xbc3"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = client.post(
        f"/sessions/{session_id}/snapshot",
        files={"file": ("test.png", png_bytes, "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert body["snapshot"]["gcs_path"].startswith(f"snapshots/{session_id}/")


def test_upload_snapshot_empty_file(client: TestClient) -> None:
    created = client.post("/sessions", json={"student_id": "s3", "topic": "graphing"})
    session_id = created.json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/snapshot",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Uploaded file is empty"


def test_upload_snapshot_wrong_content_type(client: TestClient) -> None:
    created = client.post("/sessions", json={"student_id": "s4", "topic": "graphing"})
    session_id = created.json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/snapshot",
        files={"file": ("note.txt", b"not-a-png", "text/plain")},
    )
    assert response.status_code == 415


def test_upload_snapshot_too_large(client: TestClient) -> None:
    created = client.post("/sessions", json={"student_id": "s5", "topic": "graphing"})
    session_id = created.json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/snapshot",
        files={"file": ("big.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
    )
    assert response.status_code == 413


def test_delete_session_success_and_not_found(client: TestClient) -> None:
    created = client.post("/sessions", json={"student_id": "s6", "topic": "linear equations"})
    session_id = created.json()["session_id"]

    deleted = client.delete(f"/sessions/{session_id}")
    assert deleted.status_code == 204

    deleted_again = client.delete(f"/sessions/{session_id}")
    assert deleted_again.status_code == 404
