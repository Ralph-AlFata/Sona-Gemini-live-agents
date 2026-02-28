"""Sona Agent Orchestrator — FastAPI entry point.

Endpoints:
    GET  /health    → {"status": "ok", "service": "orchestrator"}

Port: 8001 (Phase 2 will add WS /ws/{session_id})
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from config import settings
    from drawing_client import init_drawing_client, get_drawing_client

    logger.info("Orchestrator starting up on port %s", os.environ.get("PORT", "8001"))
    init_drawing_client(settings.drawing_service_url)
    yield
    await get_drawing_client().aclose()
    logger.info("Orchestrator shutting down")


app = FastAPI(title="Sona Orchestrator", version="0.1.0", lifespan=lifespan)

_allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
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
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "orchestrator"}
