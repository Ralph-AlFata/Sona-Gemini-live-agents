"""Rectangle / square renderer."""
from __future__ import annotations

import asyncio
from typing import Awaitable

from canvas.state import BBox
from drawing_client import DrawingClient


async def render_rectangle(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    """Draw a rectangle (or square) with side labels."""
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height

    draw_calls: list[Awaitable] = []

    draw_calls.append(client.send_shape(
        session_id=session_id,
        shape="rectangle",
        x=bbox.x, y=bbox.y,
        width=bbox.width, height=bbox.height,
        color="#222",
    ))

    # Labels: bottom, right, top, left
    if len(labels) >= 1:
        draw_calls.append(client.send_text(
            session_id, labels[0],
            x=x + w * 0.35, y=y + h + 0.01,
            font_size=16, color="#222",
        ))
    if len(labels) >= 2:
        draw_calls.append(client.send_text(
            session_id, labels[1],
            x=x + w + 0.01, y=y + h * 0.45,
            font_size=16, color="#222",
        ))
    if len(labels) >= 3:
        draw_calls.append(client.send_text(
            session_id, labels[2],
            x=x + w * 0.35, y=y - 0.04,
            font_size=16, color="#222",
        ))
    if len(labels) >= 4:
        draw_calls.append(client.send_text(
            session_id, labels[3],
            x=x - 0.05, y=y + h * 0.45,
            font_size=16, color="#222",
        ))

    await asyncio.gather(*draw_calls)
    label_str = ", ".join(labels) if labels else "no labels"
    return f"Rectangle with {label_str}"
