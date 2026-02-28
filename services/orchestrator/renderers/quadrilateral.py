"""Quadrilateral renderers."""
from __future__ import annotations

import asyncio
from typing import Awaitable

from canvas.state import BBox
from drawing_client import DrawingClient


async def render_rhombus(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height
    cx, cy = x + w / 2, y + h / 2

    vertices = [
        {"x": cx, "y": y},
        {"x": x + w, "y": cy},
        {"x": cx, "y": y + h},
        {"x": x, "y": cy},
        {"x": cx, "y": y},
    ]

    draw_calls: list[Awaitable] = [
        client.send_freehand(
            session_id=session_id,
            points=vertices,
            color="#222",
            stroke_width=2.0,
            delay_ms=35,
        ),
        client.send_freehand(
            session_id=session_id,
            points=[{"x": cx, "y": y}, {"x": cx, "y": y + h}],
            color="#888",
            stroke_width=1.0,
            delay_ms=0,
        ),
        client.send_freehand(
            session_id=session_id,
            points=[{"x": x, "y": cy}, {"x": x + w, "y": cy}],
            color="#888",
            stroke_width=1.0,
            delay_ms=0,
        ),
    ]

    if len(labels) >= 1:
        draw_calls.append(client.send_text(
            session_id, labels[0], x=cx + 0.01, y=cy - 0.04, font_size=14, color="#222",
        ))
    if len(labels) >= 2:
        draw_calls.append(client.send_text(
            session_id, labels[1], x=cx - 0.04, y=cy + 0.01, font_size=14, color="#222",
        ))

    await asyncio.gather(*draw_calls)
    label_str = ", ".join(labels) if labels else "no labels"
    return f"Rhombus with {label_str}"


async def render_parallelogram(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height
    shift = w * 0.2

    points = [
        {"x": x + shift, "y": y},
        {"x": x + w, "y": y},
        {"x": x + w - shift, "y": y + h},
        {"x": x, "y": y + h},
        {"x": x + shift, "y": y},
    ]

    draw_calls: list[Awaitable] = [
        client.send_freehand(
            session_id=session_id,
            points=points,
            color="#222",
            stroke_width=2.0,
            delay_ms=35,
        ),
    ]

    for i, label in enumerate(labels[:4]):
        if i == 0:  # top
            lx, ly = x + w * 0.5, y - 0.04
        elif i == 1:  # right
            lx, ly = x + w + 0.01, y + h * 0.5
        elif i == 2:  # bottom
            lx, ly = x + w * 0.35, y + h + 0.01
        else:  # left
            lx, ly = x - 0.05, y + h * 0.5
        draw_calls.append(client.send_text(session_id, label, x=lx, y=ly, font_size=14, color="#222"))

    await asyncio.gather(*draw_calls)
    label_str = ", ".join(labels) if labels else "no labels"
    return f"Parallelogram with {label_str}"


async def render_trapezoid(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height
    inset = w * 0.22

    points = [
        {"x": x + inset, "y": y},
        {"x": x + w - inset, "y": y},
        {"x": x + w, "y": y + h},
        {"x": x, "y": y + h},
        {"x": x + inset, "y": y},
    ]

    draw_calls: list[Awaitable] = [
        client.send_freehand(
            session_id=session_id,
            points=points,
            color="#222",
            stroke_width=2.0,
            delay_ms=35,
        ),
    ]

    if labels:
        draw_calls.append(client.send_text(
            session_id, labels[0], x=x + w * 0.4, y=y + h + 0.01, font_size=14, color="#222",
        ))

    await asyncio.gather(*draw_calls)
    label_str = ", ".join(labels) if labels else "no labels"
    return f"Trapezoid with {label_str}"
