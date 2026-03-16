from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.tools import _canonical, _cursor_store, _shared, core, editing, math_helpers, unified
from agent.tools.models import DrawShapeInput, HighlightInput
from drawing_client import DrawingCommandResult


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._counter = 0

    async def execute(
        self,
        session_id: str,
        operation: str,
        payload: dict,
        command_id: str | None = None,
        element_id: str | None = None,
        auth_token: str | None = None,
    ) -> DrawingCommandResult:
        _ = auth_token, element_id
        self._counter += 1
        created_ids = []
        if operation in {"draw_shape", "draw_text", "draw_freehand"}:
            created_ids = [f"el_test_{self._counter}"]
        elif operation == "set_shape_labels":
            labels = payload.get("labels", [])
            created_ids = [
                f"el_test_{self._counter}_{idx}"
                for idx, label in enumerate(labels)
                if isinstance(label, str) and label.strip()
            ]
        self.calls.append(
            {
                "session_id": session_id,
                "operation": operation,
                "payload": payload,
                "command_id": command_id,
            }
        )
        return DrawingCommandResult(
            session_id=session_id,
            command_id=command_id or f"cmd_test_{self._counter}",
            operation=operation,
            applied_count=1,
            created_element_ids=created_ids,
            failed_operations=[],
            emitted_count=1,
        )


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    client = _FakeClient()
    _shared._deduplicator = None
    monkeypatch.setattr(_shared, "get_client", lambda: client)
    return client


@pytest.fixture(autouse=True)
def _reset_cursor_store() -> None:
    _cursor_store._sessions.clear()


@pytest.mark.asyncio
async def test_draw_shape_maps_payload(monkeypatch: pytest.MonkeyPatch, _fake_client: _FakeClient) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_test")

    result = await core.draw_shape(
        shape="rectangle",
        points=[
            {"x": 0.1, "y": 0.2},
            {"x": 0.4, "y": 0.2},
            {"x": 0.4, "y": 0.6},
            {"x": 0.1, "y": 0.6},
            {"x": 0.1, "y": 0.2},
        ],
        stroke_color="#ff0000",
        stroke_width=3.0,
    )

    assert result["status"] == "success"
    assert len(result["created_element_ids"]) == 1
    assert result["created_element_ids"][0].startswith("el_")

    assert len(_fake_client.calls) == 1
    assert _fake_client.calls[0]["operation"] == "draw_shape"
    assert _fake_client.calls[0]["payload"]["style"]["stroke_color"] == "#ff0000"
    assert len(_fake_client.calls[0]["payload"]["points"]) == 5


