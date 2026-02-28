"""Triangle renderers — right triangle, equilateral, general."""
from __future__ import annotations

import asyncio
import math
from typing import Awaitable

from canvas.state import BBox
from drawing_client import DrawingClient


async def render_right_triangle(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    """Draw a right triangle with labels within the given bbox."""
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height

    draw_calls: list[Awaitable] = []

    # 1. Triangle shape via template
    draw_calls.append(client.send_shape(
        session_id=session_id,
        shape="polygon",
        x=bbox.x, y=bbox.y,
        width=bbox.width, height=bbox.height,
        color="#222",
        template_variant="right_triangle",
    ))

    # 2. Right angle marker (small square at bottom-left)
    marker_size = min(w, h) * 0.12
    draw_calls.append(client.send_freehand(
        session_id=session_id,
        points=[
            {"x": x + marker_size, "y": y + h},
            {"x": x + marker_size, "y": y + h - marker_size},
            {"x": x, "y": y + h - marker_size},
        ],
        color="#666",
        stroke_width=1.5,
        delay_ms=0,
    ))

    # 3. Labels at side midpoints
    if len(labels) >= 1:
        draw_calls.append(client.send_text(
            session_id, labels[0],
            x=x + w * 0.4, y=y + h + 0.01,
            font_size=16, color="#222",
        ))
    if len(labels) >= 2:
        draw_calls.append(client.send_text(
            session_id, labels[1],
            x=x + w + 0.01, y=y + h * 0.5,
            font_size=16, color="#222",
        ))
    if len(labels) >= 3:
        draw_calls.append(client.send_text(
            session_id, labels[2],
            x=x + w * 0.35, y=y + h * 0.35,
            font_size=16, color="#222",
        ))

    await asyncio.gather(*draw_calls)
    return f"Right triangle with labels {', '.join(labels)}"


async def render_triangle(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    """Draw a general triangle (equilateral by default) within the given bbox."""
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height

    if params.get("equilateral"):
        # Equilateral: top-center, bottom-left, bottom-right
        points = [
            {"x": x + w / 2, "y": y},
            {"x": x + w, "y": y + h},
            {"x": x, "y": y + h},
            {"x": x + w / 2, "y": y},  # close
        ]
    else:
        # General scalene triangle
        points = [
            {"x": x + w * 0.15, "y": y + h},
            {"x": x + w * 0.5, "y": y},
            {"x": x + w * 0.85, "y": y + h},
            {"x": x + w * 0.15, "y": y + h},  # close
        ]

    draw_calls: list[Awaitable] = []

    draw_calls.append(client.send_freehand(
        session_id=session_id,
        points=points,
        color="#222",
        stroke_width=2.0,
        delay_ms=35,
    ))

    # Labels at side midpoints
    if len(labels) >= 1:
        draw_calls.append(client.send_text(
            session_id, labels[0],
            x=x + w * 0.4, y=y + h + 0.01,
            font_size=16, color="#222",
        ))
    if len(labels) >= 2:
        draw_calls.append(client.send_text(
            session_id, labels[1],
            x=x + w + 0.01, y=y + h * 0.5,
            font_size=16, color="#222",
        ))
    if len(labels) >= 3:
        draw_calls.append(client.send_text(
            session_id, labels[2],
            x=x + w * 0.2, y=y + h * 0.4,
            font_size=16, color="#222",
        ))

    await asyncio.gather(*draw_calls)
    label_str = ", ".join(labels) if labels else "no labels"
    kind = "Equilateral" if params.get("equilateral") else "Triangle"
    return f"{kind} with {label_str}"
