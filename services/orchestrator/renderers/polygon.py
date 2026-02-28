"""Regular polygon renderer factory — pentagon, hexagon, octagon, etc."""
from __future__ import annotations

import asyncio
import math
from typing import Awaitable, Callable

from canvas.state import BBox
from drawing_client import DrawingClient


def render_regular_polygon(n: int) -> Callable:
    """Return an async renderer for a regular n-sided polygon."""

    async def _render(
        client: DrawingClient,
        session_id: str,
        bbox: BBox,
        params: dict,
        labels: list[str],
    ) -> str:
        cx = bbox.x + bbox.width / 2
        cy = bbox.y + bbox.height / 2
        rx = bbox.width / 2 * 0.85
        ry = bbox.height / 2 * 0.85

        # Compute vertices (start from top, going clockwise)
        points: list[dict[str, float]] = []
        for i in range(n + 1):
            theta = (2 * math.pi * i / n) - (math.pi / 2)
            points.append({
                "x": max(0.0, min(1.0, cx + rx * math.cos(theta))),
                "y": max(0.0, min(1.0, cy + ry * math.sin(theta))),
            })

        draw_calls: list[Awaitable] = []

        draw_calls.append(client.send_freehand(
            session_id=session_id,
            points=points,
            color="#222",
            stroke_width=2.0,
            delay_ms=35,
        ))

        # Labels at vertices
        for i, label in enumerate(labels[:n]):
            theta = (2 * math.pi * i / n) - (math.pi / 2)
            lx = max(0.0, min(1.0, cx + (rx + 0.02) * math.cos(theta)))
            ly = max(0.0, min(1.0, cy + (ry + 0.02) * math.sin(theta)))
            draw_calls.append(client.send_text(
                session_id, label, x=lx, y=ly, font_size=14, color="#222",
            ))

        await asyncio.gather(*draw_calls)
        return f"Regular {n}-gon with {len(labels)} labels"

    return _render
