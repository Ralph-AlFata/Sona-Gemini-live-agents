from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_health_check() -> None:
    with TestClient(main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "drawing"}


def test_draw_all_supported_types_accept_202() -> None:
    with TestClient(main.app) as client:
        cases = [
            {
                "session_id": "s1",
                "message_type": "freehand",
                "payload": {
                    "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}],
                    "color": "#000",
                    "stroke_width": 2.0,
                    "delay_ms": 30,
                },
            },
            {
                "session_id": "s1",
                "message_type": "shape",
                "payload": {
                    "shape": "rectangle",
                    "x": 0.1,
                    "y": 0.1,
                    "width": 0.3,
                    "height": 0.3,
                    "color": "#f00",
                },
            },
            {
                "session_id": "s1",
                "message_type": "text",
                "payload": {
                    "text": "abc",
                    "x": 0.2,
                    "y": 0.2,
                    "font_size": 16,
                    "color": "#111",
                },
            },
            {
                "session_id": "s1",
                "message_type": "highlight",
                "payload": {
                    "x": 0.2,
                    "y": 0.2,
                    "width": 0.2,
                    "height": 0.2,
                    "color": "rgba(255,255,0,0.4)",
                },
            },
        ]

        for body in cases:
            response = client.post("/draw", json=body)
            assert response.status_code == 202, f"Failed for {body['message_type']}"
            assert response.json()["session_id"] == "s1"
            assert response.json()["emitted_count"] >= 1


def test_draw_invalid_payload_returns_422() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/draw",
            json={
                "session_id": "s1",
                "message_type": "freehand",
                "payload": {
                    "points": [{"x": 1.5, "y": 0.1}, {"x": 0.2, "y": 0.3}],
                    "color": "#000",
                    "stroke_width": 2.0,
                    "delay_ms": 30,
                },
            },
        )
        assert response.status_code == 422


def test_draw_returns_202_without_subscribers() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/draw",
            json={
                "session_id": "no-clients",
                "message_type": "text",
                "payload": {
                    "text": "hello",
                    "x": 0.2,
                    "y": 0.2,
                    "font_size": 16,
                    "color": "#111",
                },
            },
        )
        assert response.status_code == 202
        assert response.json() == {"session_id": "no-clients", "emitted_count": 1}


def test_draw_clear_returns_202() -> None:
    with TestClient(main.app) as client:
        response = client.post("/draw/clear", json={"session_id": "clear-s1"})
        assert response.status_code == 202
        assert response.json() == {"session_id": "clear-s1", "emitted_count": 1}


def test_websocket_receives_broadcast_after_draw() -> None:
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws/test-room") as ws:
            response = client.post(
                "/draw",
                json={
                    "session_id": "test-room",
                    "message_type": "text",
                    "payload": {
                        "text": "hello",
                        "x": 0.3,
                        "y": 0.4,
                        "font_size": 18,
                        "color": "#000",
                    },
                },
            )
            assert response.status_code == 202
            msg = ws.receive_json()
            assert msg["version"] == "1.0"
            assert msg["session_id"] == "test-room"
            assert msg["type"] == "text"


def test_multiple_websocket_clients_receive_same_message() -> None:
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws/shared") as ws1, client.websocket_connect("/ws/shared") as ws2:
            response = client.post(
                "/draw",
                json={
                    "session_id": "shared",
                    "message_type": "highlight",
                    "payload": {
                        "x": 0.1,
                        "y": 0.2,
                        "width": 0.3,
                        "height": 0.2,
                        "color": "rgba(255,255,0,0.4)",
                    },
                },
            )
            assert response.status_code == 202

            msg1 = ws1.receive_json()
            msg2 = ws2.receive_json()
            assert msg1["id"] == msg2["id"]
            assert msg1["type"] == msg2["type"] == "highlight"


def test_disconnect_cleanup_does_not_break_subsequent_broadcasts() -> None:
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws/disconnect") as ws:
            ws.close()

        response = client.post(
            "/draw",
            json={
                "session_id": "disconnect",
                "message_type": "text",
                "payload": {
                    "text": "after-close",
                    "x": 0.4,
                    "y": 0.5,
                    "font_size": 16,
                    "color": "#333",
                },
            },
        )
        assert response.status_code == 202
        assert response.json()["emitted_count"] == 1
