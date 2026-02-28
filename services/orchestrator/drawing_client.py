"""Async HTTP client for the drawing command service.

Provides a circuit-breaker-protected client for POSTing draw commands.
Uses the init/get singleton pattern for lifecycle management.
"""
from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)


class DrawingClient:
    """Async HTTP client for the drawing command service."""

    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=0.5)
        self._consecutive_failures = 0
        self._circuit_open = False
        self._circuit_opened_at: float = 0.0
        self._recovery_after: float = 30.0  # seconds

    async def _post(self, path: str, json: dict) -> None:
        """POST with circuit breaker. Opens after 3 consecutive failures,
        retries after 30 seconds (half-open state)."""
        if self._circuit_open:
            if time.monotonic() - self._circuit_opened_at > self._recovery_after:
                self._circuit_open = False
                self._consecutive_failures = 0
            else:
                return  # Silently skip — drawing is non-critical during voice tutoring
        try:
            await self._client.post(path, json=json)
            self._consecutive_failures = 0
        except (httpx.TimeoutException, httpx.ConnectError):
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._circuit_open = True
                self._circuit_opened_at = time.monotonic()
                logger.warning("DrawingClient circuit breaker OPEN after 3 failures")

    async def send_text(
        self,
        session_id: str,
        text: str,
        x: float,
        y: float,
        font_size: int = 24,
        color: str = "#222",
    ) -> None:
        await self._post("/draw", json={
            "session_id": session_id,
            "message_type": "text",
            "payload": {
                "text": text, "x": x, "y": y,
                "font_size": font_size, "color": color,
            },
        })

    async def send_freehand(
        self,
        session_id: str,
        points: list[dict[str, float]],
        color: str = "#111",
        stroke_width: float = 2.0,
        delay_ms: int = 35,
    ) -> None:
        await self._post("/draw", json={
            "session_id": session_id,
            "message_type": "freehand",
            "payload": {
                "points": points, "color": color,
                "stroke_width": stroke_width, "delay_ms": delay_ms,
            },
        })

    async def send_shape(
        self,
        session_id: str,
        shape: str,
        x: float,
        y: float,
        width: float,
        height: float,
        color: str = "#111",
        fill_color: str | None = None,
        template_variant: str | None = None,
    ) -> None:
        payload: dict = {
            "shape": shape, "x": x, "y": y,
            "width": width, "height": height, "color": color,
        }
        if fill_color:
            payload["fill_color"] = fill_color
        if template_variant:
            payload["template_variant"] = template_variant
        await self._post("/draw", json={
            "session_id": session_id,
            "message_type": "shape",
            "payload": payload,
        })

    async def send_highlight(
        self,
        session_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
        color: str = "rgba(255,255,0,0.3)",
    ) -> None:
        await self._post("/draw", json={
            "session_id": session_id,
            "message_type": "highlight",
            "payload": {"x": x, "y": y, "width": width, "height": height, "color": color},
        })

    async def send_clear(self, session_id: str) -> None:
        await self._post("/draw/clear", json={"session_id": session_id})

    async def aclose(self) -> None:
        """Close the underlying httpx.AsyncClient."""
        await self._client.aclose()


# ── Singleton lifecycle ──────────────────────────────────────────────────────

_client: DrawingClient | None = None


def init_drawing_client(base_url: str) -> DrawingClient:
    """Initialize module-level DrawingClient. Called once during lifespan startup."""
    global _client
    _client = DrawingClient(base_url=base_url)
    logger.info("DrawingClient initialized (base_url=%s)", base_url)
    return _client


def get_drawing_client() -> DrawingClient:
    """Return the module-level DrawingClient. Raises RuntimeError if not initialized."""
    if _client is None:
        raise RuntimeError(
            "DrawingClient not initialized. "
            "Ensure init_drawing_client() is called during lifespan startup."
        )
    return _client
