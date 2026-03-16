from __future__ import annotations

import pytest

from agent.tools import _shared
from agent.tools._trace import draw_trace_span
from drawing_client import DrawingCommandResult


class _FakeClient:
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
        return DrawingCommandResult(
            session_id=session_id,
            command_id=command_id or "cmd_fallback",
            operation=operation,
            applied_count=1,
            created_element_ids=["el_1"],
            failed_operations=[],
            emitted_count=1,
            dsl_messages=[
                {
                    "id": "msg_1",
                    "type": "element_created",
                    "payload": {"element_id": "el_1"},
                }
            ],
        )


@pytest.mark.asyncio
async def test_execute_tool_command_emits_trace_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_shared, "_client", _FakeClient())
    monkeypatch.setattr(_shared, "_deduplicator", None)

    events: list[dict] = []
    with draw_trace_span(lambda event: events.append(event)):
        await _shared.execute_tool_command(
            session_id="s_trace",
            operation="draw_text",
            payload={"text": "hello", "x": 0.1, "y": 0.1, "font_size": 24, "style": {}},
        )

    assert len(events) == 1
    event = events[0]
    assert event["draw_command_request"]["operation"] == "draw_text"
    assert event["draw_command_request"]["session_id"] == "s_trace"
    assert event["dsl_messages"][0]["type"] == "element_created"


@pytest.mark.asyncio
async def test_execute_tool_command_dedup_hit_does_not_emit_trace_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_shared, "_client", _FakeClient())
    monkeypatch.setattr(_shared, "_deduplicator", None)

    events: list[dict] = []
    with draw_trace_span(lambda event: events.append(event)):
        await _shared.execute_tool_command(
            session_id="s_trace",
            operation="draw_text",
            payload={"text": "hello", "x": 0.1, "y": 0.1, "font_size": 24, "style": {}},
        )
        dedup_result = await _shared.execute_tool_command(
            session_id="s_trace",
            operation="draw_text",
            payload={"text": "hello", "x": 0.1, "y": 0.1, "font_size": 24, "style": {}},
        )

    assert dedup_result.deduplicated is True
    assert len(events) == 1
