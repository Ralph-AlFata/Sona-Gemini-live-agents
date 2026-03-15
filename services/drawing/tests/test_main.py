from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import main


def test_health_check() -> None:
    with TestClient(main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "drawing"}


def test_draw_create_and_edit_flow() -> None:
def test_draw_create_and_edit_flow() -> None:
    with TestClient(main.app) as client:
        create = client.post(
            "/draw",
            json={
                "command_id": "cmd_a",
        create = client.post(
            "/draw",
            json={
                "command_id": "cmd_a",
                "session_id": "s1",
                "operation": "draw_shape",
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
        assert create.status_code == 200
        body = create.json()
        assert body["applied_count"] == 1
        element_id = body["created_element_ids"][0]

        move = client.post(
            "/draw",
            json={
                "command_id": "cmd_b",
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
        assert create.status_code == 200
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
        assert move.status_code == 200
        assert move.json()["applied_count"] == 1

        update_points = client.post(
            "/draw",
            json={
                "command_id": "cmd_b2",
                "operation": "move_elements",
                "payload": {"element_ids": [element_id], "dx": 0.1, "dy": 0.0},
            },
        )
        assert move.status_code == 200
        assert move.json()["applied_count"] == 1

        update_points = client.post(
            "/draw",
            json={
                "command_id": "cmd_b2",
                "session_id": "s1",
                "operation": "update_points",
                "operation": "update_points",
                "payload": {
                    "element_id": element_id,
                    "mode": "replace",
                    "points": [
                        {"x": 0.2, "y": 0.2},
                        {"x": 0.5, "y": 0.2},
                        {"x": 0.5, "y": 0.35},
                        {"x": 0.2, "y": 0.35},
                        {"x": 0.2, "y": 0.2},
                    ],
                },
            },
        )
        assert update_points.status_code == 200
        assert update_points.json()["applied_count"] == 1

        style = client.post(
            "/draw",
            json={
                "command_id": "cmd_c",
                    "element_id": element_id,
                    "mode": "replace",
                    "points": [
                        {"x": 0.2, "y": 0.2},
                        {"x": 0.5, "y": 0.2},
                        {"x": 0.5, "y": 0.35},
                        {"x": 0.2, "y": 0.35},
                        {"x": 0.2, "y": 0.2},
                    ],
                },
            },
        )
        assert update_points.status_code == 200
        assert update_points.json()["applied_count"] == 1

        style = client.post(
            "/draw",
            json={
                "command_id": "cmd_c",
                "session_id": "s1",
                "operation": "update_style",
                "payload": {"element_ids": [element_id], "stroke_color": "#00f"},
            },
        )
        assert style.status_code == 200
        assert style.json()["applied_count"] == 1

        labels = client.post(
            "/draw",
            json={
                "command_id": "cmd_d",
                "session_id": "s1",
                "operation": "set_shape_labels",
                "payload": {"element_id": element_id, "labels": ["a", "b", "c"]},
                "operation": "update_style",
                "payload": {"element_ids": [element_id], "stroke_color": "#00f"},
            },
        )
        assert style.status_code == 200
        assert style.json()["applied_count"] == 1

        labels = client.post(
            "/draw",
            json={
                "command_id": "cmd_d",
                "session_id": "s1",
                "operation": "set_shape_labels",
                "payload": {"element_id": element_id, "labels": ["a", "b", "c"]},
            },
        )
        assert labels.status_code == 200
        assert len(labels.json()["created_element_ids"]) == 3


def test_draw_clear_returns_200() -> None:
    with TestClient(main.app) as client:
        response = client.post("/draw/clear", json={"session_id": "clear-s1"})
        assert response.status_code == 200
        assert response.json()["operation"] == "clear_canvas"
        )
        assert labels.status_code == 200
        assert len(labels.json()["created_element_ids"]) == 3


def test_draw_clear_returns_200() -> None:
    with TestClient(main.app) as client:
        response = client.post("/draw/clear", json={"session_id": "clear-s1"})
        assert response.status_code == 200
        assert response.json()["operation"] == "clear_canvas"


def test_draw_invalid_payload_returns_422() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/draw",
            json={
                "command_id": "cmd_invalid",
                "command_id": "cmd_invalid",
                "session_id": "s1",
                "operation": "draw_freehand",
                "operation": "draw_freehand",
                "payload": {
                    "points": [{"x": 1.2, "y": 0.1}, {"x": 0.2, "y": 0.3}],
                    "style": {"stroke_color": "#000"},
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
                    "command_id": "cmd_ws",
                    "session_id": "test-room",
                    "operation": "draw_text",
                    "operation": "draw_text",
                    "payload": {
                        "text": "hello",
                        "x": 0.3,
                        "y": 0.4,
                        "font_size": 18,
                        "style": {"stroke_color": "#000"},
                        "style": {"stroke_color": "#000"},
                    },
                },
            )
            assert response.status_code == 200
            assert response.status_code == 200
            msg = ws.receive_json()
            assert msg["version"] == "2.0"
            assert msg["version"] == "2.0"
            assert msg["session_id"] == "test-room"
            assert msg["type"] == "element_created"
            assert msg["type"] == "element_created"


def test_websocket_receives_graph_viewport_message() -> None:
def test_websocket_receives_graph_viewport_message() -> None:
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws/graph-room") as ws:
        with client.websocket_connect("/ws/graph-room") as ws:
            response = client.post(
                "/draw",
                json={
                    "command_id": "cmd_viewport_ws",
                    "session_id": "graph-room",
                    "operation": "set_graph_viewport",
                    "command_id": "cmd_viewport_ws",
                    "session_id": "graph-room",
                    "operation": "set_graph_viewport",
                    "payload": {
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.8,
                        "height": 0.8,
                        "domain_min": -10,
                        "domain_max": 10,
                        "y_min": -10,
                        "y_max": 10,
                        "grid_lines": 10,
                        "show_border": True,
                        "border_color": "#444444",
                        "border_opacity": 0.5,
                        "axis_color": "#111111",
                        "axis_width": 2.0,
                        "grid_color": "#bbbbbb",
                        "grid_opacity": 0.5,
                        "y": 0.1,
                        "width": 0.8,
                        "height": 0.8,
                        "domain_min": -10,
                        "domain_max": 10,
                        "y_min": -10,
                        "y_max": 10,
                        "grid_lines": 10,
                        "show_border": True,
                        "border_color": "#444444",
                        "border_opacity": 0.5,
                        "axis_color": "#111111",
                        "axis_width": 2.0,
                        "grid_color": "#bbbbbb",
                        "grid_opacity": 0.5,
                    },
                },
            )
            assert response.status_code == 200
            msg = ws.receive_json()
            assert msg["version"] == "2.0"
            assert msg["session_id"] == "graph-room"
            assert msg["type"] == "graph_viewport_set"


def test_get_session_state_returns_element_created_messages() -> None:
    with TestClient(main.app) as client:
        created = client.post(
            "/draw",
            json={
                "command_id": "cmd_state",
                "session_id": "state-room",
                "operation": "draw_text",
                "payload": {
                    "text": "state hydrate",
                    "x": 0.25,
                    "y": 0.35,
                    "font_size": 22,
                    "style": {"stroke_color": "#222222"},
                },
            },
        )
        assert created.status_code == 200

        state = client.get("/sessions/state-room/state")
        assert state.status_code == 200
        body = state.json()
        assert body["session_id"] == "state-room"
        assert body["element_count"] == 1
        assert len(body["dsl_messages"]) == 1

        msg = body["dsl_messages"][0]
        assert msg["type"] == "element_created"
        assert msg["payload"]["element_type"] == "text"
        assert msg["payload"]["payload"]["text"] == "state hydrate"
        assert msg["payload"]["payload"]["color"] == "#222222"


def test_get_session_elements_returns_direct_snapshots() -> None:
    with TestClient(main.app) as client:
        created = client.post(
            "/draw",
            json={
                "command_id": "cmd_elements",
                "session_id": "elements-room",
                "operation": "draw_text",
                "payload": {
                    "text": "hydrate directly",
                    "x": 0.2,
                    "y": 0.3,
                    "font_size": 20,
                    "style": {"stroke_color": "#333333"},
                },
            },
        )
        assert created.status_code == 200

        response = client.get("/sessions/elements-room/elements")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1
        row = body[0]
        assert row["session_id"] == "elements-room"
        assert row["element_type"] == "text"
        assert row["source"] == "ai"
        assert row["payload"]["text"] == "hydrate directly"
        assert row["payload"]["color"] == "#333333"
        assert row["payload"]["source"] == "ai"


def test_canvas_state_returns_sources_labels_and_bbox() -> None:
    with TestClient(main.app) as client:
        shape = client.post(
            "/draw",
            json={
                "command_id": "cmd_canvas_shape",
                "session_id": "canvas-state-room",
                "operation": "draw_shape",
                "payload": {
                    "shape": "rectangle",
                    "points": [
                        {"x": 0.1, "y": 0.2},
                        {"x": 0.3, "y": 0.2},
                        {"x": 0.3, "y": 0.4},
                        {"x": 0.1, "y": 0.4},
                        {"x": 0.1, "y": 0.2},
                    ],
                    "style": {"stroke_color": "#111111"},
                },
            },
        )
        shape_id = shape.json()["created_element_ids"][0]
        labels = client.post(
            "/draw",
            json={
                "command_id": "cmd_canvas_labels",
                "session_id": "canvas-state-room",
                "operation": "set_shape_labels",
                "payload": {"element_id": shape_id, "labels": ["AB", "BC", "CA"]},
            },
        )
        assert labels.status_code == 200
        user_text = client.post(
            "/draw",
            json={
                "command_id": "cmd_canvas_text",
                "session_id": "canvas-state-room",
                "operation": "draw_text",
                "source": "user",
                "payload": {
                    "text": "student note",
                    "x": 0.55,
                    "y": 0.6,
                    "font_size": 20,
                    "style": {"stroke_color": "#444444"},
                },
            },
        )
        assert user_text.status_code == 200

        response = client.get("/sessions/canvas-state-room/canvas_state")
        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == "canvas-state-room"
        assert body["element_count"] == 5

        rectangle = next(item for item in body["elements"] if item["id"] == shape_id)
        assert rectangle["type"] == "rectangle"
        assert rectangle["source"] == "ai"
        assert rectangle["labels"] == ["AB", "BC", "CA"]
        assert rectangle["side_labels"] == [
            {"side_index": 0, "text": "AB", "element_id": rectangle["side_labels"][0]["element_id"]},
            {"side_index": 1, "text": "BC", "element_id": rectangle["side_labels"][1]["element_id"]},
            {"side_index": 2, "text": "CA", "element_id": rectangle["side_labels"][2]["element_id"]},
        ]
        assert rectangle["bbox"]["x"] == 0.1
        assert rectangle["bbox"]["y"] == 0.2
        assert rectangle["bbox"]["width"] == pytest.approx(0.2)
        assert rectangle["bbox"]["height"] == pytest.approx(0.2)

        student_note = next(item for item in body["elements"] if item["text"] == "student note")
        assert student_note["source"] == "user"


def test_get_session_state_sorts_by_layer_order() -> None:
    with TestClient(main.app) as client:
        high_layer = client.post(
            "/draw",
            json={
                "command_id": "cmd_state_layer_high",
                "session_id": "state-layer-room",
                "element_id": "el_high",
                "operation": "draw_text",
                "payload": {
                    "text": "top-layer",
                    "x": 0.25,
                    "y": 0.35,
                    "font_size": 22,
                    "style": {"stroke_color": "#111111", "z_index": 10},
                },
            },
        )
        assert high_layer.status_code == 200

        low_layer = client.post(
        high_layer = client.post(
            "/draw",
            json={
                "command_id": "cmd_state_layer_high",
                "session_id": "state-layer-room",
                "element_id": "el_high",
                "operation": "draw_text",
                "payload": {
                    "text": "top-layer",
                    "x": 0.25,
                    "y": 0.35,
                    "font_size": 22,
                    "style": {"stroke_color": "#111111", "z_index": 10},
                },
            },
        )
        assert high_layer.status_code == 200

        low_layer = client.post(
            "/draw",
            json={
                "command_id": "cmd_state_layer_low",
                "session_id": "state-layer-room",
                "element_id": "el_low",
                "operation": "draw_text",
                "command_id": "cmd_state_layer_low",
                "session_id": "state-layer-room",
                "element_id": "el_low",
                "operation": "draw_text",
                "payload": {
                    "text": "low-layer",
                    "x": 0.35,
                    "y": 0.45,
                    "font_size": 22,
                    "style": {"stroke_color": "#222222", "z_index": 0},
                    "text": "low-layer",
                    "x": 0.35,
                    "y": 0.45,
                    "font_size": 22,
                    "style": {"stroke_color": "#222222", "z_index": 0},
                },
            },
        )
        assert low_layer.status_code == 200

        state = client.get("/sessions/state-layer-room/state")
        assert state.status_code == 200
        body = state.json()
        texts = [
            msg["payload"]["payload"]["text"]
            for msg in body["dsl_messages"]
            if msg.get("type") == "element_created"
        ]
        assert texts == ["low-layer", "top-layer"]
        assert low_layer.status_code == 200

        state = client.get("/sessions/state-layer-room/state")
        assert state.status_code == 200
        body = state.json()
        texts = [
            msg["payload"]["payload"]["text"]
            for msg in body["dsl_messages"]
            if msg.get("type") == "element_created"
        ]
        assert texts == ["low-layer", "top-layer"]
