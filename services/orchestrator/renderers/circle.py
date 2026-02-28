"""Circle renderer — circle with radius/diameter/angle annotations."""
from __future__ import annotations

import asyncio
from typing import Awaitable

from canvas.state import BBox
from drawing_client import DrawingClient


async def render_circle(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    """Draw a circle with optional radius line and labels."""
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height
    cx, cy = x + w / 2, y + h / 2

    draw_calls: list[Awaitable] = []

    # Circle outline via template
    draw_calls.append(client.send_shape(
        session_id=session_id,
        shape="ellipse",
        x=bbox.x, y=bbox.y,
        width=bbox.width, height=bbox.height,
        color="#222",
        template_variant="circle_outline",
    ))

    # Radius line from center to right edge
    radius = params.get("radius")
    if radius is not None or labels:
        draw_calls.append(client.send_freehand(
            session_id=session_id,
            points=[
                {"x": cx, "y": cy},
                {"x": x + w * 0.95, "y": cy},
            ],
            color="#e74c3c",
            stroke_width=1.5,
            delay_ms=20,
        ))

    # Center dot
    draw_calls.append(client.send_freehand(
        session_id=session_id,
        points=[
            {"x": cx - 0.003, "y": cy},
            {"x": cx + 0.003, "y": cy},
        ],
        color="#222",
        stroke_width=4.0,
        delay_ms=0,
    ))

    # Labels
    if len(labels) >= 1:
        draw_calls.append(client.send_text(
            session_id, labels[0],
            x=cx + w * 0.15, y=cy - 0.03,
            font_size=16, color="#e74c3c",
        ))
    if len(labels) >= 2:
        draw_calls.append(client.send_text(
            session_id, labels[1],
            x=cx - 0.02, y=y + h + 0.01,
            font_size=14, color="#222",
        ))

    await asyncio.gather(*draw_calls)
    label_str = ", ".join(labels) if labels else "no labels"
    return f"Circle with {label_str}"
