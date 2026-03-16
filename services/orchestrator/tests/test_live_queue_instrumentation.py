from __future__ import annotations

from types import SimpleNamespace

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


def test_effective_turn_complete_defaults_true_when_attribute_missing() -> None:
    request = SimpleNamespace(
        content=types.Content(role="user", parts=[types.Part.from_text(text="canvas")]),
        blob=None,
        activity_start=None,
        activity_end=None,
        close=False,
    )

    assert main._effective_live_request_turn_complete(request) is True


def test_log_enqueue_handles_live_request_without_turn_complete_attribute() -> None:
    queue = main.InstrumentedLiveRequestQueue(session_id="s1", turn_id=1)
    request = SimpleNamespace(
        content=types.Content(role="user", parts=[types.Part.from_text(text="canvas")]),
        blob=None,
        activity_start=None,
        activity_end=None,
        close=False,
    )

    queue._log_enqueue(request, "content")  # type: ignore[arg-type]

    assert queue._meta_queue.qsize() == 1


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


def test_has_assistant_speech_output_with_transcription() -> None:
    assert (
        main._has_assistant_speech_output(
            {"outputTranscription": {"text": "hello", "finished": False}}
        )
        is True
    )


def test_has_assistant_speech_output_with_audio_only_payload() -> None:
    assert (
        main._has_assistant_speech_output(
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "audio/pcm;rate=24000",
                                "data": "AQID",
                            }
                        }
                    ]
                }
            }
        )
        is True
    )


def test_has_assistant_speech_output_ignores_text_parts_only() -> None:
    assert (
        main._has_assistant_speech_output(
            {"content": {"parts": [{"text": "tool summary"}]}}
        )
        is False
    )


def test_should_retry_empty_turn_for_finished_empty_transcription() -> None:
    assert (
        main._should_retry_empty_turn(
            {
                "turnComplete": True,
                "outputTranscription": {"text": "", "finished": True},
            },
            function_calls=[],
            text_parts=[],
        )
        is True
    )


def test_should_not_retry_turn_with_function_calls() -> None:
    assert (
        main._should_retry_empty_turn(
            {
                "turnComplete": True,
                "outputTranscription": {"text": "", "finished": True},
            },
            function_calls=["canvas_actions"],
            text_parts=[],
        )
        is False
    )
