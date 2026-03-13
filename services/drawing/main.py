"""Sona Drawing Command Service — FastAPI entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
import httpx

from auth import AuthError, FirebaseTokenVerifier, extract_bearer_token
from config import settings
from dsl import apply_command, element_to_frontend_payload
from models import (
    ClearPayload,
    ClearRequest,
    DSLMessage,
    DrawCommandRequest,
    DrawResponse,
    HealthResponse,
    SessionElementSnapshot,
    SessionStateResponse,
)
from store import ElementStore, InMemoryElementStore, StoredElement

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks WebSocket subscribers by session and broadcasts JSON DSL messages."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(session_id, set()).add(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        subscribers = self._connections.get(session_id)
        if subscribers is None:
            return
        subscribers.discard(websocket)
        if not subscribers:
            self._connections.pop(session_id, None)

    async def broadcast(self, session_id: str, message: dict[str, Any]) -> int:
        subscribers = self._connections.get(session_id)
        if not subscribers:
            return 0

        dead: list[WebSocket] = []
        for socket in subscribers:
            try:
                await socket.send_json(message)
            except Exception:
                dead.append(socket)

        for socket in dead:
            self.disconnect(session_id, socket)

        return len(subscribers) - len(dead)


manager = ConnectionManager()

# Module-level store; replaced with FirestoreElementStore in lifespan when USE_FIRESTORE=true.
_store: ElementStore = InMemoryElementStore()
_session_auth_client: httpx.AsyncClient | None = None
_token_verifier: FirebaseTokenVerifier | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _store, _session_auth_client, _token_verifier

    if settings.use_firestore:
        from firestore_store import FirestoreElementStore, close_firestore_client, init_firestore_client
        init_firestore_client()
        _store = FirestoreElementStore()
        logger.info("Drawing service using Firestore element store")
    else:
        logger.info("Drawing service using in-memory element store")

    _session_auth_client = httpx.AsyncClient(
        base_url=settings.session_service_url,
        timeout=10.0,
    )
    if settings.drawing_auth_enabled:
        _token_verifier = FirebaseTokenVerifier(
            audience=settings.drawing_auth_audience or None,
        )

    logger.info("Drawing service starting up on port %s", settings.port)
    yield

    if settings.use_firestore:
        from firestore_store import close_firestore_client
        await close_firestore_client()

    if _session_auth_client is not None:
        await _session_auth_client.aclose()
        _session_auth_client = None
    _token_verifier = None

    logger.info("Drawing service shutting down")


app = FastAPI(
    title="Sona Drawing Command Service",
    description="Applies draw commands and broadcasts reconciliation DSL messages",
    version="0.2.0",
    lifespan=lifespan,
)

_allowed_origins: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if settings.frontend_url:
    _allowed_origins.append(settings.frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health_check() -> HealthResponse:
    return HealthResponse()


@app.get(
    "/sessions/{session_id}/state",
    response_model=SessionStateResponse,
    tags=["drawing"],
)
async def get_session_state(session_id: str, request: Request) -> SessionStateResponse:
    """
    Return a session's current canvas state as synthetic `element_created` DSL messages.

    Frontend can replay these messages to hydrate whiteboard state after switching sessions
    without re-running model tools.
    """
    bearer_token: str | None = None
    if settings.drawing_auth_enabled:
        token = extract_bearer_token(request.headers.get("authorization"))
        await _authorize_session_access(session_id, token)
        bearer_token = token

    snapshots = await _build_session_element_snapshots(
        session_id=session_id,
        bearer_token=bearer_token,
    )
    dsl_messages: list[DSLMessage] = []
    for item in snapshots:
        dsl_messages.append(
            DSLMessage(
                id=uuid4().hex[:8],
                command_id="state_sync",
                session_id=session_id,
                type="element_created",
                payload={
                    "element_id": item.element_id,
                    "element_type": item.element_type,
                    "payload": item.payload,
                },
            )
        )

    return SessionStateResponse(
        session_id=session_id,
        element_count=len(dsl_messages),
        dsl_messages=dsl_messages,
    )


@app.get(
    "/sessions/{session_id}/elements",
    response_model=list[SessionElementSnapshot],
    tags=["drawing"],
)
async def get_session_elements(session_id: str, request: Request) -> list[SessionElementSnapshot]:
    """
    Return direct element snapshots for frontend hydration.

    This is preferred over synthetic DSL replay when loading an existing session.
    """
    bearer_token: str | None = None
    if settings.drawing_auth_enabled:
        token = extract_bearer_token(request.headers.get("authorization"))
        await _authorize_session_access(session_id, token)
        bearer_token = token
    return await _build_session_element_snapshots(
        session_id=session_id,
        bearer_token=bearer_token,
    )


async def _build_session_element_snapshots(
    *,
    session_id: str,
    bearer_token: str | None,
) -> list[SessionElementSnapshot]:
    snapshots: list[SessionElementSnapshot] = []
    session_elements = await _store.get_all_elements(session_id)
    ordered_elements = sorted(
        session_elements.values(),
        key=_element_replay_sort_key,
    )
    for element in ordered_elements:
        snapshots.append(
            SessionElementSnapshot(
                session_id=session_id,
                element_id=element.element_id,
                element_type=element.element_type,
                payload=element_to_frontend_payload(element),
            )
        )

    if snapshots:
        return snapshots

    legacy_elements = await _load_legacy_session_elements(session_id, bearer_token)
    for row in legacy_elements:
        element_id_raw = row.get("element_id")
        element_type_raw = row.get("element_type")
        payload_raw = row.get("payload")
        if (
            not isinstance(element_id_raw, str)
            or not element_id_raw
            or not isinstance(element_type_raw, str)
            or not element_type_raw
            or not isinstance(payload_raw, dict)
        ):
            continue
        snapshots.append(
            SessionElementSnapshot(
                session_id=session_id,
                element_id=element_id_raw,
                element_type=element_type_raw,
                payload=_normalize_fallback_payload(payload_raw),
            )
        )
    return snapshots


def _element_replay_sort_key(element: StoredElement) -> tuple[int, str, str]:
    """
    Deterministic replay order for state hydration.

    Sort by z-index first, then creation timestamp (if present), then element_id.
    """
    payload = element.payload if isinstance(element.payload, dict) else {}
    style_raw = payload.get("style")
    style = style_raw if isinstance(style_raw, dict) else {}
    z_raw = payload.get("z_index", style.get("z_index", 0))
    try:
        z_index = int(z_raw)
    except Exception:
        z_index = 0
    created_at_raw = payload.get("created_at")
    created_at = created_at_raw if isinstance(created_at_raw, str) else ""
    return (z_index, created_at, element.element_id)


async def _authorize_session_access(session_id: str, bearer_token: str) -> None:
    if not settings.drawing_auth_enabled:
        return
    verifier = _token_verifier
    session_client = _session_auth_client
    if verifier is None or session_client is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Drawing auth is enabled but auth runtime is not initialized",
        )

    try:
        await verifier.verify(bearer_token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    response = await session_client.get(
        f"/sessions/{session_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    if response.status_code == status.HTTP_200_OK:
        return
    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )
    if response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session access denied for authenticated user",
        )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to validate session access",
    )


def _normalize_fallback_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy/session-service element payload shape for frontend replay."""
    normalized = dict(payload)
    style_raw = normalized.pop("style", None)
    style = style_raw if isinstance(style_raw, dict) else {}

    if "color" not in normalized:
        normalized["color"] = style.get("stroke_color", "#111111")
    if "stroke_width" not in normalized:
        normalized["stroke_width"] = style.get("stroke_width", 2.0)
    if "fill_color" not in normalized:
        normalized["fill_color"] = style.get("fill_color")
    if "opacity" not in normalized:
        normalized["opacity"] = style.get("opacity", 1.0)
    if "z_index" not in normalized:
        normalized["z_index"] = style.get("z_index", 0)
    if "delay_ms" not in normalized:
        normalized["delay_ms"] = style.get("delay_ms", 0)
    if "animate" not in normalized:
        normalized["animate"] = bool(style.get("animate", False))
    return normalized


