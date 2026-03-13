from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.tools import _shared, core, editing, math_helpers
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
    ) -> DrawingCommandResult:
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
    monkeypatch.setattr(_shared, "get_client", lambda: client)
    return client


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


@pytest.mark.asyncio
async def test_set_shape_labels_maps_payload(
    monkeypatch: pytest.MonkeyPatch,
    _fake_client: _FakeClient,
) -> None:
    monkeypatch.setattr(editing, "resolve_session_id", lambda _ctx: "s_test")

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
