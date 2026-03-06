"""Sona Drawing Command Service — FastAPI entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from dsl import apply_command
from models import (
    ClearPayload,
    ClearRequest,
    DrawCommandRequest,
    DrawResponse,
    HealthResponse,
)
from store import ElementStore, InMemoryElementStore

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _store

    if settings.use_firestore:
        from firestore_store import FirestoreElementStore, close_firestore_client, init_firestore_client
        init_firestore_client()
        _store = FirestoreElementStore()
        logger.info("Drawing service using Firestore element store")
    else:
        logger.info("Drawing service using in-memory element store")

    logger.info("Drawing service starting up on port %s", settings.port)
    yield

    if settings.use_firestore:
        from firestore_store import close_firestore_client
        await close_firestore_client()

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


@app.websocket("/ws/{session_id}")
async def websocket_session(session_id: str, websocket: WebSocket) -> None:
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
async def draw(body: DrawCommandRequest) -> DrawResponse:
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
async def clear_canvas(body: ClearRequest) -> DrawResponse:
    draw_request = DrawCommandRequest(
        session_id=body.session_id,
        operation="clear_canvas",
        payload=ClearPayload(),
    )
    messages, response = await apply_command(draw_request, _store)

    for message in messages:
        await manager.broadcast(draw_request.session_id, message.model_dump(mode="json"))

    return response