@pytest.mark.asyncio
async def test_draw_circle_accepts_center_and_radius(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_test")

    result = await core.draw_shape(
        shape="circle",
        center={"x": 0.4, "y": 0.4},
        radius=0.08,
        stroke_color="#00aa00",
    )

    assert result["status"] == "success"
    assert _fake_client.calls[0]["operation"] == "draw_shape"
    assert _fake_client.calls[0]["payload"]["shape"] == "circle"
    assert len(_fake_client.calls[0]["payload"]["points"]) > 10
    assert _fake_client.calls[0]["payload"]["style"]["stroke_color"] == "#00aa00"


@pytest.mark.asyncio
async def test_auto_shape_payload_omits_null_circle_fields(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_test")

    await core.draw_shape(shape="right_triangle")

    payload = _fake_client.calls[0]["payload"]
    assert "center" not in payload
    assert "radius" not in payload


@pytest.mark.asyncio
async def test_duplicate_draw_freehand_returns_dedup_instruction_and_does_not_move_cursor(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_test")

    points = [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.3}]
    first = await core.draw_freehand(points=points)
    second = await core.draw_freehand(points=points)

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert second["deduplicated"] is True
    assert second["already_completed"] is True
    assert "ALREADY successful" in second["message"]
    assert "DO NOT call the same tool again" in second["message"]
    assert second["created_element_ids"] == first["created_element_ids"]
    assert second["previous_command_id"] == first["command_id"]
    assert second["cursor_after"] == first["cursor_after"]
    assert len(_fake_client.calls) == 1


@pytest.mark.asyncio
async def test_duplicate_auto_draw_text_deduplicates_without_advancing_cursor(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_text_dedup")

    first = await core.draw_text(text="repeat me")
    second = await core.draw_text(text="repeat me")

    assert second["deduplicated"] is True
    assert second["cursor_after"] == first["cursor_after"]
    assert len(_fake_client.calls) == 1


@pytest.mark.asyncio
async def test_duplicate_auto_draw_shape_deduplicates_without_advancing_cursor(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_shape_dedup")

    first = await core.draw_shape(shape="rectangle", width=0.2, height=0.1)
    second = await core.draw_shape(shape="rectangle", width=0.2, height=0.1)

    assert second["deduplicated"] is True
    assert second["cursor_after"] == first["cursor_after"]
    assert len(_fake_client.calls) == 1


@pytest.mark.asyncio
async def test_draw_shape_with_labels_uses_shape_label_edit_operation(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_test")

    result = await core.draw_shape(
        shape="right_triangle",
        points=[
            {"x": 0.1, "y": 0.5},
            {"x": 0.4, "y": 0.5},
            {"x": 0.1, "y": 0.2},
            {"x": 0.1, "y": 0.5},
        ],
        labels=["a", "b", "c"],
    )

    assert result["status"] == "success"
    assert result["shape_id"] == result["created_element_ids"][0]
    assert len(result["label_ids"]) == 3
    assert len(result["created_element_ids"]) == 4

    assert [call["operation"] for call in _fake_client.calls] == [
        "draw_shape",
        "set_shape_labels",
    ]
    assert _fake_client.calls[1]["payload"]["element_id"] == result["shape_id"]
    assert _fake_client.calls[1]["payload"]["labels"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_draw_shape_preserves_labels_when_hypotenuse_is_already_last_side(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_test")

    await core.draw_shape(
        shape="right_triangle",
        points=[
            {"x": 0.1, "y": 0.2},
            {"x": 0.4, "y": 0.2},
            {"x": 0.4, "y": 0.5},
            {"x": 0.1, "y": 0.2},
        ],
        labels=["a", "b", "c"],
    )

    assert _fake_client.calls[1]["payload"]["labels"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_draw_shape_skips_blank_labels(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_test")

    result = await core.draw_shape(
        shape="triangle",
        points=[
            {"x": 0.1, "y": 0.5},
            {"x": 0.3, "y": 0.2},
            {"x": 0.5, "y": 0.5},
            {"x": 0.1, "y": 0.5},
        ],
        labels=["a", "", "c"],
    )

    assert result["status"] == "success"
    assert len(result["label_ids"]) == 2
    assert [call["operation"] for call in _fake_client.calls] == [
        "draw_shape",
        "set_shape_labels",
    ]


def test_enforce_canonical_labels_right_triangle_two_labels_is_noop() -> None:
    points = [
        {"x": 0.1, "y": 0.5},
        {"x": 0.4, "y": 0.5},
        {"x": 0.1, "y": 0.2},
        {"x": 0.1, "y": 0.5},
    ]

    assert _canonical.enforce_canonical_labels("right_triangle", points, ["p", "q"]) == ["p", "q"]


def test_enforce_canonical_labels_triangle_is_noop() -> None:
    points = [
        {"x": 0.1, "y": 0.5},
        {"x": 0.3, "y": 0.2},
        {"x": 0.5, "y": 0.5},
        {"x": 0.1, "y": 0.5},
    ]

    assert _canonical.enforce_canonical_labels("triangle", points, ["a", "b", "c"]) == ["a", "b", "c"]


def test_enforce_canonical_labels_right_triangle_places_last_label_on_hypotenuse() -> None:
    points = [
        {"x": 0.1, "y": 0.5},
        {"x": 0.4, "y": 0.5},
        {"x": 0.1, "y": 0.2},
        {"x": 0.1, "y": 0.5},
    ]

    assert _canonical.enforce_canonical_labels("right_triangle", points, ["x", "y", "z"]) == ["x", "z", "y"]


def test_enforce_canonical_labels_is_deterministic_for_same_inputs() -> None:
    points = [
        {"x": 0.1, "y": 0.5},
        {"x": 0.4, "y": 0.5},
        {"x": 0.1, "y": 0.2},
        {"x": 0.1, "y": 0.5},
    ]

    first = _canonical.enforce_canonical_labels("right_triangle", points, ["a", "b", "c"])
    second = _canonical.enforce_canonical_labels("right_triangle", points, ["a", "b", "c"])

    assert first == second == ["a", "c", "b"]


@pytest.mark.asyncio
async def test_set_shape_labels_maps_payload(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(editing, "resolve_session_id", lambda _ctx: "s_test")
    async def fake_canvas_element(*, session_id: str, element_id: str) -> dict | None:
        assert session_id == "s_test"
        assert element_id == "el_shape"
        return None

    monkeypatch.setattr(editing, "_fetch_canvas_element", fake_canvas_element)

    result = await editing.set_shape_labels(
        element_id="el_shape",
        labels=["a", "", "c"],
    )

    assert result["status"] == "success"
    assert result["shape_id"] == "el_shape"
    assert _fake_client.calls[0]["operation"] == "set_shape_labels"
    assert _fake_client.calls[0]["payload"]["element_id"] == "el_shape"
    assert _fake_client.calls[0]["payload"]["labels"] == ["a", "", "c"]


@pytest.mark.asyncio
async def test_set_shape_labels_canonicalizes_existing_right_triangle(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(editing, "resolve_session_id", lambda _ctx: "s_test")

    async def fake_canvas_element(*, session_id: str, element_id: str) -> dict | None:
        assert session_id == "s_test"
        assert element_id == "el_shape"
        return {
            "id": "el_shape",
            "type": "right_triangle",
            "points": [
                {"x": 0.1, "y": 0.5},
                {"x": 0.4, "y": 0.5},
                {"x": 0.1, "y": 0.2},
                {"x": 0.1, "y": 0.5},
            ],
        }

    monkeypatch.setattr(editing, "_fetch_canvas_element", fake_canvas_element)

    await editing.set_shape_labels(
        element_id="el_shape",
        labels=["3", "4", "5"],
    )

    assert _fake_client.calls[0]["operation"] == "set_shape_labels"
    assert _fake_client.calls[0]["payload"]["labels"] == ["3", "5", "4"]


@pytest.mark.asyncio
async def test_plot_function_no_points_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.plot_function_2d(
        expression="1/x",
        domain_min=-1,
        domain_max=1,
        y_min=-0.1,
        y_max=0.1,
        samples=50,
    )

    assert result["status"] in {"success", "error"}
    if result["status"] == "error":
        assert result["applied_count"] == 0


@pytest.mark.asyncio
async def test_plot_function_uses_requested_stroke_color_and_adds_label(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.plot_function_2d(
        expression="2*x+1",
        domain_min=-2,
        domain_max=2,
        y_min=-5,
        y_max=5,
        stroke_color="#ff0000",
    )

    assert result["status"] == "success"
    assert result["line_element_ids"]
    assert result["label_element_ids"]
    assert "y = 2x + 1" in result["plot_summary"]

    assert [call["operation"] for call in _fake_client.calls] == ["draw_freehand", "draw_text"]
    assert _fake_client.calls[0]["payload"]["render_mode"] == "polyline"
    assert _fake_client.calls[0]["payload"]["graph_clip"] == {
        "x": 0.1,
        "y": 0.05,
        "width": 0.8,
        "height": 0.45,
    }
    assert _fake_client.calls[0]["payload"]["style"]["stroke_color"] == "#ff0000"
    assert _fake_client.calls[0]["payload"]["style"]["delay_ms"] == 2
    assert _fake_client.calls[1]["payload"]["style"]["stroke_color"] == "#ff0000"
    assert _fake_client.calls[1]["payload"]["style"]["delay_ms"] == 2
    assert _fake_client.calls[1]["payload"]["text"] == "y = 2x + 1"


@pytest.mark.asyncio
async def test_plot_function_uses_default_color_when_none_specified(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    await math_helpers.plot_function_2d(
        expression="x",
        domain_min=-2,
        domain_max=2,
        y_min=-5,
        y_max=5,
    )

    assert _fake_client.calls[0]["payload"]["style"]["stroke_color"] == "#e74c3c"


@pytest.mark.asyncio
async def test_plot_function_reuses_last_axes_grid_viewport(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    tool_context = SimpleNamespace(state={"session_id": "s_test"})

    await math_helpers.draw_axes_grid(
        x=0.2,
        y=0.1,
        width=0.6,
        height=0.4,
        domain_min=0,
        domain_max=6.28,
        y_min=-2,
        y_max=2,
        tool_context=tool_context,
    )
    _fake_client.calls.clear()

    result = await math_helpers.plot_function_2d(
        expression="cos(x)",
        tool_context=tool_context,
    )

    assert result["status"] == "success"
    assert _fake_client.calls[0]["operation"] == "draw_freehand"
    assert _fake_client.calls[0]["payload"]["render_mode"] == "polyline"
    assert _fake_client.calls[0]["payload"]["graph_clip"] == {
        "x": 0.2,
        "y": 0.1,
        "width": 0.6,
        "height": 0.4,
    }
    first_point = _fake_client.calls[0]["payload"]["points"][0]
    last_point = _fake_client.calls[0]["payload"]["points"][-1]
    assert first_point["x"] == pytest.approx(0.2, abs=1e-6)
    assert last_point["x"] == pytest.approx(0.8, abs=1e-3)


@pytest.mark.asyncio
async def test_draw_axes_grid_uses_viewport_command(monkeypatch: pytest.MonkeyPatch, _fake_client: _FakeClient) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.draw_axes_grid(
        x=0.2,
        y=0.15,
        width=0.6,
        height=0.7,
        domain_min=-5,
        domain_max=5,
        y_min=-2,
        y_max=8,
        grid_lines=12,
    )

    assert result["status"] == "success"

    assert len(_fake_client.calls) == 1
    assert _fake_client.calls[0]["operation"] == "set_graph_viewport"
    assert _fake_client.calls[0]["payload"]["grid_lines"] == 12
    assert _fake_client.calls[0]["payload"]["domain_min"] == -5
    assert _fake_client.calls[0]["payload"]["y_max"] == 8


@pytest.mark.asyncio
async def test_draw_axes_grid_normalizes_oversized_auto_dimensions(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.draw_axes_grid(width=400, height=400)

    payload = _fake_client.calls[0]["payload"]
    assert payload["x"] == pytest.approx(0.06, abs=1e-6)
    assert payload["y"] == pytest.approx(0.03, abs=1e-6)
    assert payload["width"] <= 0.88 + 1e-6
    assert payload["height"] <= 2.0 + 1e-6
    assert payload["x"] + payload["width"] <= 1.0 + 1e-6
    assert payload["y"] + payload["height"] <= 2.0 + 1e-6
    assert result["placement_warning"].startswith("Graph width/height were auto-normalized")


@pytest.mark.asyncio
async def test_draw_axes_grid_clamps_manual_viewport_to_canvas(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.draw_axes_grid(x=0.8, y=1.8, width=0.6, height=0.5)

    payload = _fake_client.calls[0]["payload"]
    assert payload["x"] + payload["width"] <= 1.0 + 1e-6
    assert payload["y"] + payload["height"] <= 2.0 + 1e-6
    assert result["placement_warning"].startswith("Graph viewport was clamped")


@pytest.mark.asyncio
async def test_draw_axes_grid_normalizes_oversized_manual_dimensions_before_clamping(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.draw_axes_grid(x=0.5, y=0.4, width=400, height=300)

    payload = _fake_client.calls[0]["payload"]
    assert payload["width"] == pytest.approx(0.4, abs=1e-6)
    assert payload["height"] == pytest.approx(0.3, abs=1e-6)
    assert payload["x"] == pytest.approx(0.5, abs=1e-6)
    assert payload["y"] == pytest.approx(0.4, abs=1e-6)
    assert payload["x"] + payload["width"] <= 1.0 + 1e-6
    assert payload["y"] + payload["height"] <= 2.0 + 1e-6
    assert result["placement_warning"].startswith("Graph width/height were auto-normalized")


@pytest.mark.asyncio
async def test_update_element_points_maps_payload(monkeypatch: pytest.MonkeyPatch, _fake_client: _FakeClient) -> None:
    monkeypatch.setattr(editing, "resolve_session_id", lambda _ctx: "s_test")

    result = await editing.update_element_points(
        element_id="el_123",
        mode="append",
        points=[{"x": 0.3, "y": 0.3}, {"x": 0.4, "y": 0.4}],
    )

    assert result["status"] == "success"

    assert len(_fake_client.calls) == 1
    assert _fake_client.calls[0]["operation"] == "update_points"
    assert _fake_client.calls[0]["payload"]["element_id"] == "el_123"
    assert _fake_client.calls[0]["payload"]["mode"] == "append"


@pytest.mark.asyncio
async def test_number_line_executes_all_subcommands(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    """draw_number_line makes multiple execute_tool_command calls internally."""
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.draw_number_line(
        x=0.1,
        y=0.3,
        width=0.8,
        min_value=-2,
        max_value=2,
    )

    assert result["status"] == "success"

    # 1 base line + 5 ticks + 5 labels = 11 commands
    assert len(_fake_client.calls) == 11
    for call in _fake_client.calls:
        assert call["operation"] in ("draw_shape", "draw_text")


def test_draw_shape_rejects_unsupported_shape() -> None:
    with pytest.raises(ValidationError):
        DrawShapeInput.model_validate(
            {
                "shape": "hexagon",
                "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}],
                "style": {},
            }
        )


def test_draw_shape_rejects_too_many_labels() -> None:
    with pytest.raises(ValidationError):
        DrawShapeInput.model_validate(
            {
                "shape": "triangle",
                "points": [
                    {"x": 0.1, "y": 0.5},
                    {"x": 0.3, "y": 0.2},
                    {"x": 0.5, "y": 0.5},
                    {"x": 0.1, "y": 0.5},
                ],
                "labels": ["a", "b", "c", "d"],
                "style": {},
            }
        )


def test_draw_circle_accepts_center_and_radius_in_schema() -> None:
    data = DrawShapeInput.model_validate(
        {
            "shape": "circle",
            "center": {"x": 0.4, "y": 0.4},
            "radius": 0.08,
            "style": {},
        }
    )

    assert data.center is not None
    assert data.radius == pytest.approx(0.08)


def test_draw_circle_rejects_center_without_radius() -> None:
    with pytest.raises(ValidationError):
        DrawShapeInput.model_validate(
            {
                "shape": "circle",
                "center": {"x": 0.4, "y": 0.4},
                "style": {},
            }
        )


def test_highlight_rejects_unsupported_type() -> None:
    with pytest.raises(ValidationError):
        HighlightInput.model_validate(
            {
                "element_ids": ["el_1"],
                "highlight_type": "outline",
                "padding": 0.01,
                "style": {},
            }
        )


@pytest.mark.asyncio
async def test_draw_text_auto_stacks_vertically(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor")

    first = await core.draw_text(text="Step 1")
    second = await core.draw_text(text="Step 2")
    third = await core.draw_text(text="Step 3")

    assert first["cursor_after"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert first["cursor_after"]["y"] == pytest.approx(0.08, abs=1e-3)
    assert second["cursor_after"]["y"] > first["cursor_after"]["y"]
    assert third["cursor_after"]["y"] > second["cursor_after"]["y"]

    assert _fake_client.calls[0]["payload"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert _fake_client.calls[1]["payload"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert _fake_client.calls[2]["payload"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert _fake_client.calls[1]["payload"]["y"] > _fake_client.calls[0]["payload"]["y"]
    assert _fake_client.calls[2]["payload"]["y"] > _fake_client.calls[1]["payload"]["y"]


@pytest.mark.asyncio
async def test_shape_then_text_auto_placement_avoids_overlap(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor")

    shape_result = await core.draw_shape(shape="right_triangle", width=0.3, height=0.25)
    text_result = await core.draw_text(text="a^2 + b^2 = c^2")

    assert shape_result["element_bbox"]["height"] == pytest.approx(0.25, abs=1e-3)
    assert text_result["element_bbox"]["y"] >= shape_result["element_bbox"]["y"] + shape_result["element_bbox"]["height"]
    assert _fake_client.calls[1]["payload"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert _fake_client.calls[1]["payload"]["y"] >= 0.299


@pytest.mark.asyncio
async def test_shape_auto_size_normalizes_large_dimensions(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor")

    result = await core.draw_shape(shape="right_triangle", width=200, height=200)

    payload = _fake_client.calls[0]["payload"]
    point_xs = [point["x"] for point in payload["points"]]
    point_ys = [point["y"] for point in payload["points"]]
    assert all(0.0 <= x <= 1.0 for x in point_xs)
    assert all(0.0 <= y <= 2.0 for y in point_ys)
    assert result["placement_warning"].startswith("Shape width/height were auto-normalized")


@pytest.mark.asyncio
async def test_side_by_side_then_below_all_resets_to_left_margin(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor")

    await core.draw_shape(shape="right_triangle", width=0.3, height=0.25, next="right")
    await core.draw_text(text="a^2 + b^2 = c^2")
    reset = await core.draw_text(text="9 + 16 = 25", next="below_all")
    await core.draw_text(text="new full width line")

    assert _fake_client.calls[1]["payload"]["x"] == pytest.approx(0.39, abs=1e-3)
    assert _fake_client.calls[2]["payload"]["x"] == pytest.approx(0.39, abs=1e-3)
    assert reset["cursor_after"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert reset["cursor_after"]["y"] >= 0.299
    assert _fake_client.calls[3]["payload"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert _fake_client.calls[3]["payload"]["y"] >= 0.299


@pytest.mark.asyncio
async def test_manual_text_bypass_does_not_move_cursor(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor")

    first = await core.draw_text(text="auto first")
    manual = await core.draw_text(text="annotation", x=0.5, y=0.1)
    second = await core.draw_text(text="auto second")

    assert "cursor_after" in first
    assert "cursor_after" not in manual
    assert _fake_client.calls[1]["payload"]["x"] == pytest.approx(0.5, abs=1e-3)
    assert _fake_client.calls[1]["payload"]["y"] == pytest.approx(0.1, abs=1e-3)
    assert _fake_client.calls[2]["payload"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert _fake_client.calls[2]["payload"]["y"] == pytest.approx(first["cursor_after"]["y"], abs=1e-3)
    assert second["cursor_after"]["y"] > first["cursor_after"]["y"]


@pytest.mark.asyncio
async def test_partial_text_coords_falls_back_to_cursor_mode(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor")

    result = await core.draw_text(text="x = sqrt(25)", x=0.3, y=None)

    assert _fake_client.calls[0]["payload"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert _fake_client.calls[0]["payload"]["y"] == pytest.approx(0.03, abs=1e-3)
    assert "cursor_after" in result
    assert result["placement_warning"].startswith("Partial text coordinates were ignored")


@pytest.mark.asyncio
async def test_manual_shape_points_are_clamped_into_bounds(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor")

    result = await core.draw_shape(
        shape="triangle",
        points=[
            {"x": -5, "y": 200.03},
            {"x": 100.06, "y": -3},
            {"x": 200.06, "y": 200.03},
            {"x": -5, "y": 200.03},
        ],
    )

    payload = _fake_client.calls[0]["payload"]
    point_xs = [point["x"] for point in payload["points"]]
    point_ys = [point["y"] for point in payload["points"]]
    assert all(0.0 <= x <= 1.0 for x in point_xs)
    assert all(0.0 <= y <= 2.0 for y in point_ys)
    assert result["points_warning"].startswith("Some shape points were clamped")


@pytest.mark.asyncio
async def test_clear_canvas_resets_cursor(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor")

    await core.draw_text(text="before clear")
    await core.clear_canvas()
    await core.draw_text(text="after clear")

    assert [call["operation"] for call in _fake_client.calls] == ["draw_text", "clear_canvas", "draw_text"]
    assert _fake_client.calls[2]["payload"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert _fake_client.calls[2]["payload"]["y"] == pytest.approx(0.03, abs=1e-3)


@pytest.mark.asyncio
async def test_axes_grid_auto_placement_uses_cursor(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_cursor")
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor")

    grid_result = await math_helpers.draw_axes_grid(width=0.4, height=0.35)
    await core.draw_text(text="below graph")

    assert _fake_client.calls[0]["operation"] == "set_graph_viewport"
    assert _fake_client.calls[0]["payload"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert _fake_client.calls[0]["payload"]["y"] == pytest.approx(0.03, abs=1e-3)
    assert grid_result["cursor_after"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert grid_result["cursor_after"]["y"] == pytest.approx(0.4, abs=1e-3)
    assert _fake_client.calls[1]["payload"]["y"] == pytest.approx(0.4, abs=1e-3)


@pytest.mark.asyncio
async def test_duplicate_auto_axes_grid_deduplicates_without_advancing_cursor(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_grid_dedup")

    first = await math_helpers.draw_axes_grid(width=0.4, height=0.35)
    second = await math_helpers.draw_axes_grid(width=0.4, height=0.35)

    assert second["deduplicated"] is True
    assert second["cursor_after"] == first["cursor_after"]
    assert len(_fake_client.calls) == 1


@pytest.mark.asyncio
async def test_plot_function_accepts_implicit_multiplication(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.plot_function_2d(
        expression="2x - 4",
        domain_min=-2,
        domain_max=6,
        y_min=-6,
        y_max=8,
    )

    assert result["status"] == "success"
    assert [call["operation"] for call in _fake_client.calls] == ["draw_freehand", "draw_text"]
    assert _fake_client.calls[1]["payload"]["text"] == "y = 2x - 4"


@pytest.mark.asyncio
async def test_plot_function_accepts_caret_exponentiation(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.plot_function_2d(
        expression="x^2 - 4",
        domain_min=-3,
        domain_max=3,
        y_min=-5,
        y_max=6,
    )

    assert result["status"] == "success"
    assert [call["operation"] for call in _fake_client.calls] == ["draw_freehand", "draw_text"]
    assert _fake_client.calls[1]["payload"]["text"] == "y = x^2 - 4"


@pytest.mark.asyncio
async def test_graph_axes_grid_partial_coords_returns_error_not_exception() -> None:
    context = SimpleNamespace(state={"session_id": "s_graph_partial"})

    response = await unified.graph(
        action="axes_grid",
        x=0.5,
        y=None,
        width=400,
        height=400,
        tool_context=context,
    )

    assert response["status"] == "error"
    assert response["graph_summary"].startswith("axes_grid ignored")
    assert response["cursor_after"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert response["cursor_after"]["y"] == pytest.approx(0.03, abs=1e-3)


@pytest.mark.asyncio
async def test_unified_cursor_actions_move_new_line_and_section(_fake_client: _FakeClient) -> None:
    context = SimpleNamespace(state={"session_id": "s_unified"})

    section = await unified.edit_canvas(action="new_section", tool_context=context)
    assert section["cursor_after"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert section["cursor_after"]["y"] > 0.03

    moved = await unified.edit_canvas(action="move_cursor", x=0.4, y=0.3, tool_context=context)
    assert moved["cursor_after"]["x"] == pytest.approx(0.4, abs=1e-3)
    assert moved["cursor_after"]["y"] == pytest.approx(0.3, abs=1e-3)

    await unified.draw(action="text", text="at moved cursor", tool_context=context)
    assert _fake_client.calls[0]["payload"]["x"] == pytest.approx(0.4, abs=1e-3)
    assert _fake_client.calls[0]["payload"]["y"] == pytest.approx(0.3, abs=1e-3)

    line = await unified.edit_canvas(action="new_line", tool_context=context)
    await unified.draw(action="text", text="next line", tool_context=context)
    assert line["cursor_after"]["x"] == pytest.approx(0.4, abs=1e-3)
    assert _fake_client.calls[1]["payload"]["x"] == pytest.approx(0.4, abs=1e-3)
    assert _fake_client.calls[1]["payload"]["y"] > 0.3


@pytest.mark.asyncio
async def test_unified_move_cursor_missing_coords_returns_error_not_exception() -> None:
    context = SimpleNamespace(state={"session_id": "s_unified_missing"})

    response = await unified.edit_canvas(action="move_cursor", x=0.5, y=None, tool_context=context)

    assert response["status"] == "error"
    assert response["edit_summary"].startswith("move_cursor ignored")
    assert response["cursor_after"]["x"] == pytest.approx(0.06, abs=1e-3)
    assert response["cursor_after"]["y"] == pytest.approx(0.03, abs=1e-3)


@pytest.mark.asyncio
async def test_edit_canvas_text_falls_back_to_draw_text(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_test")
    monkeypatch.setattr(unified, "resolve_session_id", lambda _ctx: "s_test")

    result = await unified.edit_canvas(
        action="text",
        text="$34^\\circ$",
        text_format="latex",
    )

    assert result["status"] == "success"
    assert _fake_client.calls[0]["operation"] == "draw_text"
    assert _fake_client.calls[0]["payload"]["text"] == "$34^\\circ$"
    assert _fake_client.calls[0]["payload"]["text_format"] == "latex"


@pytest.mark.asyncio
async def test_canvas_actions_executes_multiple_actions_in_order(_fake_client: _FakeClient) -> None:
    context = SimpleNamespace(state={"session_id": "s_canvas_actions"})

    response = await unified.canvas_actions(
        actions=[
            {"tool": "draw", "action": "text", "text": "First"},
            {"tool": "edit_canvas", "action": "new_line"},
            {"tool": "draw", "action": "text", "text": "Second"},
        ],
        tool_context=context,
    )

    assert response["status"] == "success"
    assert response["completed_actions"] == 3
    assert response["failed_action_index"] is None
    assert response["stopped_early"] is False
    assert [result["operation"] for result in response["results"]] == [
        "draw_text",
        "edit_canvas",
        "draw_text",
    ]
    assert [call["operation"] for call in _fake_client.calls] == [
        "draw_text",
        "draw_text",
    ]
    assert _fake_client.calls[1]["payload"]["y"] > _fake_client.calls[0]["payload"]["y"]


@pytest.mark.asyncio
async def test_canvas_actions_accepts_stringified_action_objects(_fake_client: _FakeClient) -> None:
    context = SimpleNamespace(state={"session_id": "s_canvas_actions_strings"})

    response = await unified.canvas_actions(
        actions=[
            '{"tool":"draw","action":"shape","shape":"right_triangle","labels":["a","b","c"]}',
            '{"tool":"draw","action":"text","text":"a² + b² = c²","next":"below_all"}',
        ],
        tool_context=context,
    )

    assert response["status"] == "success"
    assert response["completed_actions"] == 2
    assert [call["operation"] for call in _fake_client.calls] == [
        "draw_shape",
        "set_shape_labels",
        "draw_text",
    ]


@pytest.mark.asyncio
async def test_canvas_actions_accepts_direct_set_shape_labels_tool_alias(
    _fake_client: _FakeClient,
) -> None:
    context = SimpleNamespace(state={"session_id": "s_canvas_actions_alias"})

    response = await unified.canvas_actions(
        actions=[
            {"tool": "draw", "action": "shape", "shape": "right_triangle"},
            {"tool": "set_shape_labels", "element_id": "el_test_1", "labels": ["3", "4", "5"]},
        ],
        tool_context=context,
    )

    assert response["status"] == "success"
    assert response["completed_actions"] == 2
    assert [result["operation"] for result in response["results"]] == [
        "draw_shape",
        "set_shape_labels",
    ]
    assert [call["operation"] for call in _fake_client.calls] == [
        "draw_shape",
        "set_shape_labels",
    ]


@pytest.mark.asyncio
async def test_canvas_actions_returns_error_for_unsupported_tool_without_raising(
    _fake_client: _FakeClient,
) -> None:
    context = SimpleNamespace(state={"session_id": "s_canvas_actions_bad_tool"})

    response = await unified.canvas_actions(
        actions=[
            {"tool": "draw", "action": "text", "text": "Before error"},
            {"tool": "not_a_real_tool", "foo": "bar"},
            {"tool": "draw", "action": "text", "text": "Should not run"},
        ],
        tool_context=context,
    )

    assert response["status"] == "partial_success"
    assert response["completed_actions"] == 2
    assert response["failed_action_index"] == 1
    assert response["stopped_early"] is True
    assert response["results"][1]["status"] == "error"
    assert "unsupported tool" in response["results"][1]["message"]
    assert len(_fake_client.calls) == 1


@pytest.mark.asyncio
async def test_canvas_actions_stops_on_error_result(_fake_client: _FakeClient) -> None:
    context = SimpleNamespace(state={"session_id": "s_canvas_actions_error"})

    response = await unified.canvas_actions(
        actions=[
            {"tool": "draw", "action": "text", "text": "Before error"},
            {"tool": "edit_canvas", "action": "move_cursor", "x": 0.4},
            {"tool": "draw", "action": "text", "text": "Should not run"},
        ],
        tool_context=context,
    )

    assert response["status"] == "partial_success"
    assert response["completed_actions"] == 2
    assert response["failed_action_index"] == 1
    assert response["stopped_early"] is True
    assert response["results"][1]["status"] == "error"
    assert len(_fake_client.calls) == 1


def test_update_cursor_viewport_sets_dynamic_bottom_edge() -> None:
    state = _cursor_store.update_cursor_viewport(
        "s_cursor_viewport",
        canvas_width_px=1600,
        canvas_height_px=900,
    )
    snapshot = state.to_snapshot_dict()
    # 900/1600 = 0.5625; minus 0.03 padding => ~0.5325
    assert snapshot["bottom_edge"] == pytest.approx(0.5325, abs=1e-3)


@pytest.mark.asyncio
async def test_cursor_wraps_before_bottom_edge(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(core, "resolve_session_id", lambda _ctx: "s_cursor_bottom")
    _cursor_store.update_cursor_viewport(
        "s_cursor_bottom",
        canvas_width_px=1000,
        canvas_height_px=560,
    )

    for idx in range(20):
        result = await core.draw_text(text=f"Line {idx}")
        bbox = result["element_bbox"]
        assert bbox["y"] + bbox["height"] <= 0.53 + 1e-6

    x_values = [call["payload"]["x"] for call in _fake_client.calls]
    assert max(x_values) > 0.06
