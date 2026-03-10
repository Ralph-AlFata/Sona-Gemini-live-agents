"""Sona orchestrator service entrypoint."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import warnings
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import root_agent
from config import settings

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

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
    live_request_queue = LiveRequestQueue()
    run_config = _build_live_run_config(
        proactivity=proactivity,
        affective_dialog=affective_dialog,
    )

    async def upstream_task() -> None:
        """Receives messages from WebSocket and sends to LiveRequestQueue.

        Supports manual turn control via JSON control messages:
          {"type": "activity_start"}  — user started speaking
          {"type": "activity_end"}    — user stopped speaking
        Audio bytes are only forwarded while an activity window is open.
        """
        is_speaking = False

        while True:
            message = await websocket.receive()

            if "bytes" in message:
                if not is_speaking:
                    continue
                audio_data = message["bytes"]
                audio_blob = types.Blob(
                    mime_type="audio/pcm;rate=16000", data=audio_data
                )
                live_request_queue.send_realtime(audio_blob)

            elif "text" in message:
                try:
                    json_message = json.loads(message["text"])
                except (json.JSONDecodeError, TypeError):
                    continue

                msg_type = json_message.get("type")

                if msg_type == "activity_start":
                    is_speaking = True
                    live_request_queue.send_activity_start()
                    logger.debug("Activity start signalled")

                elif msg_type == "activity_end":
                    is_speaking = False
                    live_request_queue.send_activity_end()
                    logger.debug("Activity end signalled")
        

    async def downstream_task() -> None:
        async for event in runtime.runner.run_live(
            user_id=user_id,
            session_id=session_id,
            live_request_queue=live_request_queue,
            run_config=run_config,
        ):
            event_json = event.model_dump_json(exclude_none=True, by_alias=True)
            logger.debug(f"[SERVER] Event: {event_json}")
            await websocket.send_text(event_json)

    try:
        await asyncio.gather(upstream_task(), downstream_task())
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
        live_request_queue.close()
