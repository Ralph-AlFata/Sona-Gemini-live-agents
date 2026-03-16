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
from typing import Any, AsyncGenerator, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import httpx
import google.adk as google_adk
from google.adk.agents.live_request_queue import LiveRequest, LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
import google.genai as google_genai
from google.genai import types
import pydantic

from agent.canvas_context import build_canvas_turn_content
from agent.tools._cursor_store import (
    set_cursor as set_cursor_from_snapshot,
    update_cursor_viewport,
)
from agent.tools._execution import fire_and_forget_tool_calls
from agent.tools._trace import draw_trace_span
from agent.tools._auth import auth_token_span
from agent import root_agent
from auth import AuthError, FirebaseTokenVerifier
from config import settings
from session_client import SessionServiceClient

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
UPSTREAM_MAX_BUFFERED_AUDIO_BYTES = 10 * 1024 * 1024
ALLOW_BARGE_IN_INTERRUPT = True


def _truncate_for_log(value: str, limit: int = 120) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def _summarize_content_for_log(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return "empty"

    fragments: list[str] = []
    for part in content.parts:
        function_response = getattr(part, "function_response", None)
        if function_response is not None:
            fragments.append(
                f"function_response:{getattr(function_response, 'name', '?')}"
            )
            continue

        function_call = getattr(part, "function_call", None)
        if function_call is not None:
            fragments.append(f"function_call:{getattr(function_call, 'name', '?')}")
            continue

        text = getattr(part, "text", None)
        if isinstance(text, str) and text.strip():
            fragments.append(f"text:{_truncate_for_log(text.strip())}")
            continue

        inline_data = getattr(part, "inline_data", None)
        if inline_data is not None:
            mime_type = getattr(inline_data, "mime_type", None)
            if isinstance(mime_type, str) and mime_type:
                fragments.append(f"inline:{mime_type}")
                continue

        fragments.append(type(part).__name__)

    return "|".join(fragments[:4])


def _infer_live_request_source(
    request: LiveRequest,
    explicit_source: str | None = None,
) -> str:
    if explicit_source:
        return explicit_source
    if request.close:
        return "queue_close"
    if request.activity_start is not None:
        return "activity_start"
    if request.activity_end is not None:
        return "activity_end"
    if request.blob is not None:
        return "realtime_audio"
    if request.content is not None and request.content.parts:
        for part in request.content.parts:
            if getattr(part, "function_response", None) is not None:
                return "adk_function_response_feedback"
            if getattr(part, "function_call", None) is not None:
                return "function_call_content"
        return "content"
    return "unknown"


def _live_request_field_names() -> tuple[str, ...]:
    model_fields = getattr(LiveRequest, "model_fields", None)
    if isinstance(model_fields, dict):
        return tuple(sorted(model_fields))
    annotations = getattr(LiveRequest, "__annotations__", None)
    if isinstance(annotations, dict):
        return tuple(sorted(annotations))
    return ()


def _live_request_supports_turn_complete() -> bool:
    return "turn_complete" in _live_request_field_names()


def _build_live_request(
    *,
    content: types.Content | None = None,
    blob: types.Blob | None = None,
    activity_start: types.ActivityStart | None = None,
    activity_end: types.ActivityEnd | None = None,
    close: bool = False,
    turn_complete: bool | None = None,
) -> LiveRequest:
    kwargs: dict[str, Any] = {
        "content": content,
        "blob": blob,
        "activity_start": activity_start,
        "activity_end": activity_end,
        "close": close,
    }
    if turn_complete is not None:
        if _live_request_supports_turn_complete():
            kwargs["turn_complete"] = turn_complete
        elif turn_complete is False:
            logger.warning(
                "LIVE_REQUEST_TURN_COMPLETE_UNSUPPORTED fields=%s requested=%s revision=%s",
                ",".join(_live_request_field_names()) or "unknown",
                turn_complete,
                os.getenv("K_REVISION") or "local",
            )
    return LiveRequest(**kwargs)


def _effective_live_request_turn_complete(request: LiveRequest) -> bool | None:
    if request.content is None:
        return None
    value = getattr(request, "turn_complete", None)
    if value is None:
        return True
    return value


def _log_live_request_runtime() -> None:
    logger.info(
        "LIVE_REQUEST_RUNTIME revision=%s adk=%s genai=%s pydantic=%s supports_turn_complete=%s fields=%s",
        os.getenv("K_REVISION") or "local",
        getattr(google_adk, "__version__", "unknown"),
        getattr(google_genai, "__version__", "unknown"),
        getattr(pydantic, "__version__", "unknown"),
        _live_request_supports_turn_complete(),
        ",".join(_live_request_field_names()) or "unknown",
    )


_log_live_request_runtime()


@dataclass(slots=True)
class _LiveRequestMeta:
    sequence: int
    source: str
    summary: str


class InstrumentedLiveRequestQueue(LiveRequestQueue):
    """LiveRequestQueue with enqueue/dequeue logging for hidden ADK traffic."""

    def __init__(self, *, session_id: str, turn_id: int) -> None:
        super().__init__()
        self._session_id = session_id
        self._turn_id = turn_id
        self._sequence = 0
        self._meta_queue: asyncio.Queue[_LiveRequestMeta] = asyncio.Queue()
        self._assistant_output_finalized = False

    def mark_assistant_output_finalized(self) -> None:
        self._assistant_output_finalized = True

    def _should_drop(self, request: LiveRequest, source: str) -> bool:
        if (
            self._assistant_output_finalized
            and source == "adk_function_response_feedback"
        ):
            logger.info(
                "LIVE_QUEUE_DROP session_id=%s turn_id=%s source=%s reason=assistant_output_finalized",
                self._session_id,
                self._turn_id,
                source,
            )
            return True
        return False

    def _enqueue(self, request: LiveRequest, source: str) -> None:
        if self._should_drop(request, source):
            return
        self._log_enqueue(request, source)
        self._queue.put_nowait(request)

    def _log_enqueue(self, request: LiveRequest, source: str) -> None:
        self._sequence += 1
        effective_turn_complete = _effective_live_request_turn_complete(request)
        summary = _summarize_content_for_log(request.content)
        self._meta_queue.put_nowait(
            _LiveRequestMeta(
                sequence=self._sequence,
                source=source,
                summary=summary,
            )
        )
        logger.info(
            "LIVE_QUEUE_ENQUEUE session_id=%s turn_id=%s seq=%s source=%s close=%s has_content=%s has_blob=%s activity_start=%s activity_end=%s turn_complete=%s summary=%s",
            self._session_id,
            self._turn_id,
            self._sequence,
            source,
            request.close,
            request.content is not None,
            request.blob is not None,
            request.activity_start is not None,
            request.activity_end is not None,
            effective_turn_complete,
            summary,
        )

    def close(self, source: str | None = None):
        request = _build_live_request(close=True)
        self._enqueue(request, _infer_live_request_source(request, source))

    def send_content(
        self,
        content: types.Content,
        turn_complete: bool = True,
        source: str | None = None,
    ):
        request = _build_live_request(content=content, turn_complete=turn_complete)
        self._enqueue(request, _infer_live_request_source(request, source))

    def send_realtime(self, blob: types.Blob, source: str | None = None):
        request = _build_live_request(blob=blob)
        self._enqueue(request, _infer_live_request_source(request, source))

    def send_activity_start(self, source: str | None = None):
        request = _build_live_request(activity_start=types.ActivityStart())
        self._enqueue(request, _infer_live_request_source(request, source))

    def send_activity_end(self, source: str | None = None):
        request = _build_live_request(activity_end=types.ActivityEnd())
        self._enqueue(request, _infer_live_request_source(request, source))

    def send(self, req: LiveRequest, source: str | None = None):
        self._enqueue(req, _infer_live_request_source(req, source))

    async def get(self) -> LiveRequest:
        request = await self._queue.get()
        meta = await self._meta_queue.get()
        effective_turn_complete = _effective_live_request_turn_complete(request)
        logger.info(
            "LIVE_QUEUE_DEQUEUE session_id=%s turn_id=%s seq=%s source=%s close=%s has_content=%s has_blob=%s activity_start=%s activity_end=%s turn_complete=%s summary=%s",
            self._session_id,
            self._turn_id,
            meta.sequence,
            meta.source,
            request.close,
            request.content is not None,
            request.blob is not None,
            request.activity_start is not None,
            request.activity_end is not None,
            effective_turn_complete,
            meta.summary,
        )
        return request


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


def _is_turn_complete_event(event_payload: dict[str, Any]) -> bool:
    return event_payload.get("turnComplete") is True


def _has_nonempty_output_transcription(event_payload: dict[str, Any]) -> bool:
    raw_value = event_payload.get("outputTranscription")
    if not isinstance(raw_value, dict):
        return False
    text = raw_value.get("text")
    return isinstance(text, str) and bool(text.strip())


def _has_assistant_speech_output(event_payload: dict[str, Any]) -> bool:
    return _has_audio_output(event_payload) or _has_nonempty_output_transcription(event_payload)


def _should_retry_empty_turn(
    event_payload: dict[str, Any],
    *,
    function_calls: list[str],
    text_parts: list[str],
) -> bool:
    if not _is_turn_complete_event(event_payload):
        return False
    if _has_assistant_speech_output(event_payload):
        return False
    if function_calls or text_parts:
        return False
    raw_value = event_payload.get("outputTranscription")
    if isinstance(raw_value, dict) and raw_value.get("finished") is True:
        text = raw_value.get("text")
        return not (isinstance(text, str) and text.strip())
    return False


@dataclass(slots=True)
class LiveRuntime:
    """Container for ADK runtime objects."""

    runner: Runner
    session_service: InMemorySessionService
    session_client: SessionServiceClient


def build_live_runtime() -> LiveRuntime:
    """Build ADK runtime objects used by Gemini interactions."""
    session_service = InMemorySessionService()
    session_client = SessionServiceClient(base_url=settings.session_service_url)
    runner = Runner(
        app_name=settings.app_name,
        agent=root_agent,
        session_service=session_service,
    )
    return LiveRuntime(
        runner=runner,
        session_service=session_service,
        session_client=session_client,
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


async def _ensure_persisted_session(
    runtime: LiveRuntime,
    user_id: str,
    session_id: str,
    *,
    auth_token: str | None = None,
) -> None:
    """Ensure the Firestore-backed session document exists in the session service."""
    def _hydrate_cursor_from_session(payload: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict):
            return
        raw_cursor_state = payload.get("cursor_state")
        if not isinstance(raw_cursor_state, dict):
            return
        try:
            set_cursor_from_snapshot(session_id, raw_cursor_state)
        except Exception:
            logger.exception(
                "LIVE_CURSOR_HYDRATE_FAILED session_id=%s payload=%s",
                session_id,
                raw_cursor_state,
            )

    existing = await runtime.session_client.get_session(
        session_id,
        auth_token=auth_token,
    )
    if existing is not None:
        _hydrate_cursor_from_session(existing)
        return
    created = await runtime.session_client.create_session(
        session_id=session_id,
        student_id=user_id,
        auth_token=auth_token,
    )
    _hydrate_cursor_from_session(created)


def _extract_finished_transcription(raw_value: Any) -> str | None:
    if not isinstance(raw_value, dict):
        return None
    if raw_value.get("finished") is not True:
        return None
    text = raw_value.get("text")
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    return cleaned if cleaned else None

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    app.state.live_uses_gemini = _configure_gemini_environment()
    live_runtime = build_live_runtime()
    app.state.live_runtime = live_runtime
    app.state.auth_verifier = (
        FirebaseTokenVerifier(
            audience=settings.orchestrator_auth_audience or None,
        )
        if settings.orchestrator_auth_enabled
        else None
    )

    logger.info(
        "Orchestrator service startup complete on port %s (chat_mode=%s, live_enabled=%s, auth_enabled=%s)",
        os.getenv("PORT", "8001"),
        settings.chat_mode,
        app.state.live_uses_gemini,
        settings.orchestrator_auth_enabled,
    )
    yield
    session_client = getattr(live_runtime, "session_client", None)
    if session_client is not None:
        await session_client.close()
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
    auth_token: str | None = None,
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
    effective_user_id = user_id
    bearer_token: str | None = None

    if settings.orchestrator_auth_enabled:
        if not auth_token:
            await websocket.send_json({"error": "Missing auth_token query parameter."})
            await websocket.close(code=1008)
            return
        verifier: FirebaseTokenVerifier | None = getattr(app.state, "auth_verifier", None)
        if verifier is None:
            await websocket.send_json({"error": "Auth verifier not initialized."})
            await websocket.close(code=1011)
            return
        try:
            auth_context = await verifier.verify(auth_token)
        except AuthError as exc:
            await websocket.send_json({"error": str(exc)})
            await websocket.close(code=1008)
            return
        effective_user_id = auth_context.student_id
        bearer_token = auth_token
        if user_id != effective_user_id:
            logger.warning(
                "LIVE_WS_USER_ID_MISMATCH path_user_id=%s token_user_id=%s session_id=%s",
                user_id,
                effective_user_id,
                session_id,
            )

    logger.info(
        "LIVE_WS_CONNECTED user_id=%s session_id=%s auth_enabled=%s",
        effective_user_id,
        session_id,
        settings.orchestrator_auth_enabled,
    )

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

    await _ensure_adk_session(runtime, user_id=effective_user_id, session_id=session_id)
    try:
        await _ensure_persisted_session(
            runtime,
            user_id=effective_user_id,
            session_id=session_id,
            auth_token=bearer_token,
        )
    except Exception:
        logger.exception(
            "LIVE_PERSISTED_SESSION_INIT_FAILED user_id=%s session_id=%s",
            effective_user_id,
            session_id,
        )
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
    persist_lock = asyncio.Lock()
    pending_persist_tasks: set[asyncio.Task[None]] = set()
    persisted_turn_keys: set[tuple[int, Literal["student", "sona"], str]] = set()
    turn_draw_activity: dict[int, dict[str, Any]] = {}
    pending_assistant_transcripts: dict[int, str] = {}
    assistant_speech_started: dict[int, bool] = {}
    turn_audio_replay_chunks: dict[int, list[bytes]] = {}
    empty_turn_retry_sent: dict[int, bool] = {}
    canvas_snapshot_bytes: bytes | None = None

    def _track_persist_task(task: asyncio.Task[None]) -> None:
        pending_persist_tasks.add(task)
        task.add_done_callback(lambda done: pending_persist_tasks.discard(done))

    async def persist_turn(
        *,
        turn_id: int,
        role: Literal["student", "sona"],
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        cleaned = content.strip()
        if not cleaned:
            return

        async with persist_lock:
            dedup_key = (turn_id, role, cleaned)
            if dedup_key in persisted_turn_keys:
                return
            try:
                await runtime.session_client.append_turn(
                    session_id=session_id,
                    role=role,
                    content=cleaned,
                    metadata=metadata,
                    auth_token=bearer_token,
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code == 404:
                    logger.warning(
                        "LIVE_PERSIST_APPEND_MISSING_SESSION session_id=%s role=%s; retrying after create",
                        session_id,
                        role,
                    )
                    try:
                        await _ensure_persisted_session(
                            runtime,
                            user_id=effective_user_id,
                            session_id=session_id,
                            auth_token=bearer_token,
                        )
                        await runtime.session_client.append_turn(
                            session_id=session_id,
                            role=role,
                            content=cleaned,
                            metadata=metadata,
                            auth_token=bearer_token,
                        )
                    except Exception:
                        logger.exception(
                            "LIVE_PERSIST_APPEND_RETRY_FAILED session_id=%s role=%s",
                            session_id,
                            role,
                        )
                        return
                else:
                    logger.warning(
                        "LIVE_PERSIST_APPEND_HTTP_ERROR session_id=%s role=%s status=%s",
                        session_id,
                        role,
                        status_code,
                    )
                    return
            except Exception:
                logger.exception(
                    "LIVE_PERSIST_APPEND_FAILED session_id=%s role=%s",
                    session_id,
                    role,
                )
                return

            persisted_turn_keys.add(dedup_key)

    def _record_draw_trace(turn_id: int, event: dict[str, Any]) -> None:
        activity = turn_draw_activity.setdefault(
            turn_id,
            {
                "draw_command_requests": [],
                "dsl_messages": [],
                "cursor_state": None,
            },
        )
        command_request = event.get("draw_command_request")
        if isinstance(command_request, dict):
            activity["draw_command_requests"].append(command_request)
        dsl_messages = event.get("dsl_messages")
        if isinstance(dsl_messages, list):
            activity["dsl_messages"].extend(
                item for item in dsl_messages if isinstance(item, dict)
            )
        cursor_state = event.get("cursor_state")
        if isinstance(cursor_state, dict):
            activity["cursor_state"] = dict(cursor_state)

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

    async def start_new_turn(
        trigger: str,
    ) -> LiveRequestQueue:
        nonlocal turn_counter, live_request_queue, live_task, canvas_snapshot_bytes
        await stop_current_turn(reason=f"restart_for_{trigger}", wait_for_drain=False)

        turn_counter += 1
        turn_id = turn_counter
        queue = InstrumentedLiveRequestQueue(session_id=session_id, turn_id=turn_id)
        assistant_speech_started[turn_id] = False
        empty_turn_retry_sent[turn_id] = False
        canvas_content = await build_canvas_turn_content(
            session_id,
            settings.drawing_service_url,
            canvas_snapshot_bytes,
            bearer_token,
        )
        if canvas_content is not None:
            queue.send_content(
                canvas_content,
                turn_complete=False,
                source="canvas_context",
            )
            logger.info(
                "LIVE_CANVAS_CONTEXT_SENT session_id=%s turn_id=%s has_snapshot=%s has_description=%s",
                session_id,
                turn_id,
                canvas_snapshot_bytes is not None,
                len(canvas_content.parts) > (1 if canvas_snapshot_bytes else 0),
            )
        canvas_snapshot_bytes = None

        async def downstream_for_turn(active_queue: LiveRequestQueue, active_turn_id: int) -> None:
            nonlocal event_index, live_request_queue, live_task
            try:
                with draw_trace_span(
                    lambda trace_event: _record_draw_trace(active_turn_id, trace_event)
                ), auth_token_span(bearer_token), fire_and_forget_tool_calls(True):
                    async for event in runtime.runner.run_live(
                        user_id=effective_user_id,
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

                        event_json = event.model_dump_json(exclude_none=True, by_alias=True)
                        event_payload = json.loads(event_json)
                        event_payload["serverTurnId"] = active_turn_id
                        user_text = _extract_finished_transcription(
                            event_payload.get("inputTranscription")
                        )
                        if user_text:
                            _track_persist_task(
                                asyncio.create_task(
                                    persist_turn(
                                        turn_id=active_turn_id,
                                        role="student",
                                        content=user_text,
                                    )
                                )
                            )

                        assistant_text = _extract_finished_transcription(
                            event_payload.get("outputTranscription")
                        )
                        if assistant_text:
                            pending_assistant_transcripts[active_turn_id] = assistant_text

                        text_parts = _extract_text_parts(event_payload)
                        if _has_assistant_speech_output(event_payload):
                            assistant_speech_started[active_turn_id] = True

                        if _is_turn_complete_event(event_payload):
                            final_assistant_text = pending_assistant_transcripts.pop(
                                active_turn_id,
                                None,
                            )
                            if final_assistant_text:
                                if active_queue is live_request_queue and isinstance(
                                    active_queue, InstrumentedLiveRequestQueue
                                ):
                                    active_queue.mark_assistant_output_finalized()
                                draw_activity = turn_draw_activity.pop(active_turn_id, None)
                                metadata = (
                                    draw_activity
                                    if draw_activity
                                    and (
                                        draw_activity["draw_command_requests"]
                                        or draw_activity["dsl_messages"]
                                        or isinstance(draw_activity.get("cursor_state"), dict)
                                    )
                                    else None
                                )
                                _track_persist_task(
                                    asyncio.create_task(
                                        persist_turn(
                                            turn_id=active_turn_id,
                                            role="sona",
                                            content=final_assistant_text,
                                            metadata=metadata,
                                        )
                                    )
                                )

                        is_audio_only = _is_audio_only_event(event_payload)
                        if not is_audio_only:
                            logger.info(
                                "LIVE_EVENT session_id=%s turn_id=%s idx=%s t_plus_ms=%s function_calls=%s text_parts=%s interrupted=%s",
                                session_id,
                                active_turn_id,
                                event_index,
                                elapsed_ms,
                                function_calls,
                                text_parts,
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
                            usage = event_payload.get("usageMetadata")
                            if isinstance(usage, dict):
                                prompt_tokens = usage.get("promptTokenCount")
                                total_tokens = usage.get("totalTokenCount")
                                output_tokens = None
                                if isinstance(prompt_tokens, int) and isinstance(total_tokens, int):
                                    output_tokens = total_tokens - prompt_tokens
                                logger.info(
                                    "LIVE_USAGE session_id=%s turn_id=%s idx=%s prompt_tokens=%s total_tokens=%s output_tokens=%s",
                                    session_id,
                                    active_turn_id,
                                    event_index,
                                    prompt_tokens,
                                    total_tokens,
                                    output_tokens,
                                )
                        elif event_index % DOWNSTREAM_AUDIO_EVENT_LOG_EVERY_N_EVENTS == 0:
                            logger.debug(
                                "LIVE_EVENT_AUDIO_SAMPLE session_id=%s turn_id=%s idx=%s t_plus_ms=%s",
                                session_id,
                                active_turn_id,
                                event_index,
                                elapsed_ms,
                            )

                        event_json = json.dumps(event_payload, ensure_ascii=False)
                        logger.debug(f"[SERVER] Event: {event_json}")
                        await websocket.send_text(event_json)
                        if _should_retry_empty_turn(
                            event_payload,
                            function_calls=function_calls,
                            text_parts=text_parts,
                        ) and not empty_turn_retry_sent.get(active_turn_id, False):
                            replay_chunks = turn_audio_replay_chunks.get(active_turn_id) or []
                            if replay_chunks:
                                empty_turn_retry_sent[active_turn_id] = True
                                logger.info(
                                    "LIVE_EMPTY_TURN_RETRY session_id=%s turn_id=%s idx=%s chunks=%s",
                                    session_id,
                                    active_turn_id,
                                    event_index,
                                    len(replay_chunks),
                                )
                                active_queue.send_activity_start(source="empty_turn_retry")
                                for chunk in replay_chunks:
                                    active_queue.send_realtime(
                                        types.Blob(
                                            mime_type="audio/pcm;rate=16000",
                                            data=chunk,
                                        ),
                                        source="empty_turn_retry",
                                    )
                                active_queue.send_activity_end(source="empty_turn_retry")
                                continue
                        if _is_turn_complete_event(event_payload) and assistant_speech_started.get(
                            active_turn_id, False
                        ):
                            logger.info(
                                "LIVE_TURN_COMPLETE_STOP session_id=%s turn_id=%s idx=%s",
                                session_id,
                                active_turn_id,
                                event_index,
                            )
                            active_queue.close()
                            break
                        if _is_turn_complete_event(event_payload):
                            logger.info(
                                "LIVE_TURN_COMPLETE_IGNORED session_id=%s turn_id=%s idx=%s reason=no_assistant_speech_yet",
                                session_id,
                                active_turn_id,
                                event_index,
                            )
            except Exception as exc:
                logger.exception(
                    "LIVE_TURN_DOWNSTREAM_ERROR session_id=%s turn_id=%s: %s",
                    session_id,
                    active_turn_id,
                    exc,
                )
            finally:
                pending_assistant_transcripts.pop(active_turn_id, None)
                assistant_speech_started.pop(active_turn_id, None)
                turn_audio_replay_chunks.pop(active_turn_id, None)
                empty_turn_retry_sent.pop(active_turn_id, None)
                turn_draw_activity.pop(active_turn_id, None)
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
        Audio bytes stream upstream while speaking, and activity_end closes
        the current user turn.
        """
        is_speaking = False
        audio_chunk_count = 0
        active_speaking_turn_id: int | None = None
        active_speaking_audio_bytes = 0

        while True:
            try:
                message = await websocket.receive()
            except RuntimeError as exc:
                if 'disconnect message has been received' in str(exc):
                    logger.info(
                        "LIVE_WS_RECEIVE_AFTER_DISCONNECT user_id=%s session_id=%s",
                        effective_user_id,
                        session_id,
                    )
                    return
                raise

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
                if active_speaking_turn_id is None:
                    continue
                if active_speaking_audio_bytes + len(audio_data) <= UPSTREAM_MAX_BUFFERED_AUDIO_BYTES:
                    active_speaking_audio_bytes += len(audio_data)
                    replay_chunks = turn_audio_replay_chunks.setdefault(active_speaking_turn_id, [])
                    replay_chunks.append(audio_data)
                    queue = live_request_queue
                    if queue is not None:
                        queue.send_realtime(
                            types.Blob(
                                mime_type="audio/pcm;rate=16000",
                                data=audio_data,
                            ),
                            source="browser_audio_stream",
                        )
                elif active_speaking_audio_bytes <= UPSTREAM_MAX_BUFFERED_AUDIO_BYTES:
                    logger.warning(
                        "LIVE_UPSTREAM_AUDIO_BUFFER_LIMIT session_id=%s max_bytes=%s",
                        session_id,
                        UPSTREAM_MAX_BUFFERED_AUDIO_BYTES,
                    )

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
                    trigger = "barge_in_activity_start" if ALLOW_BARGE_IN_INTERRUPT else "activity_start"
                    queue = await start_new_turn(trigger=trigger)
                    is_speaking = True
                    active_speaking_turn_id = getattr(queue, "_turn_id", None)
                    active_speaking_audio_bytes = 0
                    if active_speaking_turn_id is not None:
                        turn_audio_replay_chunks[active_speaking_turn_id] = []
                    queue.send_activity_start(source="browser_activity_start")
                    logger.info("LIVE_ACTIVITY_START session_id=%s", session_id)

                elif msg_type == "activity_end":
                    if not is_speaking:
                        logger.info(
                            "LIVE_ACTIVITY_END_IGNORED session_id=%s reason=not_speaking",
                            session_id,
                        )
                        continue
                    is_speaking = False
                    queue = live_request_queue
                    if queue is None:
                        logger.info(
                            "LIVE_ACTIVITY_END_NO_QUEUE session_id=%s",
                            session_id,
                        )
                        active_speaking_turn_id = None
                        active_speaking_audio_bytes = 0
                        continue
                    raw_snapshot = json_message.get("snapshot")
                    if isinstance(raw_snapshot, dict):
                        raw_snapshot_data = raw_snapshot.get("data")
                        if isinstance(raw_snapshot_data, str) and raw_snapshot_data.strip():
                            try:
                                canvas_snapshot_bytes = base64.b64decode(raw_snapshot_data)
                            except Exception:
                                logger.warning(
                                    "LIVE_CANVAS_SNAPSHOT_INVALID session_id=%s reason=activity_end_decode_failed",
                                    session_id,
                                )
                            else:
                                logger.info(
                                    "CANVAS_SNAPSHOT_RECEIVED session_id=%s size=%d source=activity_end",
                                    session_id,
                                    len(canvas_snapshot_bytes),
                                )
                    queue.send_activity_end(source="browser_activity_end")
                    logger.info(
                        "LIVE_ACTIVITY_AUDIO_STREAM_COMPLETE session_id=%s turn_id=%s bytes=%s",
                        session_id,
                        active_speaking_turn_id,
                        active_speaking_audio_bytes,
                    )
                    active_speaking_turn_id = None
                    active_speaking_audio_bytes = 0
                    logger.info("LIVE_ACTIVITY_END session_id=%s", session_id)

                elif msg_type == "canvas_metrics":
                    width_raw = json_message.get("canvas_width_px")
                    height_raw = json_message.get("canvas_height_px")
                    try:
                        width = float(width_raw)
                        height = float(height_raw)
                    except (TypeError, ValueError):
                        logger.warning(
                            "LIVE_CANVAS_METRICS_INVALID session_id=%s width=%r height=%r",
                            session_id,
                            width_raw,
                            height_raw,
                        )
                        continue
                    try:
                        cursor = update_cursor_viewport(
                            session_id,
                            canvas_width_px=width,
                            canvas_height_px=height,
                        )
                    except ValueError:
                        logger.warning(
                            "LIVE_CANVAS_METRICS_REJECTED session_id=%s width=%s height=%s",
                            session_id,
                            width,
                            height,
                        )
                        continue
                    logger.info(
                        "LIVE_CANVAS_METRICS session_id=%s width_px=%s height_px=%s bottom_edge=%s",
                        session_id,
                        int(width),
                        int(height),
                        cursor.to_snapshot_dict().get("bottom_edge"),
                    )

                elif msg_type == "snapshot":
                    raw_data = json_message.get("data")
                    if not isinstance(raw_data, str) or not raw_data.strip():
                        logger.warning(
                            "LIVE_CANVAS_SNAPSHOT_INVALID session_id=%s reason=missing_data",
                            session_id,
                        )
                        continue
                    try:
                        canvas_snapshot_bytes = base64.b64decode(raw_data)
                    except Exception:
                        logger.warning(
                            "LIVE_CANVAS_SNAPSHOT_INVALID session_id=%s reason=decode_failed",
                            session_id,
                        )
                        continue
                    logger.info(
                        "CANVAS_SNAPSHOT_RECEIVED session_id=%s size=%d",
                        session_id,
                        len(canvas_snapshot_bytes),
                    )

    try:
        await upstream_task()
    except WebSocketDisconnect:
        logger.info(
            "WebSocket client disconnected user_id=%s session_id=%s",
            effective_user_id,
            session_id,
        )
    except Exception as exc:
        logger.exception(
            "Live websocket failed user_id=%s session_id=%s: %s",
            effective_user_id,
            session_id,
            exc,
        )
    finally:
        await stop_current_turn(reason="websocket_closed", wait_for_drain=True)
        if pending_persist_tasks:
            done, pending = await asyncio.wait(pending_persist_tasks, timeout=2.0)
            for task in pending:
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                for task in done:
                    await task
