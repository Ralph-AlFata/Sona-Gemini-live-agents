"""Core drawing primitives."""

from __future__ import annotations

import logging
import math

from google.adk.tools import ToolContext

from agent.tools._canonical import enforce_canonical_labels
from agent.tools._cursor import BBox, LEFT_MARGIN, RIGHT_EDGE
from agent.tools._cursor_store import clear_cursor, get_cursor
from agent.tools._shared import execute_tool_command, resolve_session_id, result_to_dict
from agent.tools._trace import emit_draw_trace
from agent.tools.models import DrawFreehandInput, DrawShapeInput, DrawTextInput, HighlightInput

logger = logging.getLogger(__name__)

_AUTO_SHAPE_DEFAULT_WIDTH = 0.25
_VALID_NEXT_DIRECTIONS = {"below", "right", "left", "below_all"} # TODO: Should add top too
_MAX_AUTO_SHAPE_WIDTH = max(0.1, RIGHT_EDGE - LEFT_MARGIN)
_MAX_AUTO_SHAPE_HEIGHT = 2.0
_SUPPORTED_SHAPES = {
    "rectangle",
    "ellipse",
    "circle",
    "line",
    "triangle",
    "right_triangle",
    "polygon",
    "square",
}


def _restore_cursor_from_snapshot(cursor, snapshot: dict[str, float]) -> None:
    restored = cursor.from_snapshot_dict(snapshot)
    cursor.x = restored.x
    cursor.y = restored.y
    cursor.row_start_y = restored.row_start_y
    cursor.row_max_bottom = restored.row_max_bottom
    cursor.row_start_x = restored.row_start_x
    cursor.column_max_right = restored.column_max_right
    cursor.bottom_edge = restored.bottom_edge


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


def _estimate_text_size(text: str, font_size: int) -> tuple[float, float]:
    width = min(0.8, 0.012 * len(text) * (font_size / 24))
    height = min(0.25, 0.03 * (font_size / 24))
    return width, height


def _points_bbox(points: list[dict[str, float]]) -> dict[str, float]:
    min_x = min(point["x"] for point in points)
    max_x = max(point["x"] for point in points)
    min_y = min(point["y"] for point in points)
    max_y = max(point["y"] for point in points)
    return {
        "x": round(min_x, 4),
        "y": round(min_y, 4),
        "width": round(max_x - min_x, 4),
        "height": round(max_y - min_y, 4),
    }


def _normalize_auto_shape_size(width: float, height: float) -> tuple[float, float, bool]:
    """
    Normalize potentially pixel/percent-like dimensions to canvas units.

    Returns (normalized_width, normalized_height, changed).
    """
    w = max(width, 0.001)
    h = max(height, 0.001)
    if w <= _MAX_AUTO_SHAPE_WIDTH and h <= _MAX_AUTO_SHAPE_HEIGHT:
        return w, h, False

    for factor in (0.01, 0.001, 0.1):
        scaled_w = w * factor
        scaled_h = h * factor
        if scaled_w <= _MAX_AUTO_SHAPE_WIDTH and scaled_h <= _MAX_AUTO_SHAPE_HEIGHT:
            return max(0.02, scaled_w), max(0.02, scaled_h), True

    scale = max(
        w / _MAX_AUTO_SHAPE_WIDTH,
        h / _MAX_AUTO_SHAPE_HEIGHT,
        1.0,
    )
    normalized_w = max(0.02, min(_MAX_AUTO_SHAPE_WIDTH, w / scale))
    normalized_h = max(0.02, min(_MAX_AUTO_SHAPE_HEIGHT, h / scale))
    return normalized_w, normalized_h, True


def _clamp_points_to_canvas(
    raw_points: list[dict[str, float]],
) -> tuple[list[dict[str, float]], bool]:
    """Clamp points into normalized canvas bounds [0,1]x[0,2]."""
    clamped: list[dict[str, float]] = []
    changed = False

    for point in raw_points:
        x_raw = point.get("x")
        y_raw = point.get("y")
        if not isinstance(x_raw, (int, float)) or not isinstance(y_raw, (int, float)):
            return raw_points, False

        x = float(x_raw)
        y = float(y_raw)
        nx = min(1.0, max(0.0, x))
        ny = min(2.0, max(0.0, y))
        if nx != x or ny != y:
            changed = True
        clamped.append({"x": nx, "y": ny})

    return clamped, changed


