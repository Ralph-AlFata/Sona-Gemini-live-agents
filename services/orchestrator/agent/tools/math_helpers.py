"""Math helper tools built on primitives."""

from __future__ import annotations

import logging
import math

from google.adk.tools import ToolContext
from sympy import Symbol, lambdify
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from agent.tools._cursor import LEFT_MARGIN, RIGHT_EDGE
from agent.tools._cursor_store import get_cursor
from agent.tools._shared import execute_tool_command, resolve_session_id, result_to_dict
from agent.tools._trace import emit_draw_trace
from agent.tools.core import highlight_region, shape_to_points

logger = logging.getLogger(__name__)

_DEFAULT_PLOT_COLOR = "#e74c3c"
_DEFAULT_PLOT_LABEL_FONT_SIZE = 14
_DEFAULT_PLOT_LABEL_OFFSET = 0.025
_GRAPH_VIEWPORT_STATE_KEY = "active_graph_viewport"
_DEFAULT_GRAPH_VIEWPORT = {
    "x": 0.1,
    "y": 0.05,
    "width": 0.8,
    "height": 0.45,
    "domain_min": -10.0,
    "domain_max": 10.0,
    "y_min": -10.0,
    "y_max": 10.0,
}
_VALID_NEXT_DIRECTIONS = {"below", "right", "left", "below_all"}
_MAX_GRAPH_WIDTH = max(0.1, RIGHT_EDGE - LEFT_MARGIN)
_MAX_GRAPH_HEIGHT = 2.0
_SYMPY_TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)


def _normalize_graph_size(width: float, height: float) -> tuple[float, float, bool]:
    """Normalize oversized graph viewport dimensions to canvas units."""
    w = max(width, 0.001)
    h = max(height, 0.001)
    if w <= _MAX_GRAPH_WIDTH and h <= _MAX_GRAPH_HEIGHT:
        return w, h, False

    for factor in (0.01, 0.001, 0.1):
        scaled_w = w * factor
        scaled_h = h * factor
        if scaled_w <= _MAX_GRAPH_WIDTH and scaled_h <= _MAX_GRAPH_HEIGHT:
            return max(0.02, scaled_w), max(0.02, scaled_h), True

    scale = max(w / _MAX_GRAPH_WIDTH, h / _MAX_GRAPH_HEIGHT, 1.0)
    return (
        max(0.02, min(_MAX_GRAPH_WIDTH, w / scale)),
        max(0.02, min(_MAX_GRAPH_HEIGHT, h / scale)),
        True,
    )


def _clamp_graph_viewport(x: float, y: float, width: float, height: float) -> tuple[dict[str, float], bool]:
    """Clamp a graph viewport so the full rectangle stays on-canvas."""
    clamped_width = max(0.001, min(_MAX_GRAPH_WIDTH, width))
    clamped_height = max(0.001, min(_MAX_GRAPH_HEIGHT, height))
    clamped_x = _clamp(x, 0.0, max(0.0, 1.0 - clamped_width))
    clamped_y = _clamp(y, 0.0, max(0.0, 2.0 - clamped_height))
    changed = (
        clamped_x != x
        or clamped_y != y
        or clamped_width != width
        or clamped_height != height
    )
    return {
        "x": clamped_x,
        "y": clamped_y,
        "width": clamped_width,
        "height": clamped_height,
    }, changed


def _normalize_expression_for_parse(expression: str) -> str:
    """Normalize common model syntax into something SymPy can parse reliably."""
    return expression.replace("^", "**").strip()


def _parse_expression(expression: str):
    """Parse expressions with implicit multiplication, e.g. `2x - 4` or `x^2 - 4`."""
    return parse_expr(
        _normalize_expression_for_parse(expression),
        transformations=_SYMPY_TRANSFORMATIONS,
        evaluate=True,
    )


