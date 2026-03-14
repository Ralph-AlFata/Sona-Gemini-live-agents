"""
Sona Session Service — FastAPI application entry point.

Endpoints:
    GET  /health                          → HealthResponse
    GET  /sessions                        → list[Session]
    POST /sessions                        → Session (201 Created)
    PATCH /sessions/{session_id}          → Session (renamed)
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
from fastapi import FastAPI, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from auth import get_auth_context, SessionAuthMiddleware
import firestore as fs
import storage as st
from models import (
    AppendTurnRequest,
    ConversationTurn,
    HealthResponse,
    Session,
    SessionCreate,
    SessionElement,
    SessionRename,
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
app.add_middleware(SessionAuthMiddleware)


# ─── Shared helper ────────────────────────────────────────────────────────────

def _request_auth_context(request: Request):
    auth_context = get_auth_context(request)
    auth_enabled = bool(getattr(request.state, "session_auth_enabled", False))
    if auth_enabled and auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return auth_context


def _ensure_session_ownership(session: Session, request: Request) -> None:
    """Restrict session access to the authenticated student when auth is enabled."""
    auth_context = _request_auth_context(request)
    if auth_context is None:
        return
    if session.student_id != auth_context.student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session '{session.session_id}' does not belong to the authenticated user",
        )


async def _get_session_or_404(session_id: str, request: Request) -> Session:
    session = await fs.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )
    _ensure_session_ownership(session, request)
    return session


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health_check() -> HealthResponse:
    """Returns 200 OK when the service is running."""
    return HealthResponse()


# ─── Session CRUD ─────────────────────────────────────────────────────────────

@app.get("/sessions", response_model=list[Session], tags=["sessions"])
async def list_sessions(request: Request, student_id: str | None = None) -> list[Session]:
    """
    List sessions for one student.

    - When auth is enabled, student_id is derived from the bearer token.
    - When auth is disabled, caller must provide `student_id` query parameter.
    """
    auth_context = _request_auth_context(request)
    effective_student_id = (
        auth_context.student_id
        if auth_context is not None
        else (student_id.strip() if isinstance(student_id, str) else None)
    )
    if not effective_student_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="student_id is required when session auth is disabled",
        )
    try:
        return await fs.list_sessions_for_student(effective_student_id)
    except Exception as exc:
        logger.exception("Failed to list sessions for student %s", effective_student_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list sessions",
        ) from exc


@app.post(
    "/sessions",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
    tags=["sessions"],
)
async def create_session(payload: SessionCreate, request: Request) -> Session:
    """Create a new Session document in Firestore."""
    auth_context = _request_auth_context(request)
    if auth_context is not None:
        effective_student_id = auth_context.student_id
    else:
        raw_student_id = payload.student_id.strip() if isinstance(payload.student_id, str) else ""
        if not raw_student_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="student_id is required when session auth is disabled",
            )
        effective_student_id = raw_student_id
    create_payload = payload.model_copy(update={"student_id": effective_student_id})

    try:
        session = await fs.create_session(create_payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to create session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create session",
        ) from exc
    _ensure_session_ownership(session, request)
    return session


@app.patch("/sessions/{session_id}", response_model=Session, tags=["sessions"])
async def rename_session(
    session_id: str,
    payload: SessionRename,
    request: Request,
) -> Session:
    """Rename one session by updating its topic field."""
    await _get_session_or_404(session_id, request=request)
    cleaned_topic = payload.topic.strip()
    if not cleaned_topic:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Session name cannot be empty",
        )
    try:
        return await fs.update_session_topic(session_id, topic=cleaned_topic)
    except Exception as exc:
        logger.exception("Failed to rename session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to rename session",
        ) from exc


@app.get("/sessions/{session_id}", response_model=Session, tags=["sessions"])
async def get_session(session_id: str, request: Request) -> Session:
    """Fetch a session document. Returns 404 if not found."""
    return await _get_session_or_404(session_id, request=request)


@app.get("/sessions/{session_id}/elements", response_model=list[SessionElement], tags=["sessions"])
async def get_session_elements(session_id: str, request: Request) -> list[SessionElement]:
    """List materialized element documents for a session."""
    await _get_session_or_404(session_id, request=request)
    try:
        return await fs.list_session_elements(session_id)
    except Exception as exc:
        logger.exception("Failed to list elements for session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list session elements",
        ) from exc


@app.post(
    "/sessions/{session_id}/turns",
    response_model=Session,
    status_code=status.HTTP_200_OK,
    tags=["sessions"],
)
async def append_turn(session_id: str, payload: AppendTurnRequest, request: Request) -> Session:
    """Append a ConversationTurn to the session's turns array. Returns the updated session."""
    await _get_session_or_404(session_id, request=request)
    turn = ConversationTurn(
        role=payload.role,
        content=payload.content,
        metadata=payload.metadata,
    )
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
async def upload_snapshot(
    session_id: str,
    file: UploadFile,
    request: Request,
) -> SnapshotUploadResponse:
    """Upload a PNG canvas snapshot to GCS and update the session's latest_snapshot."""
    await _get_session_or_404(session_id, request=request)

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
async def delete_session(session_id: str, request: Request) -> Response:
    """Delete a session document. Returns 204 on success, 404 if not found."""
    await _get_session_or_404(session_id, request=request)
    deleted = await fs.delete_session(session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
