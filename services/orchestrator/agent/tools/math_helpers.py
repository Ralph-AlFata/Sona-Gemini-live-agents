"""Math helper tools built on primitives."""

from __future__ import annotations

import math

from google.adk.tools import ToolContext
from sympy import Symbol, lambdify, sympify

from agent.tools._shared import execute_tool_command, resolve_session_id
from agent.tools.core import shape_to_points

_DEFAULT_PLOT_COLOR = "#e74c3c"
_DEFAULT_PLOT_LABEL_FONT_SIZE = 14
_DEFAULT_PLOT_LABEL_OFFSET = 0.025


async def draw_axes_grid(
    x: float = 0.1,
    y: float = 0.05,
    width: float = 0.8,
    height: float = 0.45,
    grid_lines: int = 10,
    domain_min: float = -10.0,
    domain_max: float = 10.0,
    y_min: float = -10.0,
    y_max: float = 10.0,
    tool_context: ToolContext | None = None,
) -> dict:
    """Set up a graph viewport with axes and grid lines.

    Invocation condition: Call ONCE per graph. Do not redraw the grid if it
    already exists on the canvas.
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be greater than 0")
    if domain_max <= domain_min:
        raise ValueError("domain_max must be greater than domain_min")
    if y_max <= y_min:
        raise ValueError("y_max must be greater than y_min")

    grid_lines = max(2, min(30, grid_lines))
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="set_graph_viewport",
        payload={
            "x": max(0.0, min(1.0, x)),
            "y": max(0.0, min(2.0, y)),
            "width": max(0.001, min(1.0, width)),
            "height": max(0.001, min(2.0, height)),
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
    """Draw a number line with ticks and labels.

    Invocation condition: Call ONCE per number line. Do not redraw if a
    number line already exists on the canvas.
    """
    if max_value <= min_value:
        raise ValueError("max_value must be greater than min_value")

    session_id = resolve_session_id(tool_context)
    created: list[str] = []

    base = await execute_tool_command(
        session_id=session_id,
        operation="draw_shape",
        payload={
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
        tick = await execute_tool_command(
            session_id=session_id,
            operation="draw_shape",
            payload={
                "shape": "line",
                "points": shape_to_points("line", tx, y - (tick_height / 2), 0.0, tick_height),
                "style": {"stroke_color": "#111", "stroke_width": 2.0},
            },
        )
        created.extend(tick.created_element_ids)

        label = await execute_tool_command(
            session_id=session_id,
            operation="draw_text",
            payload={
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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _estimate_text_size(text: str, font_size: int) -> tuple[float, float]:
    width = min(0.8, 0.012 * len(text) * (font_size / 24))
    height = min(0.25, 0.03 * (font_size / 24))
    return width, height


def _format_equation_label(expression: str) -> str:
    label = expression.strip().replace("*", "")
    if not label:
        return "y = 0"
    if not label.lower().startswith("y"):
        label = f"y = {label}"
    label = label.replace("+", " + ").replace("-", " - ")
    return " ".join(label.split())


def _compute_plot_label_position(
    points: list[dict[str, float]],
    *,
    graph_y: float,
    graph_height: float,
    graph_x: float,
    graph_width: float,
    label_text: str,
    font_size: int,
    placed_positions: list[tuple[float, float]],
) -> tuple[float, float]:
    anchor_index = min(len(points) - 1, max(0, int(len(points) * 0.85)))
    anchor = points[anchor_index]
    p_before = points[max(0, anchor_index - 1)]
    p_after = points[min(len(points) - 1, anchor_index + 1)]
    dx = p_after["x"] - p_before["x"]
    dy = p_after["y"] - p_before["y"]
    length = math.hypot(dx, dy)
    if length > 1e-6:
        nx = -dy / length
        ny = dx / length
    else:
        nx, ny = 0.0, -1.0

    graph_center_y = graph_y + (graph_height / 2)
    if anchor["y"] < graph_center_y:
        if ny > 0:
            nx, ny = -nx, -ny
    elif ny < 0:
        nx, ny = -nx, -ny

    label_x = anchor["x"] + (nx * _DEFAULT_PLOT_LABEL_OFFSET)
    label_y = anchor["y"] + (ny * _DEFAULT_PLOT_LABEL_OFFSET)

    for prev_x, prev_y in placed_positions:
        if abs(label_x - prev_x) < 0.1 and abs(label_y - prev_y) < 0.03:
            label_y = prev_y + 0.035

    text_width, text_height = _estimate_text_size(label_text, font_size)
    label_x = _clamp(label_x - (text_width / 2), graph_x, max(graph_x, graph_x + graph_width - text_width))
    label_y = _clamp(label_y - (text_height / 2), graph_y, max(graph_y, graph_y + graph_height - text_height))
    return label_x, label_y


async def plot_function_2d(
    expression: str,
    x: float = 0.1,
    y: float = 0.05,
    width: float = 0.8,
    height: float = 0.45,
    domain_min: float = -10.0,
    domain_max: float = 10.0,
    y_min: float = -10.0,
    y_max: float = 10.0,
    samples: int = 200,
    stroke_color: str = _DEFAULT_PLOT_COLOR,
    stroke_width: float = 2.5,
    tool_context: ToolContext | None = None,
) -> dict:
    """Plot a mathematical function on the graph viewport.

    Invocation condition: Call ONCE per function expression. Do not replot
    the same expression that already has a confirmed element ID. The plotted
    function is automatically labeled with its equation near the visible line.
    """
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
                "y": max(0.0, min(2.0, ny)),
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

    session_id = resolve_session_id(tool_context)
    result = await execute_tool_command(
        session_id=session_id,
        operation="draw_freehand",
        payload={
            "points": points,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "opacity": 1.0,
                "delay_ms": 10,
                "animate": True,
            },
        },
    )

    label_text = _format_equation_label(expression)
    label_x, label_y = _compute_plot_label_position(
        points,
        graph_y=y,
        graph_height=height,
        graph_x=x,
        graph_width=width,
        label_text=label_text,
        font_size=_DEFAULT_PLOT_LABEL_FONT_SIZE,
        placed_positions=[],
    )
    label_result = await execute_tool_command(
        session_id=session_id,
        operation="draw_text",
        payload={
            "text": label_text,
            "x": label_x,
            "y": label_y,
            "font_size": _DEFAULT_PLOT_LABEL_FONT_SIZE,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": 1.0,
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
        "applied_count": result.applied_count + label_result.applied_count,
        "created_element_ids": result.created_element_ids + label_result.created_element_ids,
        "failed_operations": result.failed_operations + label_result.failed_operations,
        "line_element_ids": result.created_element_ids,
        "label_element_ids": label_result.created_element_ids,
        "plot_summary": f"Plotted {label_text} in {stroke_color}.",
    }