async def draw_axes_grid(
    x: float | None = None,
    y: float | None = None,
    width: float = 0.8,
    height: float = 0.45,
    next: str = "below",
    grid_lines: int = 10,
    domain_min: float = -10.0,
    domain_max: float = 10.0,
    y_min: float = -10.0,
    y_max: float = 10.0,
    tool_context: ToolContext | None = None,
) -> dict:
    """Set up a graph viewport with axes and grid lines.

    If `x`/`y` are omitted, the graph viewport is auto-placed at the cursor.
    Use `next` to control cursor flow after placement.

    Invocation condition: Call ONCE per graph. Do not redraw the grid if it
    already exists on the canvas.
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be greater than 0")
    if next not in _VALID_NEXT_DIRECTIONS:
        raise ValueError(f"next must be one of {sorted(_VALID_NEXT_DIRECTIONS)}")
    if (x is None) != (y is None):
        raise ValueError("x and y must be both provided or both omitted")
    if domain_max <= domain_min:
        raise ValueError("domain_max must be greater than domain_min")
    if y_max <= y_min:
        raise ValueError("y_max must be greater than y_min")

    session_id = resolve_session_id(tool_context)
    used_cursor = False
    cursor = None
    normalized_size = False
    dedup_payload: dict | None = None
    width, height, normalized_size = _normalize_graph_size(width, height)
    if x is None and y is None:
        cursor = get_cursor(session_id)
        cursor_before = cursor.to_snapshot_dict()
        bbox = cursor.place(width, height, next_direction=next)
        x = bbox.x
        y = bbox.y
        used_cursor = True
        dedup_payload = {
            "width": width,
            "height": height,
            "next": next,
            "grid_lines": grid_lines,
            "domain_min": domain_min,
            "domain_max": domain_max,
            "y_min": y_min,
            "y_max": y_max,
        }

    grid_lines = max(2, min(30, grid_lines))
    viewport_rect, clamped_viewport = _clamp_graph_viewport(x, y, width, height)
    viewport = {
        **viewport_rect,
        "domain_min": domain_min,
        "domain_max": domain_max,
        "y_min": y_min,
        "y_max": y_max,
    }
    result = await execute_tool_command(
        session_id=session_id,
        operation="set_graph_viewport",
        payload={
            **viewport,
            "grid_lines": grid_lines,
            "show_border": True,
            "border_color": "#444444",
            "border_opacity": 0.5,
            "axis_color": "#111111",
            "axis_width": 2.0,
            "grid_color": "#bbbbbb",
            "grid_opacity": 0.5,
        },
        dedup_payload=dedup_payload,
    )
    _store_graph_viewport(tool_context, viewport)
    if used_cursor and cursor is not None and result.deduplicated:
        cursor.x = cursor_before["x"]
        cursor.y = cursor_before["y"]
        cursor.row_start_y = cursor_before["row_start_y"]
        cursor.row_max_bottom = cursor_before["row_max_bottom"]
        cursor.row_start_x = cursor_before["row_start_x"]
        cursor.column_max_right = cursor_before["column_max_right"]
        cursor.bottom_edge = cursor_before["bottom_edge"]
    if used_cursor and cursor is not None:
        if not result.deduplicated:
            emit_draw_trace({"cursor_state": cursor.to_snapshot_dict()})

    response = {
        **result_to_dict(result),
        "operation": "draw_axes_grid",
        "element_bbox": {
            "x": round(viewport["x"], 4),
            "y": round(viewport["y"], 4),
            "width": round(viewport["width"], 4),
            "height": round(viewport["height"], 4),
        },
        **({"cursor_after": cursor.to_dict()} if used_cursor and cursor is not None else {}),
    }
    if normalized_size:
        response["placement_warning"] = (
            "Graph width/height were auto-normalized to canvas coordinates."
        )
    if clamped_viewport:
        response["placement_warning"] = (
            "Graph viewport was clamped to remain within canvas bounds."
        )
    return response


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
    label = expression.strip().replace("**", "^").replace("*", "")
    if not label:
        return "y = 0"
    if not label.lower().startswith("y"):
        label = f"y = {label}"
    label = label.replace("+", " + ").replace("-", " - ")
    return " ".join(label.split())


def _store_graph_viewport(tool_context: ToolContext | None, viewport: dict[str, float]) -> None:
    if tool_context is None:
        return
    tool_context.state[_GRAPH_VIEWPORT_STATE_KEY] = viewport


def _resolve_graph_viewport(
    tool_context: ToolContext | None,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    domain_min: float,
    domain_max: float,
    y_min: float,
    y_max: float,
) -> dict[str, float]:
    requested = {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "domain_min": domain_min,
        "domain_max": domain_max,
        "y_min": y_min,
        "y_max": y_max,
    }
    if tool_context is None:
        return requested

    stored = tool_context.state.get(_GRAPH_VIEWPORT_STATE_KEY)
    if not isinstance(stored, dict):
        return requested

    uses_defaults = all(requested[key] == _DEFAULT_GRAPH_VIEWPORT[key] for key in _DEFAULT_GRAPH_VIEWPORT)
    if not uses_defaults:
        return requested

    return {
        key: float(stored.get(key, _DEFAULT_GRAPH_VIEWPORT[key]))
        for key in _DEFAULT_GRAPH_VIEWPORT
    }


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
    viewport = _resolve_graph_viewport(
        tool_context,
        x=x,
        y=y,
        width=width,
        height=height,
        domain_min=domain_min,
        domain_max=domain_max,
        y_min=y_min,
        y_max=y_max,
    )
    x = viewport["x"]
    y = viewport["y"]
    width = viewport["width"]
    height = viewport["height"]
    domain_min = viewport["domain_min"]
    domain_max = viewport["domain_max"]
    y_min = viewport["y_min"]
    y_max = viewport["y_max"]

    var_x = Symbol("x")
    try:
        expr = _parse_expression(expression)
    except Exception as exc:
        logger.info("PLOT_FUNCTION_PARSE_ERROR expression=%r error=%s", expression, exc)
        return {
            "status": "error",
            "operation": "plot_function_2d",
            "applied_count": 0,
            "created_element_ids": [],
            "failed_operations": [{"element_id": None, "reason": f"invalid expression: {expression}"}],
        }
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
            "render_mode": "polyline",
            "graph_clip": {
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            },
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


def _fmt_coord(v: float) -> str:
    """Format a coordinate value: integer if whole, 2dp otherwise."""
    return str(int(v)) if v == int(v) else f"{v:.2f}"


async def mark_graph_intersection(
    math_x: float,
    math_y: float,
    label: str | None = None,
    stroke_color: str = "rgba(220,50,50,0.9)",
    stroke_width: float = 2.5,
    padding: float = 0.018,
    tool_context: ToolContext | None = None,
) -> dict:
    """Place an X marker at a math-space point on the active graph.

    Reads the stored graph viewport from tool_context.state and converts
    (math_x, math_y) to canvas coordinates automatically.
    If label is omitted, defaults to "(math_x, math_y)".
    """
    if tool_context is None:
        return {
            "status": "error",
            "operation": "mark_graph_intersection",
            "applied_count": 0,
            "created_element_ids": [],
            "failed_operations": [{"error": "tool_context is required"}],
        }

    vp = tool_context.state.get(_GRAPH_VIEWPORT_STATE_KEY)
    if not isinstance(vp, dict):
        return {
            "status": "error",
            "operation": "mark_graph_intersection",
            "applied_count": 0,
            "created_element_ids": [],
            "failed_operations": [{"error": "No active graph viewport. Call draw_axes_grid first."}],
        }

    gx = float(vp["x"])
    gy = float(vp["y"])
    gw = float(vp["width"])
    gh = float(vp["height"])
    domain_min = float(vp["domain_min"])
    domain_max = float(vp["domain_max"])
    y_min = float(vp["y_min"])
    y_max = float(vp["y_max"])

    t = (math_x - domain_min) / (domain_max - domain_min)
    nx = max(0.0, min(1.0, gx + t * gw))
    ny = max(0.0, min(2.0, gy + (y_max - math_y) / (y_max - y_min) * gh))

    auto_label = label if label else f"({_fmt_coord(math_x)}, {_fmt_coord(math_y)})"

    return await highlight_region(
        element_ids=[],
        highlight_type="x_marker",
        point_x=nx,
        point_y=ny,
        label=auto_label,
        stroke_color=stroke_color,
        stroke_width=stroke_width,
        padding=padding,
        tool_context=tool_context,
    )
