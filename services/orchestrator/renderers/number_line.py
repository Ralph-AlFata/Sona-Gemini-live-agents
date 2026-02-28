"""Number line renderer."""
from __future__ import annotations

import asyncio
from typing import Awaitable

from canvas.state import BBox
from drawing_client import DrawingClient


async def render_number_line(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height
    mid_y = y + h * 0.55
    start_x = x + w * 0.08
    end_x = x + w * 0.92

    values = params.get("values") or [-3, 3]
    vmin = int(min(values)) if len(values) >= 2 else -3
    vmax = int(max(values)) if len(values) >= 2 else 3
    if vmin == vmax:
        vmax += 1

    draw_calls: list[Awaitable] = [
        client.send_freehand(
            session_id=session_id,
            points=[{"x": start_x, "y": mid_y}, {"x": end_x, "y": mid_y}],
            color="#222",
            stroke_width=2.0,
            delay_ms=10,
        )
    ]

    tick_count = min(13, max(2, vmax - vmin + 1))
    for i in range(tick_count):
        ratio = i / (tick_count - 1)
        tx = start_x + (end_x - start_x) * ratio
        draw_calls.append(client.send_freehand(
            session_id=session_id,
            points=[{"x": tx, "y": mid_y - 0.018}, {"x": tx, "y": mid_y + 0.018}],
            color="#666",
            stroke_width=1.2,
            delay_ms=0,
        ))

        value = int(round(vmin + (vmax - vmin) * ratio))
        draw_calls.append(client.send_text(
            session_id=session_id,
            text=str(value),
            x=tx - 0.01,
            y=mid_y + 0.025,
            font_size=12,
            color="#555",
        ))

    for i, label in enumerate(labels[:4]):
        ratio = (i + 1) / (len(labels[:4]) + 1)
        lx = start_x + (end_x - start_x) * ratio
        draw_calls.append(client.send_text(
            session_id=session_id,
            text=label,
            x=lx - 0.01,
            y=mid_y - 0.055,
            font_size=13,
            color="#e74c3c",
        ))

    await asyncio.gather(*draw_calls)
    return f"Number line from {vmin} to {vmax}"
