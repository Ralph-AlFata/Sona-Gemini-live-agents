"""Async client for drawing command service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx


@dataclass(slots=True)
class DrawingCommandResult:
    session_id: str
    command_id: str
    operation: str
    applied_count: int
    created_element_ids: list[str]
    failed_operations: list[dict]
    emitted_count: int
    dsl_messages: list[dict[str, Any]] = field(default_factory=list)

class DrawingClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def execute(self, session_id: str, operation: str, payload: dict, command_id: str | None = None) -> DrawingCommandResult:
        cid = command_id or uuid4().hex[:12]
        response = await self._client.post(
            "/draw",
            json={
                "command_id": cid,
                "operation": operation,
                "session_id": session_id,
                "payload": payload,
            },
        )
        response.raise_for_status()
        body = response.json()
        return DrawingCommandResult(
            session_id=str(body["session_id"]),
            command_id=str(body["command_id"]),
            operation=str(body.get("operation", operation)),
            applied_count=int(body.get("applied_count", 0)),
            created_element_ids=[str(item) for item in body.get("created_element_ids", [])],
            failed_operations=list(body.get("failed_operations", [])),
            emitted_count=int(body.get("emitted_count", 0)),
            dsl_messages=[
                item
                for item in body.get("dsl_messages", [])
                if isinstance(item, dict)
            ],
        )
