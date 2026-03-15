from __future__ import annotations

from google.adk.agents.live_request_queue import LiveRequest
from google.genai import types

import main


async def _drain(queue: main.InstrumentedLiveRequestQueue) -> LiveRequest:
    return await queue.get()


def test_instrumented_queue_preserves_turn_complete_flag() -> None:
    queue = main.InstrumentedLiveRequestQueue(session_id="s1", turn_id=1)
    queue.send_content(
        types.Content(role="user", parts=[types.Part.from_text(text="canvas")]),
        turn_complete=False,
        source="canvas_context",
    )

    request = __import__("asyncio").run(_drain(queue))
    assert request.content is not None
    assert request.turn_complete is False


def test_infer_function_response_feedback_source() -> None:
    response_part = types.Part(
        function_response=types.FunctionResponse(
            id="call-1",
            name="draw",
            response={"status": "success"},
        )
    )
    request = LiveRequest(content=types.Content(role="user", parts=[response_part]))

    source = main._infer_live_request_source(request)
    assert source == "adk_function_response_feedback"


def test_instrumented_queue_drops_function_feedback_after_output_finalized() -> None:
    queue = main.InstrumentedLiveRequestQueue(session_id="s1", turn_id=1)
    queue.mark_assistant_output_finalized()

    queue.send_content(
        types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id="call-1",
                        name="draw",
                        response={"status": "success"},
                    )
                )
            ],
        ),
    )

    assert queue._queue.qsize() == 0


def test_instrumented_queue_allows_normal_content_after_output_finalized() -> None:
    queue = main.InstrumentedLiveRequestQueue(session_id="s1", turn_id=1)
    queue.mark_assistant_output_finalized()

    queue.send_content(
        types.Content(role="user", parts=[types.Part.from_text(text="new user content")]),
        source="content",
    )

    request = __import__("asyncio").run(_drain(queue))
    assert request.content is not None


def test_is_turn_complete_event() -> None:
    assert main._is_turn_complete_event({"turnComplete": True}) is True
    assert main._is_turn_complete_event({"turnComplete": False}) is False
    assert main._is_turn_complete_event({}) is False
