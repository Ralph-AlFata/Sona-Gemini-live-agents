from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_health_check() -> None:
    with TestClient(main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "drawing"}


def test_draw_create_and_edit_flow() -> None:
    with TestClient(main.app) as client:
        create = client.post(
            "/draw",
            json={
                "command_id": "cmd_a",
                "session_id": "s1",
                "operation": "draw_shape",
                "payload": {
                    "shape": "rectangle",
                    "points": [
                        {"x": 0.1, "y": 0.1},
                        {"x": 0.4, "y": 0.1},
                        {"x": 0.4, "y": 0.3},
                        {"x": 0.1, "y": 0.3},
                        {"x": 0.1, "y": 0.1},
                    ],
                    "style": {"stroke_color": "#f00", "stroke_width": 2.0},
                },
            },
        )
        assert create.status_code == 202
        body = create.json()
        assert body["applied_count"] == 1
        element_id = body["created_element_ids"][0]

        move = client.post(
            "/draw",
            json={
                "command_id": "cmd_b",
                "session_id": "s1",
                "operation": "move_elements",
                "payload": {"element_ids": [element_id], "dx": 0.1, "dy": 0.0},
            },
        )
        assert move.status_code == 202
        assert move.json()["applied_count"] == 1

        style = client.post(
            "/draw",
            json={
                "command_id": "cmd_c",
                "session_id": "s1",
                "operation": "update_style",
                "payload": {"element_ids": [element_id], "stroke_color": "#00f"},
            },
        )
        assert style.status_code == 202
        assert style.json()["applied_count"] == 1


def test_draw_clear_returns_202() -> None:
    with TestClient(main.app) as client:
        response = client.post("/draw/clear", json={"session_id": "clear-s1"})
        assert response.status_code == 202
        assert response.json()["operation"] == "clear_canvas"


def test_draw_invalid_payload_returns_422() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/draw",
            json={
                "command_id": "cmd_invalid",
                "session_id": "s1",
                "operation": "draw_freehand",
                "payload": {
                    "points": [{"x": 1.2, "y": 0.1}, {"x": 0.2, "y": 0.3}],
                    "style": {"stroke_color": "#000"},
                },
            },
        )
        assert response.status_code == 422


def test_websocket_receives_broadcast_after_draw() -> None:
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws/test-room") as ws:
            response = client.post(
                "/draw",
                json={
                    "command_id": "cmd_ws",
                    "session_id": "test-room",
                    "operation": "draw_text",
                    "payload": {
                        "text": "hello",
                        "x": 0.3,
                        "y": 0.4,
                        "font_size": 18,
                        "style": {"stroke_color": "#000"},
                    },
                },
            )
            assert response.status_code == 202
            msg = ws.receive_json()
            assert msg["version"] == "2.0"
            assert msg["session_id"] == "test-room"
            assert msg["type"] == "element_created"
