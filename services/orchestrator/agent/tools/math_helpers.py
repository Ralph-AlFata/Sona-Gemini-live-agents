"""Math helper tools built on primitives."""

from __future__ import annotations

import math

from google.adk.tools import ToolContext
from sympy import Symbol, lambdify, sympify

from agent.tools._shared import get_client, resolve_session_id
from agent.tools.core import shape_to_points


async def draw_axes_grid(
    x: float = 0.1,
    y: float = 0.1,
    width: float = 0.8,
    height: float = 0.8,
    grid_lines: int = 10,
    domain_min: float = -10.0,
    domain_max: float = 10.0,
    y_min: float = -10.0,
    y_max: float = 10.0,
    tool_context: ToolContext | None = None,
) -> dict:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be greater than 0")
    if domain_max <= domain_min:
        raise ValueError("domain_max must be greater than domain_min")
    if y_max <= y_min:
        raise ValueError("y_max must be greater than y_min")

    grid_lines = max(2, min(30, grid_lines))
    result = await get_client().execute(
        session_id=resolve_session_id(tool_context),
        operation="set_graph_viewport",
        payload={
            "x": max(0.0, min(1.0, x)),
            "y": max(0.0, min(1.0, y)),
            "width": max(0.001, min(1.0, width)),
            "height": max(0.001, min(1.0, height)),
            "domain_min": domain_min,
            "domain_max": domain_max,
            "y_min": y_min,
            "y_max": y_max,
            "grid_lines": grid_lines,
            "show_border": True,
            "border_color": "#444444",
            "border_opacity": 0.5,
            "axis_color": "#111111",
            "axis_width": 2.0,
            "grid_color": "#bbbbbb",
            "grid_opacity": 0.5,
        },
    )

    return {
        "status": "success",
        "operation": "draw_axes_grid",
        "command_id": result.command_id,
        "applied_count": result.applied_count,
        "created_element_ids": result.created_element_ids,
        "failed_operations": result.failed_operations,
    }


async def draw_number_line(
    x: float,
    y: float,
    width: float,
    min_value: int = -5,
    max_value: int = 5,
    tick_height: float = 0.04,
    tool_context: ToolContext | None = None,
) -> dict:
    if max_value <= min_value:
        raise ValueError("max_value must be greater than min_value")

    session_id = resolve_session_id(tool_context)
    client = get_client()
    created: list[str] = []

    base = await client.execute(
        session_id,
        "draw_shape",
        {
            "shape": "line",
            "points": shape_to_points("line", x, y, width, 0.0),
            "style": {"stroke_color": "#111", "stroke_width": 2.0},
        },
    )
    created.extend(base.created_element_ids)

    count = max_value - min_value
    step = width / count
    for i, value in enumerate(range(min_value, max_value + 1)):
        tx = x + (i * step)
        tick = await client.execute(
            session_id,
            "draw_shape",
            {
                "shape": "line",
                "points": shape_to_points("line", tx, y - (tick_height / 2), 0.0, tick_height),
                "style": {"stroke_color": "#111", "stroke_width": 2.0},
            },
        )
        created.extend(tick.created_element_ids)

        label = await client.execute(
            session_id,
            "draw_text",
            {
                "text": str(value),
                "x": max(0.0, tx - 0.01),
                "y": min(1.0, y + 0.015),
                "font_size": 14,
                "style": {"stroke_color": "#111", "stroke_width": 1.0},
            },
        )
        created.extend(label.created_element_ids)

    return {
        "status": "success",
        "operation": "draw_number_line",
        "applied_count": len(created),
        "created_element_ids": created,
        "failed_operations": [],
    }


async def plot_function_2d(
    expression: str,
    x: float = 0.1,
    y: float = 0.1,
    width: float = 0.8,
    height: float = 0.8,
    domain_min: float = -10.0,
    domain_max: float = 10.0,
    y_min: float = -10.0,
    y_max: float = 10.0,
    samples: int = 200,
    tool_context: ToolContext | None = None,
) -> dict:
    if domain_max <= domain_min:
        raise ValueError("domain_max must be greater than domain_min")
    if y_max <= y_min:
        raise ValueError("y_max must be greater than y_min")
    samples = max(20, min(1000, samples))

    var_x = Symbol("x")
    expr = sympify(expression)
    fn = lambdify(var_x, expr, "math")

    points: list[dict[str, float]] = []
    for i in range(samples):
        t = i / (samples - 1)
        x_value = domain_min + ((domain_max - domain_min) * t)
        try:
            y_value = float(fn(x_value))
        except Exception:
            continue
        if not math.isfinite(y_value):
            continue
        if y_value < y_min or y_value > y_max:
            continue

        nx = x + (t * width)
        ny = y + ((y_max - y_value) / (y_max - y_min) * height)
        points.append(
            {
                "x": max(0.0, min(1.0, nx)),
                "y": max(0.0, min(1.0, ny)),
            }
        )

    if len(points) < 2:
        return {
            "status": "error",
            "operation": "plot_function_2d",
            "applied_count": 0,
            "created_element_ids": [],
            "failed_operations": [{"element_id": None, "reason": "no plottable points in range"}],
        }

    result = await get_client().execute(
        session_id=resolve_session_id(tool_context),
        operation="draw_freehand",
        payload={
            "points": points,
            "style": {
                "stroke_color": "#2563eb",
                "stroke_width": 2.5,
                "opacity": 1.0,
                "delay_ms": 10,
                "animate": True,
            },
        },
    )

    return {
        "status": "success",
        "operation": "plot_function_2d",
        "command_id": result.command_id,
        "applied_count": result.applied_count,
        "created_element_ids": result.created_element_ids,
        "failed_operations": result.failed_operations,
    }
