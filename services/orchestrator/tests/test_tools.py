from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.tools import _batch, _shared, core, editing, math_helpers
from agent.tools.models import DrawShapeInput, HighlightInput


@pytest.fixture(autouse=True)
def _clean_batches() -> None:
    """Ensure no stale batch leaks between tests."""
    yield
    # Synchronous cleanup — the batch registry is just a dict.
    _batch._active_batches.pop("s_test", None)


@pytest.mark.asyncio
async def test_draw_shape_maps_payload(monkeypatch: pytest.MonkeyPatch) -> None:
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

    # Verify the command was queued in the batch
    batch = await _batch.pop_batch("s_test")
    assert batch is not None
    commands = await batch.drain()
    assert len(commands) == 1
    assert commands[0]["operation"] == "draw_shape"
    assert commands[0]["payload"]["style"]["stroke_color"] == "#ff0000"
    assert len(commands[0]["payload"]["points"]) == 5
    # Pre-generated element_id should be in the command
    assert commands[0]["element_id"] == result["created_element_ids"][0]


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
async def test_draw_axes_grid_uses_viewport_command(monkeypatch: pytest.MonkeyPatch) -> None:
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

    batch = await _batch.pop_batch("s_test")
    assert batch is not None
    commands = await batch.drain()
    assert len(commands) == 1
    assert commands[0]["operation"] == "set_graph_viewport"
    assert commands[0]["payload"]["grid_lines"] == 12
    assert commands[0]["payload"]["domain_min"] == -5
    assert commands[0]["payload"]["y_max"] == 8


@pytest.mark.asyncio
async def test_update_element_points_maps_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(editing, "resolve_session_id", lambda _ctx: "s_test")

    result = await editing.update_element_points(
        element_id="el_123",
        mode="append",
        points=[{"x": 0.3, "y": 0.3}, {"x": 0.4, "y": 0.4}],
    )

    assert result["status"] == "success"

    batch = await _batch.pop_batch("s_test")
    assert batch is not None
    commands = await batch.drain()
    assert len(commands) == 1
    assert commands[0]["operation"] == "update_points"
    assert commands[0]["payload"]["element_id"] == "el_123"
    assert commands[0]["payload"]["mode"] == "append"
    # Non-creation ops should not have element_id
    assert "element_id" not in commands[0]


@pytest.mark.asyncio
async def test_number_line_batches_all_subcommands(monkeypatch: pytest.MonkeyPatch) -> None:
    """draw_number_line makes multiple execute_tool_command calls internally.
    All should be queued in a single batch."""
    monkeypatch.setattr(math_helpers, "resolve_session_id", lambda _ctx: "s_test")

    result = await math_helpers.draw_number_line(
        x=0.1,
        y=0.3,
        width=0.8,
        min_value=-2,
        max_value=2,
    )

    assert result["status"] == "success"

    batch = await _batch.pop_batch("s_test")
    assert batch is not None
    commands = await batch.drain()
    # 1 base line + 5 ticks + 5 labels = 11 commands
    assert len(commands) == 11
    # All creation ops should have pre-generated element IDs
    for cmd in commands:
        assert cmd["operation"] in ("draw_shape", "draw_text")
        assert "element_id" in cmd
        assert cmd["element_id"].startswith("el_")


def test_draw_shape_rejects_unsupported_shape() -> None:
    with pytest.raises(ValidationError):
        DrawShapeInput.model_validate(
            {
                "shape": "hexagon",
                "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}],
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
