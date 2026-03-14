"""Drawing command application + DSL message translation."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

from models import (
    ClearPayload,
    DSLMessage,
    DeleteElementsPayload,
    DrawCommandFailure,
    DrawCommandRequest,
    DrawFreehandPayload,
    DrawResponse,
    DrawShapePayload,
    DrawTextPayload,
    EraseRegionPayload,
    GraphViewportPayload,
    HighlightPayload,
    MoveElementsPayload,
    ResizeElementsPayload,
    SetShapeLabelsPayload,
    StylePayload,
    UpdatePointsPayload,
    UpdateStylePayload,
)
from store import BBox, ElementStore, StoredElement


def _next_message_id() -> str:
    return uuid4().hex[:8]


def _next_element_id() -> str:
    return f"el_{uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _clamp(value: float, upper: float = 1.0) -> float:
    return max(0.0, min(upper, value))


_Y_MAX = 2.0  # width-uniform coords: y can exceed 1.0 on non-square screens


def _bbox_intersects(a: BBox, b: BBox) -> bool:
    return not (
        a.x + a.width < b.x
        or b.x + b.width < a.x
        or a.y + a.height < b.y
        or b.y + b.height < a.y
    )


def _bbox_from_points(points: list[dict[str, float]]) -> BBox:
    xs = [float(point["x"]) for point in points]
    ys = [float(point["y"]) for point in points]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    return BBox(min_x, min_y, max(max_x - min_x, 0.001), max(max_y - min_y, 0.001))


def _style_to_dict(style: StylePayload) -> dict:
    return {
        "stroke_color": style.stroke_color,
        "stroke_width": style.stroke_width,
        "fill_color": style.fill_color,
        "opacity": style.opacity,
        "z_index": style.z_index,
        "delay_ms": style.delay_ms,
        "animate": style.animate,
    }


def _build_shape_element(payload: DrawShapePayload) -> tuple[dict, BBox]:
    """Build a stored shape element. BBox is computed from the vertex points."""
    points_raw = [p.model_dump() for p in payload.points]
    xs = [p["x"] for p in points_raw]
    ys = [p["y"] for p in points_raw]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    draw_payload = {
        "shape": payload.shape,
        "points": points_raw,
        "style": _style_to_dict(payload.style),
    }
    return draw_payload, BBox(min_x, min_y, max(max_x - min_x, 0.001), max(max_y - min_y, 0.001))

def _build_text_element(payload: DrawTextPayload) -> tuple[dict, BBox]:
    approx_width = min(0.8, 0.012 * len(payload.text) * (payload.font_size / 24))
    approx_height = min(0.25, 0.03 * (payload.font_size / 24))
    draw_payload = {
        "text": payload.text,
        "x": payload.x,
        "y": payload.y,
        "font_size": payload.font_size,
        "style": _style_to_dict(payload.style),
    }
    return draw_payload, BBox(payload.x, payload.y, approx_width, approx_height)


def _estimate_text_bbox(x: float, y: float, text: str, font_size: int) -> BBox:
    approx_width = min(0.8, 0.012 * len(text) * (font_size / 24))
    approx_height = min(0.25, 0.03 * (font_size / 24))
    return BBox(x, y, approx_width, approx_height)

# TODO: Check why when we ask it to draw an S-shaped line, it gives us this weird thing
def _build_freehand_element(payload: DrawFreehandPayload) -> tuple[dict, BBox]:
    xs = [point.x for point in payload.points]
    ys = [point.y for point in payload.points]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    draw_payload = {
        "points": [point.model_dump() for point in payload.points],
        "style": _style_to_dict(payload.style),
    }
    return draw_payload, BBox(min_x, min_y, max(max_x - min_x, 0.001), max(max_y - min_y, 0.001))


def _translate_style_for_frontend(style: dict) -> dict:
    return {
        "color": style.get("stroke_color", "#111111"),
        "stroke_width": style.get("stroke_width", 2.0),
        "fill_color": style.get("fill_color"),
        "opacity": style.get("opacity", 1.0),
        "z_index": style.get("z_index", 0),
        "delay_ms": style.get("delay_ms", 30),
        "animate": bool(style.get("animate", True)),
    }


def element_to_frontend_payload(element: StoredElement) -> dict:
    """
    Convert a stored element payload into the flattened frontend DSL shape.

    Stored elements keep style in nested `payload.style`; `element_created`
    messages expect style fields flattened (color/stroke_width/etc).
    """
    payload = dict(element.payload)
    raw_style = payload.pop("style", {})
    style = dict(raw_style) if isinstance(raw_style, dict) else {}
    translated = _translate_style_for_frontend(style)
    for key, value in translated.items():
        payload.setdefault(key, value)
    return payload


def _create_message(command: DrawCommandRequest, message_type: str, payload: dict) -> DSLMessage:
    return DSLMessage(
        id=_next_message_id(),
        command_id=command.command_id,
        session_id=command.session_id,
        type=message_type,
        payload=payload,
    )


def _shape_vertices(points: list[dict[str, float]]) -> list[dict[str, float]]:
    if len(points) > 2 and points[0] == points[-1]:
        return points[:-1]
    return points


def _shape_centroid(points: list[dict[str, float]]) -> tuple[float, float]:
    vertices = _shape_vertices(points)
    count = max(len(vertices), 1)
    return (
        sum(point["x"] for point in vertices) / count,
        sum(point["y"] for point in vertices) / count,
    )


def _line_label_anchor(p1: dict[str, float], p2: dict[str, float], offset: float = 0.025) -> tuple[float, float]:
    dx = p2["x"] - p1["x"]
    dy = p2["y"] - p1["y"]
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        raise ValueError("cannot place a label on a zero-length side")

    nx = -dy / length
    ny = dx / length
    if abs(dx) >= abs(dy):
        if ny > 0:
            nx = -nx
            ny = -ny
    elif nx > 0:
        nx = -nx
        ny = -ny

    mid_x = (p1["x"] + p2["x"]) / 2
    mid_y = (p1["y"] + p2["y"]) / 2
    return mid_x + (nx * offset), mid_y + (ny * offset)


def _side_label_anchor(
    points: list[dict[str, float]],
    side_index: int,
    offset: float = 0.025,
) -> tuple[float, float]:
    p1 = points[side_index]
    p2 = points[side_index + 1]
    dx = p2["x"] - p1["x"]
    dy = p2["y"] - p1["y"]
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        raise ValueError(f"cannot place a label on zero-length side {side_index}")

    mid_x = (p1["x"] + p2["x"]) / 2
    mid_y = (p1["y"] + p2["y"]) / 2
    if len(points) == 2:
        return _line_label_anchor(p1, p2, offset)

    centroid_x, centroid_y = _shape_centroid(points)
    normal_a = (-dy / length, dx / length)
    normal_b = (dy / length, -dx / length)
    away_a = ((mid_x + normal_a[0]) - centroid_x) ** 2 + ((mid_y + normal_a[1]) - centroid_y) ** 2
    away_b = ((mid_x + normal_b[0]) - centroid_x) ** 2 + ((mid_y + normal_b[1]) - centroid_y) ** 2
    nx, ny = normal_a if away_a >= away_b else normal_b
    return mid_x + (nx * offset), mid_y + (ny * offset)


def _label_text_origin(
    points: list[dict[str, float]],
    side_index: int,
    text: str,
    font_size: int,
) -> tuple[float, float]:
    anchor_x, anchor_y = _side_label_anchor(points, side_index)
    bbox = _estimate_text_bbox(0.0, 0.0, text, font_size)
    return (
        _clamp(anchor_x - (bbox.width / 2), max(0.0, 1.0 - bbox.width)),
        _clamp(anchor_y - (bbox.height / 2), max(0.0, _Y_MAX - bbox.height)),
    )


def _build_shape_label_payload(
    shape_element: StoredElement,
    side_index: int,
    text: str,
    font_size: int,
) -> tuple[dict, BBox]:
    points = shape_element.payload.get("points", [])
    x, y = _label_text_origin(points, side_index, text, font_size)
    shape_style = shape_element.payload.get("style", {})
    draw_payload = {
        "text": text,
        "x": x,
        "y": y,
        "font_size": font_size,
        "style": {
            "stroke_color": shape_style.get("stroke_color", "#111111"),
            "stroke_width": max(1.0, min(float(shape_style.get("stroke_width", 2.0)), 2.0)),
            "fill_color": None,
            "opacity": shape_style.get("opacity", 1.0),
            "z_index": int(shape_style.get("z_index", 0)) + 1,
            "delay_ms": int(shape_style.get("delay_ms", 30)),
            "animate": bool(shape_style.get("animate", True)),
        },
        "attached_shape_id": shape_element.element_id,
        "side_index": side_index,
        "label_kind": "shape_side",
    }
    return draw_payload, _estimate_text_bbox(x, y, text, font_size)


def _label_entries(shape_element: StoredElement) -> list[dict]:
    entries = shape_element.payload.get("side_labels", [])
    return entries if isinstance(entries, list) else []


async def _sync_shape_label_positions(
    command: DrawCommandRequest,
    store: ElementStore,
    session_elements: dict[str, StoredElement],
    shape_element: StoredElement,
) -> list[DSLMessage]:
    transformed: list[dict] = []
    for entry in _label_entries(shape_element):
        if not isinstance(entry, dict):
            continue
        label_id = entry.get("element_id")
        text = entry.get("text")
        side_index = entry.get("side_index")
        font_size = entry.get("font_size", 22)
        if not isinstance(label_id, str) or not isinstance(text, str) or not isinstance(side_index, int):
            continue
        label_element = session_elements.get(label_id)
        if label_element is None:
            continue
        draw_payload, bbox = _build_shape_label_payload(shape_element, side_index, text, int(font_size))
        label_element.payload = draw_payload
        label_element.bbox = bbox
        await store.put_element(command.session_id, label_element)
        transformed.append(
            {
                "element_id": label_element.element_id,
                "element_type": "text",
                "payload": {
                    "text": draw_payload["text"],
                    "x": draw_payload["x"],
                    "y": draw_payload["y"],
                    "font_size": draw_payload["font_size"],
                    **_translate_style_for_frontend(draw_payload["style"]),
                },
            }
        )
    return [_create_message(command, "elements_transformed", {"elements": transformed})] if transformed else []


def _move_bbox(bbox: BBox, dx: float, dy: float) -> BBox:
    """
    Translate a bounding box by (dx, dy) in normalised coordinates.
    The box dimensions are preserved; only the origin shifts.
    Used by _move_payload to keep the stored BBox in sync after a move.
    """
    return BBox(x=_clamp(bbox.x + dx), y=_clamp(bbox.y + dy, _Y_MAX), width=bbox.width, height=bbox.height)


def _resize_bbox(bbox: BBox, sx: float, sy: float) -> BBox:
    """
    Scale a bounding box around its centre by (sx, sy).
    The centre stays fixed; width/height grow or shrink proportionally.
    Used by _resize_payload to keep the stored BBox in sync after a resize.
    """
    cx = bbox.x + (bbox.width / 2)
    cy = bbox.y + (bbox.height / 2)
    nw = min(1.0, bbox.width * sx)
    nh = min(_Y_MAX, bbox.height * sy)
    return BBox(
        x=_clamp(cx - (nw / 2)),
        y=_clamp(cy - (nh / 2), _Y_MAX),
        width=nw,
        height=nh,
    )


def _move_payload(element: StoredElement, dx: float, dy: float) -> None:
    if element.element_type == "freehand" or "points" in element.payload:
        points = []
        for point in element.payload["points"]:
            points.append({"x": _clamp(float(point["x"]) + dx), "y": _clamp(float(point["y"]) + dy, _Y_MAX)})
        element.payload["points"] = points
        xs = [point["x"] for point in points]
        ys = [point["y"] for point in points]
        element.bbox = BBox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        return

    if {"x", "y"}.issubset(element.payload):
        element.payload["x"] = _clamp(float(element.payload["x"]) + dx)
        element.payload["y"] = _clamp(float(element.payload["y"]) + dy, _Y_MAX)

    element.bbox = _move_bbox(element.bbox, dx, dy)


def _resize_payload(element: StoredElement, scale_x: float, scale_y: float) -> None:
    new_bbox = _resize_bbox(element.bbox, scale_x, scale_y)

    if element.element_type == "freehand" or "points" in element.payload:
        old_bbox = element.bbox
        if old_bbox.width == 0 or old_bbox.height == 0:
            element.bbox = new_bbox
            return
        points = []
        for point in element.payload["points"]:
            rel_x = (float(point["x"]) - old_bbox.x) / old_bbox.width
            rel_y = (float(point["y"]) - old_bbox.y) / old_bbox.height
            points.append(
                {
                    "x": _clamp(new_bbox.x + (rel_x * new_bbox.width)),
                    "y": _clamp(new_bbox.y + (rel_y * new_bbox.height), _Y_MAX),
                }
            )
        element.payload["points"] = points
        element.bbox = new_bbox
        return

    if "width" in element.payload:
        element.payload["width"] = new_bbox.width
    if "height" in element.payload:
        element.payload["height"] = new_bbox.height
    if "x" in element.payload:
        element.payload["x"] = new_bbox.x
    if "y" in element.payload:
        element.payload["y"] = new_bbox.y

    element.bbox = new_bbox


def _update_style_payload(element: StoredElement, update: UpdateStylePayload) -> None:
    style = element.payload.get("style", {})
    if update.stroke_color is not None:
        style["stroke_color"] = update.stroke_color
    if update.stroke_width is not None:
        style["stroke_width"] = update.stroke_width
    if update.fill_color is not None:
        style["fill_color"] = update.fill_color
    if update.opacity is not None:
        style["opacity"] = update.opacity
    if update.z_index is not None:
        style["z_index"] = update.z_index
    if update.delay_ms is not None:
        style["delay_ms"] = update.delay_ms
    element.payload["style"] = style


def _apply_style(element: StoredElement, style: StylePayload) -> None:
    """Overwrite all style fields on an element from a StylePayload."""
    element.payload["style"] = _style_to_dict(style)


def _delete_elements_from_snapshot(
    session_elements: dict[str, StoredElement],
    element_ids: list[str],
) -> tuple[list[str], list[DrawCommandFailure]]:
    """
    Remove elements by ID from the in-memory snapshot dict.

    Returns (deleted_ids, failures). The caller is responsible for
    calling store.delete_element() for each deleted ID to persist the change.
    """
    deleted: list[str] = []
    failures: list[DrawCommandFailure] = []
    pending = list(dict.fromkeys(element_ids))
    visited: set[str] = set()
    while pending:
        eid = pending.pop(0)
        if eid in visited:
            continue
        visited.add(eid)
        element = session_elements.get(eid)
        if element is None:
            failures.append(DrawCommandFailure(element_id=eid, reason="element not found"))
            continue
        if element.element_type == "shape":
            for entry in _label_entries(element):
                label_id = entry.get("element_id") if isinstance(entry, dict) else None
                if isinstance(label_id, str):
                    pending.append(label_id)
        session_elements.pop(eid, None)
        deleted.append(eid)
    return deleted, failures


def _ellipse_points(cx: float, cy: float, rx: float, ry: float, segments: int = 40) -> list[dict]:
    """Generate normalised ellipse points for freehand rendering."""
    points = []
    for i in range(segments + 1):
        theta = 2 * math.pi * i / segments
        points.append({
            "x": _clamp(cx + rx * math.cos(theta)),
            "y": _clamp(cy + ry * math.sin(theta), _Y_MAX),
        })
    return points


async def apply_command(
    command: DrawCommandRequest,
    store: ElementStore,
) -> tuple[list[DSLMessage], DrawResponse]:
    """
    Apply a single draw command to the element store and produce DSL messages.

    Loads the current session elements from the store, applies the requested
    operation in memory, persists each change back to the store (via
    put_element / delete_element / clear_session), generates DSL messages for
    each state change, and returns them alongside a DrawResponse summary.

    DSL messages are later broadcast over WebSocket to connected frontend clients,
    which render the canvas in real-time based on message type.
    """
    logger.info(
        "DSL_APPLY_COMMAND session_id=%s operation=%s command_id=%s element_id=%s payload_type=%s",
        command.session_id,
        command.operation,
        command.command_id,
        command.element_id,
        type(command.payload).__name__,
    )

    session_elements = await store.get_all_elements(command.session_id)
    messages: list[DSLMessage] = []
    failures: list[DrawCommandFailure] = []
    created_element_ids: list[str] = []
    applied_count = 0

    payload = command.payload

    if isinstance(payload, ClearPayload):
        await store.clear_session(command.session_id)
        session_elements.clear()
        messages.append(_create_message(command, "clear", {"mode": "full"}))
        applied_count = 1

    elif isinstance(payload, GraphViewportPayload):
        messages.append(
            _create_message(
                command,
                "graph_viewport_set",
                {"viewport": payload.model_dump(mode="json")},
            )
        )
        applied_count = 1

    elif isinstance(payload, DrawShapePayload):
        element_id = command.element_id or _next_element_id()
        draw_payload, bbox = _build_shape_element(payload)
        draw_payload["created_at"] = _now_iso()
        draw_payload["side_labels"] = []
        element = StoredElement(
            element_id=element_id,
            element_type="shape",
            payload=draw_payload,
            bbox=bbox,
        )
        session_elements[element_id] = element
        await store.put_element(command.session_id, element)
        created_element_ids.append(element_id)
        applied_count = 1
        messages.append(
            _create_message(
                command,
                "element_created",
                {
                    "element_id": element_id,
                    "element_type": "shape",
                    "payload": {
                        "shape": draw_payload["shape"],
                        "points": draw_payload["points"],
                        **_translate_style_for_frontend(draw_payload["style"]),
                    },
                },
            )
        )

    elif isinstance(payload, DrawTextPayload):
        element_id = command.element_id or _next_element_id()
        draw_payload, bbox = _build_text_element(payload)
        draw_payload["created_at"] = _now_iso()
        element = StoredElement(
            element_id=element_id,
            element_type="text",
            payload=draw_payload,
            bbox=bbox,
        )
        session_elements[element_id] = element
        await store.put_element(command.session_id, element)
        created_element_ids.append(element_id)
        applied_count = 1
        messages.append(
            _create_message(
                command,
                "element_created",
                {
                    "element_id": element_id,
                    "element_type": "text",
                    "payload": {
                        "text": draw_payload["text"],
                        "x": draw_payload["x"],
                        "y": draw_payload["y"],
                        "font_size": draw_payload["font_size"],
                        **_translate_style_for_frontend(draw_payload["style"]),
                    },
                },
            )
        )

    elif isinstance(payload, DrawFreehandPayload):
        element_id = command.element_id or _next_element_id()
        draw_payload, bbox = _build_freehand_element(payload)
        draw_payload["created_at"] = _now_iso()
        element = StoredElement(
            element_id=element_id,
            element_type="freehand",
            payload=draw_payload,
            bbox=bbox,
        )
        session_elements[element_id] = element
        await store.put_element(command.session_id, element)
        created_element_ids.append(element_id)
        applied_count = 1
        messages.append(
            _create_message(
                command,
                "element_created",
                {
                    "element_id": element_id,
                    "element_type": "freehand",
                    "payload": {
                        "points": draw_payload["points"],
                        **_translate_style_for_frontend(draw_payload["style"]),
                    },
                },
            )
        )
    elif isinstance(payload, HighlightPayload):
        # Look up target elements and compute their union bounding box.
        target_elements = [
            session_elements[eid] for eid in payload.element_ids if eid in session_elements
        ]
        not_found = [eid for eid in payload.element_ids if eid not in session_elements]
        failures.extend(
            DrawCommandFailure(element_id=eid, reason="element not found") for eid in not_found
        )

        if target_elements:
            pad = payload.padding
            target_ids = [element.element_id for element in target_elements]
            xs_lo = [e.bbox.x for e in target_elements]
            ys_lo = [e.bbox.y for e in target_elements]
            xs_hi = [e.bbox.x + e.bbox.width for e in target_elements]
            ys_hi = [e.bbox.y + e.bbox.height for e in target_elements]
            ux = _clamp(min(xs_lo) - pad)
            uy = _clamp(min(ys_lo) - pad, _Y_MAX)
            ux2 = _clamp(max(xs_hi) + pad)
            uy2 = _clamp(max(ys_hi) + pad, _Y_MAX)
            uw = max(0.001, ux2 - ux)
            uh = max(0.001, uy2 - uy)
            style_dict = _style_to_dict(payload.style)

            if payload.highlight_type == "color_change":
                restyled = []
                for element in target_elements:
                    _apply_style(element, payload.style)
                    await store.put_element(command.session_id, element)
                    restyled.append({
                        "element_id": element.element_id,
                        "element_type": element.element_type,
                        "style": _translate_style_for_frontend(element.payload.get("style", {})),
                    })
                    applied_count += 1
                if restyled:
                    messages.append(_create_message(command, "elements_restyled", {"elements": restyled}))

            elif payload.highlight_type == "marker":
                eid = _next_element_id()
                h_payload = {
                    "x": ux,
                    "y": uy,
                    "width": uw,
                    "height": uh,
                    "style": style_dict,
                    "target_element_ids": target_ids,
                    "padding": pad,
                    "created_at": _now_iso(),
                }
                el = StoredElement(
                    element_id=eid,
                    element_type="highlight",
                    payload=h_payload,
                    bbox=BBox(ux, uy, uw, uh),
                )
                session_elements[eid] = el
                await store.put_element(command.session_id, el)
                created_element_ids.append(eid)
                applied_count = 1
                messages.append(_create_message(command, "element_created", {
                    "element_id": eid,
                    "element_type": "highlight",
                    "payload": {
                        "x": ux, "y": uy, "width": uw, "height": uh,
                        "target_element_ids": target_ids,
                        "padding": pad,
                        **_translate_style_for_frontend(style_dict),
                    },
                }))

            elif payload.highlight_type == "circle":
                cx = ux + uw / 2
                cy = uy + uh / 2
                pts = _ellipse_points(cx, cy, uw / 2, uh / 2)
                eid = _next_element_id()
                el = StoredElement(
                    element_id=eid,
                    element_type="freehand",
                    payload={
                        "points": pts,
                        "style": style_dict,
                        "highlight_kind": "circle",
                        "highlight_part": "ellipse",
                        "target_element_ids": target_ids,
                        "padding": pad,
                        "created_at": _now_iso(),
                    },
                    bbox=BBox(ux, uy, uw, uh),
                )
                session_elements[eid] = el
                await store.put_element(command.session_id, el)
                created_element_ids.append(eid)
                applied_count = 1
                messages.append(_create_message(command, "element_created", {
                    "element_id": eid,
                    "element_type": "freehand",
                    "payload": {
                        "points": pts,
                        "highlight_kind": "circle",
                        "highlight_part": "ellipse",
                        "target_element_ids": target_ids,
                        "padding": pad,
                        **_translate_style_for_frontend(style_dict),
                    },
                }))

            elif payload.highlight_type == "pointer":
                # Ellipse around the region.
                cx = ux + uw / 2
                cy = uy + uh / 2
                ellipse_pts = _ellipse_points(cx, cy, uw / 2, uh / 2)
                eid1 = _next_element_id()
                el1 = StoredElement(
                    element_id=eid1,
                    element_type="freehand",
                    payload={
                        "points": ellipse_pts,
                        "style": style_dict,
                        "highlight_kind": "pointer",
                        "highlight_part": "ellipse",
                        "target_element_ids": target_ids,
                        "padding": pad,
                        "created_at": _now_iso(),
                    },
                    bbox=BBox(ux, uy, uw, uh),
                )
                session_elements[eid1] = el1
                await store.put_element(command.session_id, el1)
                created_element_ids.append(eid1)
                messages.append(_create_message(command, "element_created", {
                    "element_id": eid1,
                    "element_type": "freehand",
                    "payload": {
                        "points": ellipse_pts,
                        "highlight_kind": "pointer",
                        "highlight_part": "ellipse",
                        "target_element_ids": target_ids,
                        "padding": pad,
                        **_translate_style_for_frontend(style_dict),
                    },
                }))

                # Arrow: vertical stem from below the ellipse up to its bottom edge.
                arrow_tip_y = _clamp(uy2, _Y_MAX)
                arrow_start_y = _clamp(uy2 + 0.07, _Y_MAX)
                if arrow_start_y < _Y_MAX and arrow_start_y > arrow_tip_y:
                    arrow_pts = [
                        {"x": cx, "y": arrow_start_y},
                        {"x": cx, "y": arrow_tip_y},
                    ]
                    eid2 = _next_element_id()
                    el2 = StoredElement(
                        element_id=eid2,
                        element_type="freehand",
                        payload={
                            "points": arrow_pts,
                            "style": style_dict,
                            "highlight_kind": "pointer",
                            "highlight_part": "arrow",
                            "target_element_ids": target_ids,
                            "padding": pad,
                            "created_at": _now_iso(),
                        },
                        bbox=BBox(cx, arrow_tip_y, 0.001, arrow_start_y - arrow_tip_y),
                    )
                    session_elements[eid2] = el2
                    await store.put_element(command.session_id, el2)
                    created_element_ids.append(eid2)
                    messages.append(_create_message(command, "element_created", {
                        "element_id": eid2,
                        "element_type": "freehand",
                        "payload": {
                            "points": arrow_pts,
                            "highlight_kind": "pointer",
                            "highlight_part": "arrow",
                            "target_element_ids": target_ids,
                            "padding": pad,
                            **_translate_style_for_frontend(style_dict),
                        },
                    }))

                applied_count = len(created_element_ids)

    elif isinstance(payload, DeleteElementsPayload):
        deleted, new_failures = _delete_elements_from_snapshot(session_elements, payload.element_ids)
        for eid in deleted:
            await store.delete_element(command.session_id, eid)
        failures.extend(new_failures)
        applied_count = len(deleted)
        if deleted:
            messages.append(_create_message(command, "elements_deleted", {"element_ids": deleted}))

    elif isinstance(payload, SetShapeLabelsPayload):
        shape_element = session_elements.get(payload.element_id)
        if shape_element is None:
            failures.append(DrawCommandFailure(element_id=payload.element_id, reason="element not found"))
        elif shape_element.element_type != "shape":
            failures.append(
                DrawCommandFailure(element_id=payload.element_id, reason="element is not a shape")
            )
        else:
            shape_kind = str(shape_element.payload.get("shape", ""))
            points = shape_element.payload.get("points", [])
            edge_count = len(points) - 1
            if shape_kind in {"circle", "ellipse"} and payload.labels:
                failures.append(
                    DrawCommandFailure(
                        element_id=payload.element_id,
                        reason=f"labels are not supported for shape '{shape_kind}'",
                    )
                )
            elif edge_count < 1:
                failures.append(
                    DrawCommandFailure(element_id=payload.element_id, reason="shape has no labelable sides")
                )
            elif len(payload.labels) > edge_count:
                failures.append(
                    DrawCommandFailure(
                        element_id=payload.element_id,
                        reason=f"labels can have at most {edge_count} entries for this shape",
                    )
                )
            else:
                prior_label_ids = [
                    entry["element_id"]
                    for entry in _label_entries(shape_element)
                    if isinstance(entry, dict) and isinstance(entry.get("element_id"), str)
                ]
                deleted_ids = [label_id for label_id in prior_label_ids if label_id in session_elements]
                for label_id in deleted_ids:
                    session_elements.pop(label_id, None)
                    await store.delete_element(command.session_id, label_id)
                if deleted_ids:
                    messages.append(
                        _create_message(command, "elements_deleted", {"element_ids": deleted_ids})
                    )

                new_entries: list[dict] = []
                for side_index, label_text in enumerate(payload.labels):
                    if not label_text.strip():
                        continue
                    label_id = _next_element_id()
                    draw_payload, bbox = _build_shape_label_payload(
                        shape_element,
                        side_index,
                        label_text,
                        payload.font_size,
                    )
                    label_element = StoredElement(
                        element_id=label_id,
                        element_type="text",
                        payload=draw_payload,
                        bbox=bbox,
                    )
                    session_elements[label_id] = label_element
                    await store.put_element(command.session_id, label_element)
                    created_element_ids.append(label_id)
                    new_entries.append(
                        {
                            "side_index": side_index,
                            "text": label_text,
                            "element_id": label_id,
                            "font_size": payload.font_size,
                        }
                    )
                    messages.append(
                        _create_message(
                            command,
                            "element_created",
                            {
                                "element_id": label_id,
                                "element_type": "text",
                                "payload": {
                                    "text": draw_payload["text"],
                                    "x": draw_payload["x"],
                                    "y": draw_payload["y"],
                                    "font_size": draw_payload["font_size"],
                                    **_translate_style_for_frontend(draw_payload["style"]),
                                },
                            },
                        )
                    )

                shape_element.payload["side_labels"] = new_entries
                await store.put_element(command.session_id, shape_element)
                applied_count = len(deleted_ids) + len(created_element_ids)

    elif isinstance(payload, EraseRegionPayload):
        target = BBox(payload.x, payload.y, payload.width, payload.height)
        ids_to_erase = [
            eid for eid, el in session_elements.items()
            if _bbox_intersects(el.bbox, target)
        ]
        deleted, _ = _delete_elements_from_snapshot(session_elements, ids_to_erase)
        for eid in deleted:
            await store.delete_element(command.session_id, eid)
        applied_count = len(deleted)
        messages.append(_create_message(command, "elements_deleted", {"element_ids": deleted}))

    elif isinstance(payload, MoveElementsPayload):
        transformed: list[dict] = []
        for element_id in payload.element_ids:
            element = session_elements.get(element_id)
            if element is None:
                failures.append(DrawCommandFailure(element_id=element_id, reason="element not found"))
                continue
            _move_payload(element, payload.dx, payload.dy)
            await store.put_element(command.session_id, element)
            transformed.append({
                "element_id": element_id,
                "element_type": element.element_type,
                "payload": element.payload,
            })
            applied_count += 1
            if element.element_type == "shape":
                messages.extend(
                    await _sync_shape_label_positions(command, store, session_elements, element)
                )
        if transformed:
            messages.append(_create_message(command, "elements_transformed", {"elements": transformed}))

    elif isinstance(payload, ResizeElementsPayload):
        transformed = []
        for element_id in payload.element_ids:
            element = session_elements.get(element_id)
            if element is None:
                failures.append(DrawCommandFailure(element_id=element_id, reason="element not found"))
                continue
            _resize_payload(element, payload.scale_x, payload.scale_y)
            await store.put_element(command.session_id, element)
            transformed.append({
                "element_id": element_id,
                "element_type": element.element_type,
                "payload": element.payload,
            })
            applied_count += 1
            if element.element_type == "shape":
                messages.extend(
                    await _sync_shape_label_positions(command, store, session_elements, element)
                )
        if transformed:
            messages.append(_create_message(command, "elements_transformed", {"elements": transformed}))

    elif isinstance(payload, UpdatePointsPayload):
        element = session_elements.get(payload.element_id)
        if element is None:
            failures.append(DrawCommandFailure(element_id=payload.element_id, reason="element not found"))
        elif "points" not in element.payload or not isinstance(element.payload["points"], list):
            failures.append(
                DrawCommandFailure(
                    element_id=payload.element_id,
                    reason="element does not support point updates",
                )
            )
        else:
            incoming_points = [point.model_dump() for point in payload.points]
            existing_points = [
                {"x": float(point["x"]), "y": float(point["y"])}
                for point in element.payload["points"]
                if isinstance(point, dict) and "x" in point and "y" in point
            ]

            if payload.mode == "append":
                next_points = existing_points + incoming_points
            else:
                next_points = incoming_points

            if len(next_points) < 2:
                failures.append(
                    DrawCommandFailure(
                        element_id=payload.element_id,
                        reason="updated point list must contain at least 2 points",
                    )
                )
            else:
                element.payload["points"] = next_points
                element.bbox = _bbox_from_points(next_points)
                await store.put_element(command.session_id, element)
                applied_count = 1
                if element.element_type == "shape":
                    messages.extend(
                        await _sync_shape_label_positions(command, store, session_elements, element)
                    )
                messages.append(
                    _create_message(
                        command,
                        "elements_transformed",
                        {
                            "elements": [
                                {
                                    "element_id": payload.element_id,
                                    "element_type": element.element_type,
                                    "payload": element.payload,
                                }
                            ]
                        },
                    )
                )

    elif isinstance(payload, UpdateStylePayload):
        restyled = []
        for element_id in payload.element_ids:
            element = session_elements.get(element_id)
            if element is None:
                failures.append(DrawCommandFailure(element_id=element_id, reason="element not found"))
                continue
            _update_style_payload(element, payload)
            await store.put_element(command.session_id, element)
            restyled.append({
                "element_id": element_id,
                "element_type": element.element_type,
                "style": _translate_style_for_frontend(element.payload.get("style", {})),
            })
            applied_count += 1
        if restyled:
            messages.append(_create_message(command, "elements_restyled", {"elements": restyled}))

    return (
        messages,
        DrawResponse(
            session_id=command.session_id,
            command_id=command.command_id,
            operation=command.operation,
            applied_count=applied_count,
            created_element_ids=created_element_ids,
            failed_operations=failures,
            emitted_count=len(messages),
            dsl_messages=messages,
        ),
    )
