"""Sona Drawing Command Service — FastAPI entry point."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware

from dsl import StoredElement, apply_command
from models import (
    ClearPayload,
    ClearRequest,
    DrawCommandRequest,
    DrawResponse,
    HealthResponse,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks WebSocket subscribers by session and broadcasts JSON DSL messages."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id].add(websocket)

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
# session_id -> element_id -> element\
# TODO: In the future, we need to integrate database in the cloud. We need to handle the different sessions for the different users, and have the canvas there, etc...
ELEMENT_STORE: dict[str, dict[str, StoredElement]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Drawing service starting up on port %s", os.environ.get("PORT", "8002"))
    yield
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
# TODO: Standardize everything that is coming from the .env. Create a config.py file for the drawing microservice, then load the settings from there
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
    status_code=status.HTTP_202_ACCEPTED,
    tags=["drawing"],
)
async def draw(body: DrawCommandRequest) -> DrawResponse:
    messages, response = apply_command(body, ELEMENT_STORE)

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
    status_code=status.HTTP_202_ACCEPTED,
    tags=["drawing"],
)
async def clear_canvas(body: ClearRequest) -> DrawResponse:
    draw_request = DrawCommandRequest(
        session_id=body.session_id,
        operation="clear_canvas",
        payload=ClearPayload(),
    )
    messages, response = apply_command(draw_request, ELEMENT_STORE)

    for message in messages:
        await manager.broadcast(draw_request.session_id, message.model_dump(mode="json"))

    return response
