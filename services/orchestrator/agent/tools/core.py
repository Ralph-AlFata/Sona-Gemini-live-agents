"""Core drawing primitives."""

from __future__ import annotations

import math

from google.adk.tools import ToolContext

from agent.tools._shared import execute_tool_command, resolve_session_id, result_to_dict
from agent.tools.models import DrawFreehandInput, DrawShapeInput, DrawTextInput, HighlightInput


def shape_to_points(
    shape: str,
    x: float,
    y: float,
    width: float,
    height: float,
) -> list[dict[str, float]]:
    """
    Convert a shape defined by (x, y, width, height) into explicit vertex points.

    This helper is used internally so that math_helpers can still express shapes
    in terms of position/size while the drawing service receives normalised points.
    """
    if shape == "line":
        return [{"x": x, "y": y}, {"x": x + width, "y": y + height}]

    if shape in ("rectangle", "square"):
        return [
            {"x": x, "y": y},
            {"x": x + width, "y": y},
            {"x": x + width, "y": y + height},
            {"x": x, "y": y + height},
            {"x": x, "y": y},
        ]

    if shape == "triangle":
        # Isoceles triangle: base at bottom, apex at top centre.
        return [
            {"x": x, "y": y + height},
            {"x": x + width / 2, "y": y},
            {"x": x + width, "y": y + height},
            {"x": x, "y": y + height},
        ]

    if shape == "right_triangle":
        # Right angle at bottom-left.
        return [
            {"x": x, "y": y + height},
            {"x": x + width, "y": y + height},
            {"x": x, "y": y},
            {"x": x, "y": y + height},
        ]

    if shape == "circle":
        # Circle: equal radius in both axes (width-uniform coords guarantee roundness)
        cx = x + width / 2
        cy = y + height / 2
        r = min(width, height) / 2
        segments = 48
        points = []
        for i in range(segments + 1):
            t = 2 * math.pi * i / segments
            points.append({
                "x": max(0.0, min(1.0, cx + r * math.cos(t))),
                "y": max(0.0, min(2.0, cy + r * math.sin(t))),
            })
        return points

    if shape == "ellipse":
        cx = x + width / 2
        cy = y + height / 2
        rx = width / 2
        ry = height / 2
        segments = 48
        points = []
        for i in range(segments + 1):
            t = 2 * math.pi * i / segments
            points.append({
                "x": max(0.0, min(1.0, cx + rx * math.cos(t))),
                "y": max(0.0, min(2.0, cy + ry * math.sin(t))),
            })
        return points

    if shape == "polygon":
        cx = x + width / 2
        cy = y + height / 2
        rx = width / 2
        ry = height / 2
        n = 5
        points = []
        for i in range(n + 1):
            t = 2 * math.pi * i / n - math.pi / 2
            points.append({
                "x": max(0.0, min(1.0, cx + rx * math.cos(t))),
                "y": max(0.0, min(2.0, cy + ry * math.sin(t))),
            })
        return points

    return []


async def draw_shape(
    shape: str,
    points: list[dict[str, float]],
    stroke_color: str = "#111111",
    stroke_width: float = 2.0,
    fill_color: str | None = None,
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    animate: bool = True,
    tool_context: ToolContext | None = None,
) -> dict:
    """
    Draw a shape on the canvas using explicit vertex points.

    `shape` is a rendering hint for the frontend. `points` is a list of
    {x, y} dicts in normalised [0, 1] coordinates. At least 2 points are
    required. For closed shapes, repeat the first point at the end.

    Common shapes and their point counts:
    - line:           2 pts
    - rectangle:      5 pts (closed: first == last)
    - square:         5 pts (closed, equal sides)
    - triangle:       4 pts (closed isoceles)
    - right_triangle: 4 pts (right angle at bottom-left, closed)
    - ellipse:        49 pts (48 segments + closing point)
    - polygon:        6 pts (regular 5-gon + closing point)
    """
    data = DrawShapeInput.model_validate(
        {
            "shape": shape,
            "points": points,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "fill_color": fill_color,
                "opacity": opacity,
                "z_index": z_index,
                "delay_ms": delay_ms,
                "animate": animate,
            },
        }
    )
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="draw_shape",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def draw_text(
    text: str,
    x: float,
    y: float,
    font_size: int = 24,
    stroke_color: str = "#111111",
    stroke_width: float = 2.0,
    fill_color: str | None = None,
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    animate: bool = True,
    tool_context: ToolContext | None = None,
) -> dict:
    data = DrawTextInput.model_validate(
        {
            "text": text,
            "x": x,
            "y": y,
            "font_size": font_size,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "fill_color": fill_color,
                "opacity": opacity,
                "z_index": z_index,
                "delay_ms": delay_ms,
                "animate": animate,
            },
        }
    )
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="draw_text",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def draw_freehand(
    points: list[dict[str, float]],
    stroke_color: str = "#111111",
    stroke_width: float = 2.0,
    fill_color: str | None = None,
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    animate: bool = True,
    tool_context: ToolContext | None = None,
) -> dict:
    data = DrawFreehandInput.model_validate(
        {
            "points": points,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "fill_color": fill_color,
                "opacity": opacity,
                "z_index": z_index,
                "delay_ms": delay_ms,
                "animate": animate,
            },
        }
    )
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="draw_freehand",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def highlight_region(
    element_ids: list[str],
    highlight_type: str = "marker",
    padding: float = 0.02,
    stroke_color: str = "rgba(255,255,0,0.8)",
    stroke_width: float = 2.0,
    fill_color: str | None = "rgba(255,255,0,0.25)",
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    animate: bool = True,
    tool_context: ToolContext | None = None,
) -> dict:
    """
    Highlight one or more existing canvas elements.

    `element_ids` must be IDs returned by a previous draw call.
    `highlight_type` controls the visual:
    - "marker"       — semi-transparent rectangle (default)
    - "circle"       — ellipse outline
    - "pointer"      — ellipse + arrow beneath
    - "color_change" — applies stroke_color/fill_color to the target elements
    """
    data = HighlightInput.model_validate(
        {
            "element_ids": element_ids,
            "highlight_type": highlight_type,
            "padding": padding,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "fill_color": fill_color,
                "opacity": opacity,
                "z_index": z_index,
                "delay_ms": delay_ms,
                "animate": animate,
            },
        }
    )
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="highlight_region",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def clear_canvas(tool_context: ToolContext | None = None) -> dict:
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="clear_canvas",
        payload={"mode": "full"},
    )
    return result_to_dict(result)
