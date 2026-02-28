"""Graph renderer for linear equations."""
from __future__ import annotations

import asyncio
from typing import Awaitable

from canvas.state import BBox
from drawing_client import DrawingClient
from math_verify import evaluate_linear, parse_linear_equation


def _clamp_01(val: float) -> float:
    return max(0.0, min(1.0, val))


async def render_graph(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    equations: list[str],
    x_min: float,
    x_max: float,
) -> str:
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height

    parsed: list[tuple[str, float, float]] = []
    all_y_vals: list[float] = []
    for eq in equations:
        slope, intercept = parse_linear_equation(eq)
        parsed.append((eq, slope, intercept))
        all_y_vals.extend([
            evaluate_linear(slope, intercept, x_min),
            evaluate_linear(slope, intercept, x_max),
        ])

    y_min_data = min(all_y_vals) - 1.0
    y_max_data = max(all_y_vals) + 1.0
    if y_min_data == y_max_data:
        y_max_data += 1.0

    draw_calls: list[Awaitable] = [
        client.send_shape(
            session_id=session_id,
            shape="polygon",
            x=bbox.x,
            y=bbox.y,
            width=bbox.width,
            height=bbox.height,
            color="#999",
            template_variant="cartesian_axes",
        ),
        client.send_text(session_id, "x", x=x + w - 0.02, y=y + h * 0.52, font_size=14, color="#999"),
        client.send_text(session_id, "y", x=x + w * 0.52, y=y + 0.01, font_size=14, color="#999"),
    ]

    colors = ["#e74c3c", "#2980b9", "#27ae60", "#8e44ad"]
    for i, (eq, slope, intercept) in enumerate(parsed):
        color = colors[i % len(colors)]

        points: list[dict[str, float]] = []
        num_samples = 40
        for s in range(num_samples + 1):
            xv = x_min + (x_max - x_min) * s / num_samples
            yv = evaluate_linear(slope, intercept, xv)
            nx = x + w * (xv - x_min) / (x_max - x_min)
            ny = y + h * (1.0 - (yv - y_min_data) / (y_max_data - y_min_data))
            points.append({"x": _clamp_01(nx), "y": _clamp_01(ny)})

        draw_calls.append(client.send_freehand(
            session_id=session_id,
            points=points,
            color=color,
            stroke_width=2.5,
            delay_ms=20,
        ))
        draw_calls.append(client.send_text(
            session_id=session_id,
            text=eq,
            x=x + w * 0.58,
            y=y + 0.02 + i * 0.04,
            font_size=14,
            color=color,
        ))

    await asyncio.gather(*draw_calls)
    return f"Graph of {', '.join(equations)}"
