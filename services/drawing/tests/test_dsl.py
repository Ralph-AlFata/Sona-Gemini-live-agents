from __future__ import annotations

import pytest

from dsl import apply_command
from models import DrawCommandRequest
from store import InMemoryElementStore

RECT_POINTS = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.5, "y": 0.1},
    {"x": 0.5, "y": 0.3},
    {"x": 0.1, "y": 0.3},
    {"x": 0.1, "y": 0.1},
]

SQUARE_POINTS = [
    {"x": 0.2, "y": 0.2},
    {"x": 0.4, "y": 0.2},
    {"x": 0.4, "y": 0.4},
    {"x": 0.2, "y": 0.4},
    {"x": 0.2, "y": 0.2},
]


async def test_create_shape_returns_element_created_message_and_id() -> None:
    store = InMemoryElementStore()
    command = DrawCommandRequest(
        command_id="cmd_1",
        session_id="s1",
        operation="draw_shape",
        payload={
            "shape": "rectangle",
            "points": RECT_POINTS,
            "style": {"stroke_color": "#000000"},
        },
    )

    messages, response = await apply_command(command, store)

    assert len(messages) == 1
    assert messages[0].type == "element_created"
    assert response.applied_count == 1
    assert len(response.created_element_ids) == 1


async def test_set_graph_viewport_emits_single_viewport_message() -> None:
    store = InMemoryElementStore()
    command = DrawCommandRequest(
        command_id="cmd_viewport",
        session_id="s1",
        operation="set_graph_viewport",
        payload={
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
        },
    )

    messages, response = await apply_command(command, store)

    assert len(messages) == 1
    assert messages[0].type == "graph_viewport_set"
    assert messages[0].payload["viewport"]["grid_lines"] == 10
    assert response.applied_count == 1
    assert response.created_element_ids == []


async def test_move_and_resize_transform_element() -> None:
    store = InMemoryElementStore()
    create = DrawCommandRequest(
        command_id="cmd_create",
        session_id="s1",
        operation="draw_shape",
        payload={
            "shape": "square",
            "points": SQUARE_POINTS,
            "style": {},
        },
    )
    _, create_resp = await apply_command(create, store)
    element_id = create_resp.created_element_ids[0]

    move = DrawCommandRequest(
        command_id="cmd_move",
        session_id="s1",
        operation="move_elements",
        payload={"element_ids": [element_id], "dx": 0.1, "dy": 0.1},
    )
    messages, response = await apply_command(move, store)

    assert len(messages) == 1
    assert messages[0].type == "elements_transformed"
    assert response.applied_count == 1

    resize = DrawCommandRequest(
        command_id="cmd_resize",
        session_id="s1",
        operation="resize_elements",
        payload={"element_ids": [element_id], "scale_x": 1.5, "scale_y": 1.5},
    )
    messages, response = await apply_command(resize, store)

    assert len(messages) == 1
    assert messages[0].type == "elements_transformed"
    assert response.applied_count == 1


async def test_update_points_replaces_existing_shape_points() -> None:
    store = InMemoryElementStore()
    create = DrawCommandRequest(
        command_id="cmd_shape_update_create",
        session_id="s1",
        operation="draw_shape",
        payload={"shape": "rectangle", "points": RECT_POINTS, "style": {}},
    )
    _, create_resp = await apply_command(create, store)
    element_id = create_resp.created_element_ids[0]

    replacement_points = [
        {"x": 0.15, "y": 0.15},
        {"x": 0.55, "y": 0.15},
        {"x": 0.55, "y": 0.35},
        {"x": 0.15, "y": 0.35},
        {"x": 0.15, "y": 0.15},
    ]
    update = DrawCommandRequest(
        command_id="cmd_shape_update_replace",
        session_id="s1",
        operation="update_points",
        payload={"element_id": element_id, "mode": "replace", "points": replacement_points},
    )
    messages, response = await apply_command(update, store)

    assert response.applied_count == 1
    assert len(messages) == 1
    assert messages[0].type == "elements_transformed"
    transformed = messages[0].payload["elements"][0]["payload"]["points"]
    assert transformed == replacement_points


async def test_update_points_appends_to_freehand_points() -> None:
    store = InMemoryElementStore()
    create = DrawCommandRequest(
        command_id="cmd_freehand_create",
        session_id="s1",
        operation="draw_freehand",
        payload={
            "points": [{"x": 0.2, "y": 0.2}, {"x": 0.3, "y": 0.3}],
            "style": {},
        },
    )
    _, create_resp = await apply_command(create, store)
    element_id = create_resp.created_element_ids[0]

    append = DrawCommandRequest(
        command_id="cmd_freehand_append",
        session_id="s1",
        operation="update_points",
        payload={
            "element_id": element_id,
            "mode": "append",
            "points": [{"x": 0.4, "y": 0.4}, {"x": 0.5, "y": 0.5}],
        },
    )
    messages, response = await apply_command(append, store)

    assert response.applied_count == 1
    assert messages[0].type == "elements_transformed"
    transformed = messages[0].payload["elements"][0]["payload"]["points"]
    assert len(transformed) == 4
    assert transformed[-1] == {"x": 0.5, "y": 0.5}


