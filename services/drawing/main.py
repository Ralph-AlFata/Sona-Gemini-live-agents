"""Sona Drawing Command Service — FastAPI entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from dsl import translate
from models import (
    ClearPayload,
    ClearRequestBody,
    DrawRequest,
    DrawRequestBody,
    DrawResponse,
    DSLMessage,
    HealthResponse,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks websocket subscribers by session and broadcasts JSON DSL messages."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id].add(websocket)
        logger.info(
            "WebSocket connected: session_id=%s subscribers=%d",
            session_id,
            len(self._connections[session_id]),
        )

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        subscribers = self._connections.get(session_id)
        if subscribers is None:
            return

        subscribers.discard(websocket)
        if not subscribers:
            self._connections.pop(session_id, None)

        logger.info(
            "WebSocket disconnected: session_id=%s subscribers=%d",
            session_id,
            len(self._connections.get(session_id, set())),
        )

    async def broadcast(self, session_id: str, message: DSLMessage) -> int:
        subscribers = self._connections.get(session_id)
        if not subscribers:
            logger.info("No subscribers for session_id=%s; dropped message id=%s", session_id, message.id)
            return 0

        dead: list[WebSocket] = []
        payload: dict[str, Any] = message.model_dump(mode="json")

        for socket in subscribers:
            try:
                await socket.send_json(payload)
            except Exception:
                dead.append(socket)

        for socket in dead:
            self.disconnect(session_id, socket)

        delivered = len(subscribers) - len(dead)
        logger.info(
            "Broadcast complete: session_id=%s message_id=%s delivered=%d",
            session_id,
            message.id,
            delivered,
        )
        return delivered


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Drawing service starting up on port %s", os.environ.get("PORT", "8002"))
    yield
    logger.info("Drawing service shutting down")


app = FastAPI(
    title="Sona Drawing Command Service",
    description="Translates draw requests into DSL and broadcasts over WebSocket",
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
async def draw(body: DrawRequestBody) -> DrawResponse:
    try:
        draw_request = body.to_draw_request()
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
        ) from exc
    messages = translate(draw_request)

    for message in messages:
        asyncio.create_task(manager.broadcast(draw_request.session_id, message))

    logger.info(
        "Draw accepted: session_id=%s type=%s emitted=%d",
        draw_request.session_id,
        draw_request.message_type,
        len(messages),
    )
    return DrawResponse(session_id=draw_request.session_id, emitted_count=len(messages))


@app.post(
    "/draw/clear",
    response_model=DrawResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["drawing"],
)
async def clear_canvas(body: ClearRequestBody) -> DrawResponse:
    draw_request = DrawRequest(
        session_id=body.session_id,
        message_type="clear",
        payload=ClearPayload(),
    )
    messages = translate(draw_request)

    for message in messages:
        asyncio.create_task(manager.broadcast(draw_request.session_id, message))

    logger.info("Clear accepted: session_id=%s", draw_request.session_id)
    return DrawResponse(session_id=draw_request.session_id, emitted_count=len(messages))