async def _load_legacy_session_elements(
    session_id: str,
    bearer_token: str | None,
) -> list[dict[str, Any]]:
    """Fetch materialized session elements from session service for backward compatibility."""
    session_client = _session_auth_client
    if session_client is None:
        return []
    headers = (
        {"Authorization": f"Bearer {bearer_token}"}
        if isinstance(bearer_token, str) and bearer_token
        else None
    )
    try:
        response = await session_client.get(f"/sessions/{session_id}/elements", headers=headers)
    except httpx.HTTPError:
        logger.warning(
            "Legacy session element fetch failed for session %s",
            session_id,
            exc_info=True,
        )
        return []
    if response.status_code == status.HTTP_404_NOT_FOUND:
        return []
    if response.status_code == status.HTTP_200_OK:
        body = response.json()
        if isinstance(body, list):
            return [item for item in body if isinstance(item, dict)]
        return []
    if response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ):
        if not bearer_token:
            logger.warning(
                "Legacy session elements unavailable for session %s: session service requires auth",
                session_id,
            )
            return []
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session access denied for authenticated user",
        )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to load legacy session elements",
    )


@app.websocket("/ws/{session_id}")
async def websocket_session(
    session_id: str,
    websocket: WebSocket,
    auth_token: str | None = None,
) -> None:
    if settings.drawing_auth_enabled:
        if not auth_token:
            await websocket.close(code=1008, reason="Missing auth_token query parameter")
            return
        try:
            await _authorize_session_access(session_id, auth_token)
        except HTTPException as exc:
            await websocket.close(code=1008, reason=str(exc.detail))
            return

    await manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)


@app.post(
    "/draw",
    response_model=DrawResponse,
    status_code=status.HTTP_200_OK,
    tags=["drawing"],
)
async def draw(body: DrawCommandRequest, request: Request) -> DrawResponse:
    if settings.drawing_auth_enabled:
        token = extract_bearer_token(request.headers.get("authorization"))
        await _authorize_session_access(body.session_id, token)
    messages, response = await apply_command(body, _store)

    delivered = 0
    for message in messages:
        delivered += await manager.broadcast(body.session_id, message.model_dump(mode="json"))

    logger.info(
        "Draw accepted: session_id=%s operation=%s emitted=%d delivered=%d",
        body.session_id,
        body.operation,
        len(messages),
        delivered,
    )
    return response

@app.post(
    "/draw/clear",
    response_model=DrawResponse,
    status_code=status.HTTP_200_OK,
    tags=["drawing"],
)
async def clear_canvas(body: ClearRequest, request: Request) -> DrawResponse:
    if settings.drawing_auth_enabled:
        token = extract_bearer_token(request.headers.get("authorization"))
        await _authorize_session_access(body.session_id, token)
    draw_request = DrawCommandRequest(
        session_id=body.session_id,
        operation="clear_canvas",
        payload=ClearPayload(),
    )
    messages, response = await apply_command(draw_request, _store)

    for message in messages:
        await manager.broadcast(draw_request.session_id, message.model_dump(mode="json"))

    return response