async def test_delete_and_clear() -> None:
    store = InMemoryElementStore()
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
    _, create_resp = await apply_command(create, store)
    element_id = create_resp.created_element_ids[0]

    delete = DrawCommandRequest(
        command_id="cmd_delete",
        session_id="s1",
        operation="delete_elements",
        payload={"element_ids": [element_id]},
    )
    messages, response = await apply_command(delete, store)
    assert messages[0].type == "elements_deleted"
    assert response.applied_count == 1

    clear = DrawCommandRequest(
        command_id="cmd_clear",
        session_id="s1",
        operation="clear_canvas",
        payload={"mode": "full"},
    )
    messages, response = await apply_command(clear, store)
    assert messages[0].type == "clear"
    assert response.applied_count == 1


async def test_highlight_marker_creates_element() -> None:
    store = InMemoryElementStore()
    create = DrawCommandRequest(
        command_id="cmd_shape",
        session_id="s1",
        operation="draw_shape",
        payload={"shape": "rectangle", "points": RECT_POINTS, "style": {}},
    )
    _, create_resp = await apply_command(create, store)
    element_id = create_resp.created_element_ids[0]

    highlight = DrawCommandRequest(
        command_id="cmd_hl",
        session_id="s1",
        operation="highlight_region",
        payload={
            "element_ids": [element_id],
            "highlight_type": "marker",
        },
    )
    messages, response = await apply_command(highlight, store)
    assert len(messages) == 1
    assert messages[0].type == "element_created"
    assert messages[0].payload["element_type"] == "highlight"
    highlight_payload = messages[0].payload["payload"]
    assert highlight_payload["target_element_ids"] == [element_id]
    assert highlight_payload["padding"] == 0.02
    assert response.applied_count == 1


async def test_highlight_circle_creates_freehand() -> None:
    store = InMemoryElementStore()
    create = DrawCommandRequest(
        command_id="cmd_shape2",
        session_id="s1",
        operation="draw_shape",
        payload={"shape": "rectangle", "points": RECT_POINTS, "style": {}},
    )
    _, create_resp = await apply_command(create, store)
    element_id = create_resp.created_element_ids[0]

    highlight = DrawCommandRequest(
        command_id="cmd_circle",
        session_id="s1",
        operation="highlight_region",
        payload={
            "element_ids": [element_id],
            "highlight_type": "circle",
        },
    )
    messages, response = await apply_command(highlight, store)
    assert len(messages) == 1
    assert messages[0].type == "element_created"
    assert messages[0].payload["element_type"] == "freehand"
    circle_payload = messages[0].payload["payload"]
    assert circle_payload["highlight_kind"] == "circle"
    assert circle_payload["highlight_part"] == "ellipse"
    assert circle_payload["target_element_ids"] == [element_id]
    assert circle_payload["padding"] == 0.02
    assert response.applied_count == 1


async def test_highlight_pointer_creates_ellipse_and_arrow_with_metadata() -> None:
    store = InMemoryElementStore()
    create = DrawCommandRequest(
        command_id="cmd_shape_pointer",
        session_id="s1",
        operation="draw_shape",
        payload={"shape": "rectangle", "points": RECT_POINTS, "style": {}},
    )
    _, create_resp = await apply_command(create, store)
    element_id = create_resp.created_element_ids[0]

    highlight = DrawCommandRequest(
        command_id="cmd_pointer",
        session_id="s1",
        operation="highlight_region",
        payload={
            "element_ids": [element_id],
            "highlight_type": "pointer",
        },
    )
    messages, response = await apply_command(highlight, store)
    assert len(messages) == 2
    assert all(message.type == "element_created" for message in messages)
    assert all(message.payload["element_type"] == "freehand" for message in messages)
    parts = {
        message.payload["payload"]["highlight_part"]
        for message in messages
    }
    assert parts == {"ellipse", "arrow"}
    for message in messages:
        payload = message.payload["payload"]
        assert payload["highlight_kind"] == "pointer"
        assert payload["target_element_ids"] == [element_id]
        assert payload["padding"] == 0.02
    assert response.applied_count == 2


async def test_erase_region_removes_intersecting_elements() -> None:
    store = InMemoryElementStore()
    create = DrawCommandRequest(
        command_id="cmd_er",
        session_id="s1",
        operation="draw_shape",
        payload={"shape": "rectangle", "points": RECT_POINTS, "style": {}},
    )
    _, create_resp = await apply_command(create, store)
    assert len(create_resp.created_element_ids) == 1

    erase = DrawCommandRequest(
        command_id="cmd_erase",
        session_id="s1",
        operation="erase_region",
        payload={"x": 0.0, "y": 0.0, "width": 0.8, "height": 0.8},
    )
    messages, response = await apply_command(erase, store)
    assert messages[0].type == "elements_deleted"
    assert response.applied_count == 1
    # Verify element gone from store
    elements = await store.get_all_elements("s1")
    assert len(elements) == 0


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
