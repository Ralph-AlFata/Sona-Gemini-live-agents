"""Sona orchestrator service entrypoint."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import warnings
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import root_agent
from agent.tools._batch import pop_batch
from agent.tools._shared import get_client
from config import settings

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
UPSTREAM_AUDIO_LOG_EVERY_N_CHUNKS = 25
STOP_TURN_DRAIN_TIMEOUT_SECONDS = 0.75
DOWNSTREAM_AUDIO_EVENT_LOG_EVERY_N_EVENTS = 50


def _sanitize_event_for_log(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"data", "audio", "bytes"} and isinstance(item, str):
                sanitized[key] = f"<omitted:{len(item)} chars>"
            else:
                sanitized[key] = _sanitize_event_for_log(item)
        return sanitized
    if isinstance(value, set):
        return [_sanitize_event_for_log(item) for item in sorted(value, key=lambda x: str(x))]
    if isinstance(value, tuple):
        return [_sanitize_event_for_log(item) for item in value]
    if isinstance(value, list):
        return [_sanitize_event_for_log(item) for item in value]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    return value


def _extract_text_parts(event_payload: dict[str, Any]) -> list[str]:
    content = event_payload.get("content")
    if not isinstance(content, dict):
        return []
    parts = content.get("parts")
    if not isinstance(parts, list):
        return []
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return texts


def _is_audio_only_event(event_payload: dict[str, Any]) -> bool:
    if event_payload.get("outputTranscription") or event_payload.get("inputTranscription"):
        return False
    content = event_payload.get("content")
    if not isinstance(content, dict):
        return False
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        return False
    for part in parts:
        if not isinstance(part, dict):
            return False
        inline_data = part.get("inlineData")
        if not isinstance(inline_data, dict):
            return False
        mime_type = inline_data.get("mimeType")
        if not (isinstance(mime_type, str) and mime_type.startswith("audio/pcm")):
            return False
    return True


def _has_nonempty_output_transcription(event_payload: dict[str, Any]) -> bool:
    output_transcription = event_payload.get("outputTranscription")
    if not isinstance(output_transcription, dict):
        return False
    text = output_transcription.get("text")
    return isinstance(text, str) and bool(text.strip())


def _has_audio_output(event_payload: dict[str, Any]) -> bool:
    content = event_payload.get("content")
    if not isinstance(content, dict):
        return False
    parts = content.get("parts")
    if not isinstance(parts, list):
        return False
    for part in parts:
        if not isinstance(part, dict):
            continue
        inline_data = part.get("inlineData")
        if not isinstance(inline_data, dict):
            continue
        mime_type = inline_data.get("mimeType")
        data = inline_data.get("data")
        if isinstance(mime_type, str) and mime_type.startswith("audio/pcm") and data:
            return True
    return False

@dataclass(slots=True)
class LiveRuntime:
    """Container for ADK runtime objects."""

    runner: Runner
    session_service: InMemorySessionService


def build_live_runtime() -> LiveRuntime:
    """Build ADK runtime objects used by Gemini interactions."""
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=settings.app_name,
        agent=root_agent,
        session_service=session_service,
    )
    return LiveRuntime(
        runner=runner,
        session_service=session_service,
    )


def _configure_gemini_environment() -> bool:
    """Configure Gemini environment variables; return whether Gemini mode is usable."""
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = str(settings.google_genai_use_vertexai).lower()

    if settings.google_genai_use_vertexai:
        has_required = bool(settings.google_cloud_project and settings.google_cloud_location)
        if not has_required:
            if settings.chat_mode == "gemini":
                raise RuntimeError(
                    "GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION are required "
                    "when GOOGLE_GENAI_USE_VERTEXAI=true in chat_mode=gemini"
                )
            return False

        os.environ["GOOGLE_CLOUD_PROJECT"] = settings.google_cloud_project
        os.environ["GOOGLE_CLOUD_LOCATION"] = settings.google_cloud_location
        os.environ.pop("GOOGLE_API_KEY", None)
        return settings.chat_mode != "mock"

    if not settings.google_api_key:
        if settings.chat_mode == "gemini":
            raise RuntimeError(
                "GOOGLE_API_KEY is required when GOOGLE_GENAI_USE_VERTEXAI=false in chat_mode=gemini"
            )
        return False

    os.environ["GOOGLE_API_KEY"] = settings.google_api_key
    return settings.chat_mode != "mock"


def _build_live_run_config(proactivity: bool, affective_dialog: bool) -> RunConfig:
    model_name = str(root_agent.model)
    is_native_audio = "native-audio" in model_name.lower()
    if not is_native_audio and (proactivity or affective_dialog):
        logger.warning(
            "proactivity/affective_dialog are only supported for native audio models "
            "(current model=%s); ignoring these flags",
            model_name,
        )

    return RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig() if is_native_audio else None,
        output_audio_transcription=types.AudioTranscriptionConfig() if is_native_audio else None,
        session_resumption=types.SessionResumptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=True,
            ),
        ),
        proactivity=(
            types.ProactivityConfig(proactive_audio=False)
            if is_native_audio and proactivity
            else None
        ),
        enable_affective_dialog=affective_dialog if is_native_audio and affective_dialog else None,
    )


async def _ensure_adk_session(runtime: LiveRuntime, user_id: str, session_id: str) -> None:
    existing = await runtime.session_service.get_session(
        app_name=settings.app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if existing is not None:
        return

    await runtime.session_service.create_session(
        app_name=settings.app_name,
        user_id=user_id,
        session_id=session_id,
        state={"session_id": session_id},
    )

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    app.state.live_uses_gemini = _configure_gemini_environment()
    app.state.live_runtime = build_live_runtime()

    logger.info(
        "Orchestrator service startup complete on port %s (chat_mode=%s, live_enabled=%s)",
        os.getenv("PORT", "8001"),
        settings.chat_mode,
        app.state.live_uses_gemini,
    )
    yield
    logger.info("Orchestrator service shutdown complete")


app = FastAPI(
    title="Sona Agent Orchestrator",
    description="Gemini Live API bridge and ADK agent runtime",
    version="0.1.0",
    lifespan=lifespan,
)

_allowed_origins: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_extra_origin = os.environ.get("FRONTEND_URL")
if _extra_origin:
    _allowed_origins.append(_extra_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "orchestrator"}


@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
    proactivity: bool = False,
    affective_dialog: bool = False,
) -> None:
    """WebSocket endpoint for bidirectional streaming with ADK.

    Args:
        websocket: The WebSocket connection
        user_id: User identifier
        session_id: Session identifier
        proactivity: Enable proactive audio (native audio models only)
        affective_dialog: Enable affective dialog (native audio models only)
    """
    await websocket.accept()
    logger.info("LIVE_WS_CONNECTED user_id=%s session_id=%s", user_id, session_id)

    if not getattr(app.state, "live_uses_gemini", False):
        await websocket.send_json(
            {
                "error": "Gemini live mode is not enabled for this environment.",
                "session_id": session_id,
            }
        )
        await websocket.close(code=1011)
        return

    runtime: LiveRuntime | None = getattr(app.state, "live_runtime", None)
    if runtime is None:
        await websocket.close(code=1011)
        return

    # TODO: Double check here if the actual runtime is being updated globally, or it's just inside the function and then it's dropping
    await _ensure_adk_session(runtime, user_id=user_id, session_id=session_id)
    run_config = _build_live_run_config(
        proactivity=proactivity,
        affective_dialog=affective_dialog,
    )
    turn_state_lock = asyncio.Lock()
    live_request_queue: LiveRequestQueue | None = None
    live_task: asyncio.Task[None] | None = None
    turn_counter = 0
    stream_start = time.perf_counter()
    event_index = 0

    async def stop_current_turn(reason: str, wait_for_drain: bool = True) -> None:
        nonlocal live_request_queue, live_task
        async with turn_state_lock:
            queue = live_request_queue
            task = live_task
            live_request_queue = None
            live_task = None

        if queue is not None:
            logger.info("LIVE_TURN_STOP session_id=%s reason=%s", session_id, reason)
            queue.close()

        if task is not None and not task.done() and task is not asyncio.current_task():
            if wait_for_drain:
                try:
                    await asyncio.wait_for(task, timeout=STOP_TURN_DRAIN_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    logger.warning(
                        "LIVE_TURN_STOP_TIMEOUT session_id=%s reason=%s timeout_s=%.2f",
                        session_id,
                        reason,
                        STOP_TURN_DRAIN_TIMEOUT_SECONDS,
                    )
                    task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await task
                except Exception:
                    logger.exception(
                        "LIVE_TURN_STOP_AWAIT_ERROR session_id=%s reason=%s",
                        session_id,
                        reason,
                    )
            else:
                task.cancel()

    async def start_new_turn(trigger: str) -> LiveRequestQueue:
        nonlocal turn_counter, live_request_queue, live_task
        await stop_current_turn(reason=f"restart_for_{trigger}", wait_for_drain=False)

        turn_counter += 1
        turn_id = turn_counter
        queue = LiveRequestQueue()

        async def downstream_for_turn(active_queue: LiveRequestQueue, active_turn_id: int) -> None:
            nonlocal event_index, live_request_queue, live_task
            has_spoken_this_turn = False
            saw_tool_call_since_turn_complete = False
            saw_output_since_turn_complete = False
            try:
                async for event in runtime.runner.run_live(
                    user_id=user_id,
                    session_id=session_id,
                    live_request_queue=active_queue,
                    run_config=run_config,
                ):
                    event_index += 1
                    elapsed_ms = int((time.perf_counter() - stream_start) * 1000)
                    function_calls: list[str] = []
                    if hasattr(event, "get_function_calls"):
                        raw_calls = event.get_function_calls()
                        for call in raw_calls:
                            name = getattr(call, "name", None)
                            if isinstance(name, str):
                                function_calls.append(name)

                    event_payload = event.model_dump(exclude_none=True, by_alias=True)
                    if _has_audio_output(event_payload) or _has_nonempty_output_transcription(event_payload):
                        has_spoken_this_turn = True
                    text_parts = _extract_text_parts(event_payload)
                    if function_calls:
                        saw_tool_call_since_turn_complete = True
                    if _has_nonempty_output_transcription(event_payload) or text_parts:
                        saw_output_since_turn_complete = True
                    is_audio_only = _is_audio_only_event(event_payload)
                    if not is_audio_only:
                        logger.info(
                            "LIVE_EVENT session_id=%s turn_id=%s idx=%s t_plus_ms=%s function_calls=%s text_parts=%s turn_complete=%s interrupted=%s",
                            session_id,
                            active_turn_id,
                            event_index,
                            elapsed_ms,
                            function_calls,
                            text_parts,
                            event_payload.get("turnComplete"),
                            event_payload.get("interrupted"),
                        )
                        logger.info(
                            "LIVE_EVENT_RAW session_id=%s turn_id=%s idx=%s payload=%s",
                            session_id,
                            active_turn_id,
                            event_index,
                            json.dumps(
                                _sanitize_event_for_log(event_payload),
                                ensure_ascii=False,
                                default=str,
                            )[:4000],
                        )
                    elif event_index % DOWNSTREAM_AUDIO_EVENT_LOG_EVERY_N_EVENTS == 0:
                        logger.debug(
                            "LIVE_EVENT_AUDIO_SAMPLE session_id=%s turn_id=%s idx=%s t_plus_ms=%s",
                            session_id,
                            active_turn_id,
                            event_index,
                            elapsed_ms,
                        )

                    event_json = event.model_dump_json(exclude_none=True, by_alias=True)
                    logger.debug(f"[SERVER] Event: {event_json}")
                    await websocket.send_text(event_json)

                    if event_payload.get("turnComplete") is True:
                        if not has_spoken_this_turn and not saw_tool_call_since_turn_complete:
                            logger.info(
                                "LIVE_TURN_COMPLETE_DEFER_CLOSE session_id=%s turn_id=%s reason=no_model_output_yet",
                                session_id,
                                active_turn_id,
                            )
                            continue

                        if saw_tool_call_since_turn_complete:
                            logger.info(
                                "LIVE_TURN_COMPLETE_CONTINUE session_id=%s turn_id=%s reason=tool_progress",
                                session_id,
                                active_turn_id,
                            )
                            saw_tool_call_since_turn_complete = False
                            saw_output_since_turn_complete = False
                            continue

                        if saw_output_since_turn_complete:
                            await stop_current_turn(
                                reason="turn_complete_no_tool_progress",
                                wait_for_drain=False,
                            )
                            return

                        # Defensive close: repeated completion packets with no new progress.
                        await stop_current_turn(
                            reason="turn_complete_no_progress",
                            wait_for_drain=False,
                        )
                        return
            except Exception as exc:
                logger.exception(
                    "LIVE_TURN_DOWNSTREAM_ERROR session_id=%s turn_id=%s: %s",
                    session_id,
                    active_turn_id,
                    exc,
                )
            finally:
                # Flush any pending batched draw commands as a single HTTP call.
                batch = await pop_batch(session_id)
                if batch is not None:
                    commands = await batch.drain()
                    if commands:
                        logger.info(
                            "BATCH_FLUSH session_id=%s turn_id=%s commands=%d",
                            session_id,
                            active_turn_id,
                            len(commands),
                        )
                        try:
                            batch_result = await get_client().execute_batch(commands)
                            logger.info(
                                "BATCH_FLUSH_OK session_id=%s turn_id=%s applied=%d created=%d failed=%d emitted=%d",
                                session_id,
                                active_turn_id,
                                batch_result.total_applied,
                                len(batch_result.total_created_element_ids),
                                batch_result.total_failed,
                                batch_result.total_emitted,
                            )
                        except Exception:
                            logger.exception(
                                "BATCH_FLUSH_ERROR session_id=%s turn_id=%s commands=%d",
                                session_id,
                                active_turn_id,
                                len(commands),
                            )

                async with turn_state_lock:
                    if live_request_queue is active_queue:
                        live_request_queue = None
                    if live_task is asyncio.current_task():
                        live_task = None
                logger.info(
                    "LIVE_TURN_DOWNSTREAM_EXIT session_id=%s turn_id=%s",
                    session_id,
                    active_turn_id,
                )

        task = asyncio.create_task(downstream_for_turn(queue, turn_id))
        async with turn_state_lock:
            live_request_queue = queue
            live_task = task

        logger.info(
            "LIVE_TURN_STARTED session_id=%s turn_id=%s trigger=%s",
            session_id,
            turn_id,
            trigger,
        )
        return queue

    async def upstream_task() -> None:
        """Receives messages from WebSocket and sends to the current turn queue.

        Supports manual turn control via JSON control messages:
          {"type": "activity_start"}  — user started speaking
          {"type": "activity_end"}    — user stopped speaking
        Audio bytes are only forwarded while an activity window is open.
        """
        is_speaking = False
        audio_chunk_count = 0

        while True:
            message = await websocket.receive()

            if "bytes" in message:
                if not is_speaking:
                    continue
                audio_data = message["bytes"]
                audio_chunk_count += 1
                if audio_chunk_count % UPSTREAM_AUDIO_LOG_EVERY_N_CHUNKS == 0:
                    logger.debug(
                        "LIVE_UPSTREAM_AUDIO_CHUNK session_id=%s bytes=%s chunk_count=%s",
                        session_id,
                        len(audio_data),
                        audio_chunk_count,
                    )
                audio_blob = types.Blob(
                    mime_type="audio/pcm;rate=16000", data=audio_data
                )
                async with turn_state_lock:
                    queue = live_request_queue
                if queue is not None:
                    queue.send_realtime(audio_blob)

            elif "text" in message:
                raw_text = message.get("text")
                logger.info(
                    "LIVE_UPSTREAM_TEXT session_id=%s raw=%s",
                    session_id,
                    str(raw_text)[:500],
                )
                try:
                    json_message = json.loads(raw_text)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("LIVE_UPSTREAM_TEXT_PARSE_FAILED session_id=%s", session_id)
                    continue

                msg_type = json_message.get("type")

                if msg_type == "activity_start":
                    is_speaking = True
                    queue = await start_new_turn(trigger="activity_start")
                    queue.send_activity_start()
                    logger.info("LIVE_ACTIVITY_START session_id=%s", session_id)

                elif msg_type == "activity_end":
                    is_speaking = False
                    async with turn_state_lock:
                        queue = live_request_queue
                    if queue is not None:
                        queue.send_activity_end()
                    logger.info("LIVE_ACTIVITY_END session_id=%s", session_id)

    try:
        await upstream_task()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected user_id=%s session_id=%s", user_id, session_id)
    except Exception as exc:
        logger.exception(
            "Live websocket failed user_id=%s session_id=%s: %s",
            user_id,
            session_id,
            exc,
        )
    finally:
        await stop_current_turn(reason="websocket_closed", wait_for_drain=True)
