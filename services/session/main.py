"""
Sona Session Service — FastAPI application entry point.

Endpoints:
    GET  /health                          → HealthResponse
    POST /sessions                        → Session (201 Created)
    GET  /sessions/{session_id}           → Session (404 if missing)
    POST /sessions/{session_id}/turns     → Session (appended turn)
    POST /sessions/{session_id}/snapshot  → SnapshotUploadResponse
    DELETE /sessions/{session_id}         → 204 No Content

Port: 8003
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import firestore as fs
import storage as st
from models import (
    AppendTurnRequest,
    ConversationTurn,
    HealthResponse,
    Session,
    SessionCreate,
    SnapshotUploadResponse,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Session service starting up...")
    fs.init_firestore_client()
    st.init_storage_client()
    logger.info("Session service ready on port %s", os.environ.get("PORT", "8003"))
    yield
    logger.info("Session service shutting down...")
    await fs.close_firestore_client()
    st.close_storage_client()
    logger.info("Session service shutdown complete")


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Sona Session Service",
    description="CRUD service for Sona tutoring session lifecycle",
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


# ─── Shared helper ────────────────────────────────────────────────────────────

async def _get_session_or_404(session_id: str) -> Session:
    session = await fs.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )
    return session


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health_check() -> HealthResponse:
    """Returns 200 OK when the service is running."""
    return HealthResponse()


# ─── Session CRUD ─────────────────────────────────────────────────────────────

@app.post(
    "/sessions",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
    tags=["sessions"],
)
async def create_session(payload: SessionCreate) -> Session:
    """Create a new Session document in Firestore."""
    try:
        session = await fs.create_session(payload)
    except Exception as exc:
        logger.exception("Failed to create session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create session",
        ) from exc
    return session


@app.get("/sessions/{session_id}", response_model=Session, tags=["sessions"])
async def get_session(session_id: str) -> Session:
    """Fetch a session document. Returns 404 if not found."""
    return await _get_session_or_404(session_id)


@app.post(
    "/sessions/{session_id}/turns",
    response_model=Session,
    status_code=status.HTTP_200_OK,
    tags=["sessions"],
)
async def append_turn(session_id: str, payload: AppendTurnRequest) -> Session:
    """Append a ConversationTurn to the session's turns array. Returns the updated session."""
    await _get_session_or_404(session_id)
    turn = ConversationTurn(role=payload.role, content=payload.content)
    try:
        updated = await fs.append_turn(session_id, turn)
    except Exception as exc:
        logger.exception("Failed to append turn to session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to append turn",
        ) from exc
    return updated


@app.post(
    "/sessions/{session_id}/snapshot",
    response_model=SnapshotUploadResponse,
    status_code=status.HTTP_200_OK,
    tags=["sessions"],
)
async def upload_snapshot(session_id: str, file: UploadFile) -> SnapshotUploadResponse:
    """Upload a PNG canvas snapshot to GCS and update the session's latest_snapshot."""
    await _get_session_or_404(session_id)

    if file.content_type not in ("image/png", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Expected image/png, got {file.content_type!r}",
        )

    png_bytes = await file.read()
    if len(png_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty",
        )
    if len(png_bytes) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Snapshot file exceeds 10 MB limit",
        )

    try:
        snapshot = await st.upload_canvas_snapshot(session_id, png_bytes)
        updated = await fs.update_snapshot_url(session_id, snapshot)
    except Exception as exc:
        logger.exception("Failed to upload snapshot for session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload snapshot",
        ) from exc

    return SnapshotUploadResponse(
        session_id=session_id,
        snapshot=updated.latest_snapshot,  # type: ignore[arg-type]
    )


@app.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["sessions"],
)
async def delete_session(session_id: str) -> Response:
    """Delete a session document. Returns 204 on success, 404 if not found."""
    deleted = await fs.delete_session(session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
