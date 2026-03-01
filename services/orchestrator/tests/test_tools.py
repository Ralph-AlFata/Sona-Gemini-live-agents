from __future__ import annotations

import pytest

from agent.tools import core, math_helpers


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
    monkeypatch.setattr(core, "get_client", lambda: fake)
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
    monkeypatch.setattr(math_helpers, "get_client", lambda: fake)
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
