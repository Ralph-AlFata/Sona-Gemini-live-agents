"""Sona orchestrator service entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.run_config import RunConfig
from google.adk.events.event import Event
from google.adk.runners import LiveRequestQueue, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from pydantic import BaseModel, Field

from agent import root_agent
from config import settings

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


class ChatResponse(BaseModel):
    session_id: str
    user_text: str
    assistant_text: str
    tool_calls: list[str]


@dataclass(slots=True)
class LiveRuntime:
    """Container for ADK runtime objects."""

    runner: Runner
    session_service: InMemorySessionService
    live_run_config: RunConfig
    chat_run_config: RunConfig
    live_request_queue: LiveRequestQueue


def build_live_runtime() -> LiveRuntime:
    """Build ADK runtime objects used by Gemini interactions."""
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=settings.app_name,
        agent=root_agent,
        session_service=session_service,
    )
    live_run_config = RunConfig(response_modalities=["AUDIO"])
    chat_run_config = RunConfig(response_modalities=["TEXT"])
    live_request_queue = LiveRequestQueue()
    return LiveRuntime(
        runner=runner,
        session_service=session_service,
        live_run_config=live_run_config,
        chat_run_config=chat_run_config,
        live_request_queue=live_request_queue,
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


def _extract_text_from_event(event: Event) -> str:
    content = event.content
    if content is None or not content.parts:
        return ""

    chunks: list[str] = []
    for part in content.parts:
        if part.text:
            text = part.text.strip()
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


async def _ensure_adk_session(runtime: LiveRuntime, session_id: str) -> None:
    existing = await runtime.session_service.get_session(
        app_name=settings.app_name,
        user_id=settings.default_user_id,
        session_id=session_id,
    )
    if existing is not None:
        return

    await runtime.session_service.create_session(
        app_name=settings.app_name,
        user_id=settings.default_user_id,
        session_id=session_id,
        state={"session_id": session_id},
    )


def _mock_chat_response(session_id: str, text: str) -> ChatResponse:
    lowered = text.lower()
    tool_calls: list[str] = []

    if "clear" in lowered:
        tool_calls.append("clear_canvas")
    if any(token in lowered for token in ("draw", "graph", "plot", "shape", "equation", "line")):
        tool_calls.append("draw_text")

    return ChatResponse(
        session_id=session_id,
        user_text=text,
        assistant_text=(
            "Mock mode response. Backend chat wiring is active; "
            "switch chat_mode=gemini with valid credentials for real model output."
        ),
        tool_calls=tool_calls,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    app.state.chat_uses_gemini = _configure_gemini_environment()
    app.state.live_runtime = build_live_runtime()

    logger.info(
        "Orchestrator service startup complete on port %s (chat_mode=%s, gemini_enabled=%s)",
        os.getenv("PORT", "8001"),
        settings.chat_mode,
        app.state.chat_uses_gemini,
    )
    yield
    app.state.live_runtime.live_request_queue.close()
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


@app.post("/chat/{session_id}", response_model=ChatResponse, tags=["chat"])
async def chat(session_id: str, body: ChatRequest) -> ChatResponse:
    user_text = body.text.strip()
    if not user_text:
        raise HTTPException(status_code=422, detail="text must not be empty")

    if not getattr(app.state, "chat_uses_gemini", False):
        return _mock_chat_response(session_id=session_id, text=user_text)

    runtime: LiveRuntime | None = getattr(app.state, "live_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=500, detail="runtime is not initialized")

    await _ensure_adk_session(runtime, session_id)

    assistant_fragments: list[str] = []
    tool_calls: list[str] = []

    try:
        async for event in runtime.runner.run_async(
            user_id=settings.default_user_id,
            session_id=session_id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=user_text)],
            ),
            run_config=runtime.chat_run_config,
        ):
            for func_call in event.get_function_calls():
                if func_call.name:
                    tool_calls.append(str(func_call.name))

            text = _extract_text_from_event(event)
            if text:
                assistant_fragments.append(text)

    except Exception as exc:
        logger.exception("Chat request failed for session_id=%s", session_id)
        raise HTTPException(status_code=500, detail=f"chat execution failed: {exc}") from exc

    assistant_text = "\n".join(assistant_fragments).strip()
    if not assistant_text:
        assistant_text = "I processed your request but did not generate text output."

    return ChatResponse(
        session_id=session_id,
        user_text=user_text,
        assistant_text=assistant_text,
        tool_calls=_dedupe_keep_order(tool_calls),
    )
