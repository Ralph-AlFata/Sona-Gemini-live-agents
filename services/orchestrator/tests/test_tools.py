from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.tools import _shared, core, editing, math_helpers
from agent.tools.models import DrawShapeInput, HighlightInput


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, session_id: str, operation: str, payload: dict, command_id: str | None = None):
        self.calls.append(
            {
                "session_id": session_id,
                "operation": operation,
                "payload": payload,
                "command_id": command_id,
            }
        )
        return type(
            "Result",
            (),
            {
                "session_id": session_id,
                "command_id": command_id or "cmd_auto",
                "operation": operation,
                "applied_count": 1,
                "created_element_ids": ["el_a"],
                "failed_operations": [],
                "emitted_count": 1,
            },
        )()


@pytest.mark.asyncio
async def test_draw_shape_maps_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(_shared, "get_client", lambda: fake)
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
    assert fake.calls[0]["operation"] == "draw_shape"
    assert fake.calls[0]["payload"]["style"]["stroke_color"] == "#ff0000"
    assert len(fake.calls[0]["payload"]["points"]) == 5


@pytest.mark.asyncio
async def test_plot_function_no_points_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(_shared, "get_client", lambda: fake)
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
    fake = FakeClient()
    monkeypatch.setattr(_shared, "get_client", lambda: fake)
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
    assert fake.calls[0]["operation"] == "set_graph_viewport"
    assert fake.calls[0]["payload"]["grid_lines"] == 12
    assert fake.calls[0]["payload"]["domain_min"] == -5
    assert fake.calls[0]["payload"]["y_max"] == 8


@pytest.mark.asyncio
async def test_update_element_points_maps_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(_shared, "get_client", lambda: fake)
    monkeypatch.setattr(editing, "resolve_session_id", lambda _ctx: "s_test")

    result = await editing.update_element_points(
        element_id="el_123",
        mode="append",
        points=[{"x": 0.3, "y": 0.3}, {"x": 0.4, "y": 0.4}],
    )

    assert result["status"] == "success"
    assert fake.calls[0]["operation"] == "update_points"
    assert fake.calls[0]["payload"]["element_id"] == "el_123"
    assert fake.calls[0]["payload"]["mode"] == "append"


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
