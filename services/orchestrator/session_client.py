"""Async client for the session service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import httpx


@dataclass(slots=True)
class SessionServiceClient:
    """HTTP client for persisted session + turn storage."""

    base_url: str
    timeout_seconds: float = 10.0
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _auth_headers(auth_token: str | None) -> dict[str, str] | None:
        if isinstance(auth_token, str) and auth_token:
            return {"Authorization": f"Bearer {auth_token}"}
        return None

    async def get_session(
        self,
        session_id: str,
        *,
        auth_token: str | None = None,
    ) -> dict[str, Any] | None:
        response = await self._client.get(
            f"/sessions/{session_id}",
            headers=self._auth_headers(auth_token),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def create_session(
        self,
        *,
        session_id: str,
        student_id: str,
        topic: str | None = None,
        auth_token: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": session_id,
            "student_id": student_id,
            "topic": topic,
        }
        response = await self._client.post(
            "/sessions",
            json=payload,
            headers=self._auth_headers(auth_token),
        )
        response.raise_for_status()
        return response.json()

    async def append_turn(
        self,
        *,
        session_id: str,
        role: Literal["student", "sona"],
        content: str,
        metadata: dict[str, Any] | None = None,
        auth_token: str | None = None,
    ) -> dict[str, Any]:
        response = await self._client.post(
            f"/sessions/{session_id}/turns",
            json={
                "role": role,
                "content": content,
                "metadata": metadata,
            },
            headers=self._auth_headers(auth_token),
        )
        response.raise_for_status()
        return response.json()
