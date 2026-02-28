"""Sona orchestrator service entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.run_config import RunConfig
from google.adk.runners import LiveRequestQueue, Runner
from google.adk.sessions import InMemorySessionService

from agent import root_agent
from config import settings

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LiveRuntime:
    """Container for ADK Live runtime objects."""

    runner: Runner
    session_service: InMemorySessionService
    run_config: RunConfig
    live_request_queue: LiveRequestQueue


def build_live_runtime() -> LiveRuntime:
    """Build ADK runtime objects used by Gemini Live streaming flows."""
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=settings.app_name,
        agent=root_agent,
        session_service=session_service,
    )
    run_config = RunConfig(response_modalities=["AUDIO"])
    live_request_queue = LiveRequestQueue()
    return LiveRuntime(
        runner=runner,
        session_service=session_service,
        run_config=run_config,
        live_request_queue=live_request_queue,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = str(settings.google_genai_use_vertexai).lower()

    if settings.google_genai_use_vertexai:
        if not settings.google_cloud_project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required when GOOGLE_GENAI_USE_VERTEXAI=true")
        if not settings.google_cloud_location:
            raise RuntimeError("GOOGLE_CLOUD_LOCATION is required when GOOGLE_GENAI_USE_VERTEXAI=true")
        os.environ["GOOGLE_CLOUD_PROJECT"] = settings.google_cloud_project
        os.environ["GOOGLE_CLOUD_LOCATION"] = settings.google_cloud_location
        os.environ.pop("GOOGLE_API_KEY", None)
    else:
        if not settings.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is required when GOOGLE_GENAI_USE_VERTEXAI=false")
        os.environ["GOOGLE_API_KEY"] = settings.google_api_key

    app.state.live_runtime = build_live_runtime()
    logger.info("Orchestrator service startup complete on port %s", os.getenv("PORT", "8001"))
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
