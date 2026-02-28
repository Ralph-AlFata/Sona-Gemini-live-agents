from __future__ import annotations

import pytest

from dsl import apply_command
from models import DrawCommandRequest


def test_create_shape_returns_element_created_message_and_id() -> None:
    store = {}
    command = DrawCommandRequest(
        command_id="cmd_1",
        session_id="s1",
        operation="draw_shape",
        payload={
            "shape": "rectangle",
            "x": 0.1,
            "y": 0.1,
            "width": 0.4,
            "height": 0.2,
            "style": {"stroke_color": "#000000"},
        },
    )

    messages, response = apply_command(command, store)

    assert len(messages) == 1
    assert messages[0].type == "element_created"
    assert response.applied_count == 1
    assert len(response.created_element_ids) == 1


def test_move_and_resize_transform_element() -> None:
    store = {}
    create = DrawCommandRequest(
        command_id="cmd_create",
        session_id="s1",
        operation="draw_shape",
        payload={
            "shape": "square",
            "x": 0.2,
            "y": 0.2,
            "width": 0.2,
            "height": 0.2,
            "style": {},
        },
    )
    _, create_resp = apply_command(create, store)
    element_id = create_resp.created_element_ids[0]

    move = DrawCommandRequest(
        command_id="cmd_move",
        session_id="s1",
        operation="move_elements",
        payload={"element_ids": [element_id], "dx": 0.1, "dy": 0.1},
    )
    messages, response = apply_command(move, store)

    assert len(messages) == 1
    assert messages[0].type == "elements_transformed"
    assert response.applied_count == 1

    resize = DrawCommandRequest(
        command_id="cmd_resize",
        session_id="s1",
        operation="resize_elements",
        payload={"element_ids": [element_id], "scale_x": 1.5, "scale_y": 1.5},
    )
    messages, response = apply_command(resize, store)

    assert len(messages) == 1
    assert messages[0].type == "elements_transformed"
    assert response.applied_count == 1


def test_delete_and_clear() -> None:
    store = {}
    create = DrawCommandRequest(
        command_id="cmd_create_text",
        session_id="s1",
        operation="draw_text",
        payload={
            "text": "hello",
            "x": 0.2,
            "y": 0.2,
            "font_size": 20,
            "style": {},
        },
    )
    _, create_resp = apply_command(create, store)
    element_id = create_resp.created_element_ids[0]

    delete = DrawCommandRequest(
        command_id="cmd_delete",
        session_id="s1",
        operation="delete_elements",
        payload={"element_ids": [element_id]},
    )
    messages, response = apply_command(delete, store)
    assert messages[0].type == "elements_deleted"
    assert response.applied_count == 1

    clear = DrawCommandRequest(
        command_id="cmd_clear",
        session_id="s1",
        operation="clear_canvas",
        payload={"mode": "full"},
    )
    messages, response = apply_command(clear, store)
    assert messages[0].type == "clear"
    assert response.applied_count == 1


def test_legacy_message_type_is_rejected() -> None:
    with pytest.raises(Exception):
        DrawCommandRequest(
            session_id="s1",
            message_type="text",
            payload={
                "text": "legacy",
                "x": 0.1,
                "y": 0.1,
                "font_size": 16,
                "color": "#222",
            },
        )
