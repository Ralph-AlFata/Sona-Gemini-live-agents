from __future__ import annotations

import pytest
from google.genai import types

from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.models.gemini_llm_connection import GeminiLlmConnection


@pytest.mark.asyncio
async def test_live_request_queue_preserves_turn_complete_flag() -> None:
    queue = LiveRequestQueue()
    queue.send_content(
        types.Content(role="user", parts=[types.Part.from_text(text="canvas")]),
        turn_complete=False,
    )

    request = await queue.get()
    assert request.content is not None
    assert request.turn_complete is False


class _FakeSession:
    def __init__(self) -> None:
        self.inputs: list[object] = []

    async def send(self, *, input: object) -> None:  # type: ignore[override]
        self.inputs.append(input)


@pytest.mark.asyncio
async def test_gemini_connection_send_content_honors_turn_complete_flag() -> None:
    session = _FakeSession()
    connection = GeminiLlmConnection(session)  # type: ignore[arg-type]

    await connection.send_content(
        types.Content(role="user", parts=[types.Part.from_text(text="canvas")]),
        turn_complete=False,
    )

    assert len(session.inputs) == 1
    payload = session.inputs[0]
    assert isinstance(payload, types.LiveClientContent)
    assert payload.turn_complete is False