async def draw_shape(
    shape: str,
    points: list[dict[str, float]] | None = None,
    width: float | None = None,
    height: float | None = None,
    next: str = "below",
    labels: list[str] | None = None,
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
    Draw a shape on the canvas.

    Two placement modes:
    - AUTOMATIC (recommended): Omit `points`. Optionally provide `width` and
      `height`; otherwise sensible defaults are used. The shape is placed at
      the current cursor and the cursor advances.
    - MANUAL: Provide explicit `points`. The cursor is not moved.

    `next` controls cursor flow after automatic placement:
    "below" (default), "right", "left", or "below_all".

    Invocation condition: Call ONLY when you need to draw a NEW shape that
    does not already exist on the canvas. Never call with the same shape
    and points as a previous successful call in this session.

    `labels` is optional. Each entry maps by index to a side:
    `labels[0]` labels the segment from `points[0]` to `points[1]`,
    `labels[1]` labels the segment from `points[1]` to `points[2]`, etc.
    Use empty strings to skip sides you do not want to label.
    """
    if next not in _VALID_NEXT_DIRECTIONS:
        raise ValueError(f"next must be one of {sorted(_VALID_NEXT_DIRECTIONS)}")

    session_id = resolve_session_id(tool_context)
    used_cursor = False
    cursor = None
    normalized_shape_size = False
    normalized_points = False

    if points is None:
        if shape not in _SUPPORTED_SHAPES:
            raise ValueError(f"unsupported shape '{shape}'")
        if width is not None and width <= 0:
            raise ValueError("width must be greater than 0")
        if height is not None and height <= 0:
            raise ValueError("height must be greater than 0")
        cursor = get_cursor(session_id)
        cursor_before = cursor.to_snapshot_dict()
        auto_width = _AUTO_SHAPE_DEFAULT_WIDTH if width is None else width
        auto_height = auto_width if height is None else height
        auto_width, auto_height, normalized_shape_size = _normalize_auto_shape_size(
            auto_width,
            auto_height,
        )
        bbox = cursor.place(auto_width, auto_height, next_direction=next)
        points = shape_to_points(shape, bbox.x, bbox.y, bbox.width, bbox.height)
        if not points:
            return {
                "status": "error",
                "operation": "draw_shape",
                "message": f"cannot auto-generate points for shape '{shape}'",
            }
        width = auto_width
        height = auto_height
        used_cursor = True
    else:
        points, normalized_points = _clamp_points_to_canvas(points)

    data = DrawShapeInput.model_validate(
        {
            "shape": shape,
            "points": points,
            "width": width,
            "height": height,
            "next": next,
            "labels": labels or [],
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
    if data.labels:
        original_labels = list(data.labels)
        remapped_labels = enforce_canonical_labels(
            data.shape,
            [
                {"x": point.x, "y": point.y}
                for point in data.points
            ],
            original_labels,
        )
        if remapped_labels != original_labels:
            logger.info(
                "CANONICAL_LABEL_REMAP session_id=%s shape=%s original=%s remapped=%s",
                session_id,
                data.shape,
                original_labels,
                remapped_labels,
            )
            data.labels = remapped_labels
    result = await execute_tool_command(
        session_id=session_id,
        operation="draw_shape",
        payload=data.model_dump(mode="json", exclude={"labels", "width", "height", "next"}),
    )
    response = result_to_dict(result)
    shape_id = result.created_element_ids[0] if result.created_element_ids else None
    label_ids: list[str] = []

    if used_cursor and cursor is not None and result.deduplicated:
        _restore_cursor_from_snapshot(cursor, cursor_before)

    if shape_id and data.labels:
        label_result = await execute_tool_command(
            session_id=session_id,
            operation="set_shape_labels",
            payload={
                "element_id": shape_id,
                "labels": data.labels,
                "font_size": 22,
            },
        )
        label_ids = label_result.created_element_ids
        response["created_element_ids"].extend(label_result.created_element_ids)
        response["failed_operations"].extend(label_result.failed_operations)
        response["applied_count"] += label_result.applied_count

    response["shape_id"] = shape_id
    response["label_ids"] = label_ids
    response["element_bbox"] = _points_bbox(
        [
            {"x": point.x, "y": point.y}
            for point in data.points
        ]
    )
    if used_cursor and cursor is not None:
        response["cursor_after"] = cursor.to_dict()
        if not result.deduplicated:
            emit_draw_trace({"cursor_state": cursor.to_snapshot_dict()})
    if normalized_shape_size:
        response["placement_warning"] = (
            "Shape width/height were auto-normalized to canvas coordinates."
        )
    if normalized_points:
        response["points_warning"] = (
            "Some shape points were clamped into canvas bounds."
        )
    return response


async def draw_text(
    text: str,
    x: float | None = None,
    y: float | None = None,
    next: str = "below",
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
    """Place text on the canvas.

    Two placement modes:
    - AUTOMATIC (recommended): Omit `x` and `y`; text is placed at the current
      cursor and the cursor advances.
    - MANUAL: Provide explicit `x` and `y`; cursor is not moved.
    """
    if next not in _VALID_NEXT_DIRECTIONS:
        raise ValueError(f"next must be one of {sorted(_VALID_NEXT_DIRECTIONS)}")

    session_id = resolve_session_id(tool_context)
    used_cursor = False
    cursor = None
    normalized_partial_coords = False

    # LLMs sometimes emit only one coordinate. Normalize that to automatic
    # placement instead of failing the whole live turn.
    if (x is None) != (y is None):
        x = None
        y = None
        normalized_partial_coords = True

    if x is None and y is None:
        cursor = get_cursor(session_id)
        cursor_before = cursor.to_snapshot_dict()
        text_width, text_height = _estimate_text_size(text, font_size)
        bbox = cursor.place(text_width, text_height, next_direction=next)
        x = bbox.x
        y = bbox.y
        used_cursor = True

    data = DrawTextInput.model_validate(
        {
            "text": text,
            "x": x,
            "y": y,
            "next": next,
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
        session_id=session_id,
        operation="draw_text",
        payload=data.model_dump(mode="json", exclude={"next"}),
    )
    response = result_to_dict(result)
    if used_cursor and cursor is not None and result.deduplicated:
        _restore_cursor_from_snapshot(cursor, cursor_before)
    text_width, text_height = _estimate_text_size(text, font_size)
    response["element_bbox"] = {
        "x": round(data.x if data.x is not None else 0.0, 4),
        "y": round(data.y if data.y is not None else 0.0, 4),
        "width": round(text_width, 4),
        "height": round(text_height, 4),
    }
    if used_cursor and cursor is not None:
        response["cursor_after"] = cursor.to_dict()
        if not result.deduplicated:
            emit_draw_trace({"cursor_state": cursor.to_snapshot_dict()})
    if normalized_partial_coords:
        response["placement_warning"] = (
            "Partial text coordinates were ignored; used automatic cursor placement."
        )
    return response


async def draw_freehand(
    points: list[dict[str, float]],
    next: str = "below",
    stroke_color: str = "#111111",
    stroke_width: float = 2.0,
    fill_color: str | None = None,
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    animate: bool = True,
    tool_context: ToolContext | None = None,
) -> dict:
    """Draw a freehand stroke on the canvas.

    Invocation condition: Call ONLY for NEW freehand strokes. Do not redraw
    a stroke that already has a confirmed element ID.
    """
    if next not in _VALID_NEXT_DIRECTIONS:
        raise ValueError(f"next must be one of {sorted(_VALID_NEXT_DIRECTIONS)}")

    session_id = resolve_session_id(tool_context)
    data = DrawFreehandInput.model_validate(
        {
            "points": points,
            "next": next,
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
        session_id=session_id,
        operation="draw_freehand",
        payload=data.model_dump(mode="json", exclude={"next"}),
    )
    response = result_to_dict(result)
    bbox_payload = _points_bbox(
        [
            {"x": point.x, "y": point.y}
            for point in data.points
        ]
    )
    bbox = BBox(
        x=bbox_payload["x"],
        y=bbox_payload["y"],
        width=bbox_payload["width"],
        height=bbox_payload["height"],
    )
    cursor = get_cursor(session_id)
    if not result.deduplicated:
        cursor.advance_from_bbox(bbox, next_direction=next)
    response["cursor_after"] = cursor.to_dict()
    response["element_bbox"] = bbox_payload
    if not result.deduplicated:
        emit_draw_trace({"cursor_state": cursor.to_snapshot_dict()})
    return response


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

    Invocation condition: Call ONLY when highlighting elements not already
    highlighted. Do not re-highlight the same element_ids with the same type.
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
    session_id = resolve_session_id(tool_context)
    clear_cursor(session_id)
    cursor = get_cursor(session_id)
    emit_draw_trace({"cursor_state": cursor.to_snapshot_dict()})
    result = await execute_tool_command(
        session_id=session_id,
        operation="clear_canvas",
        payload={"mode": "full"},
    )
    response = result_to_dict(result)
    response["cursor_after"] = cursor.to_dict()
    return response
