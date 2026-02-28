"""Drawing command application + DSL message translation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

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
    HighlightPayload,
    MoveElementsPayload,
    Point,
    ResizeElementsPayload,
    StylePayload,
    UpdateStylePayload,
)


@dataclass(slots=True)
class BBox:
    x: float
    y: float
    width: float
    height: float


@dataclass(slots=True)
class StoredElement:
    element_id: str
    element_type: str
    payload: dict
    bbox: BBox


def _next_message_id() -> str:
    return uuid4().hex[:8]


def _next_element_id() -> str:
    return f"el_{uuid4().hex[:12]}"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _bbox_intersects(a: BBox, b: BBox) -> bool:
    return not (
        a.x + a.width < b.x
        or b.x + b.width < a.x
        or a.y + a.height < b.y
        or b.y + b.height < a.y
    )


def _style_to_dict(style: StylePayload) -> dict:
    return {
        "stroke_color": style.stroke_color,
        "stroke_width": style.stroke_width,
        "fill_color": style.fill_color,
        "opacity": style.opacity,
        "z_index": style.z_index,
        "delay_ms": style.delay_ms,
    }

# TODO: Since we are looking into changing the way we define shapes (from the points), we need to change how we infer the BBOX
def _build_shape_element(payload: DrawShapePayload) -> tuple[dict, BBox]:
    draw_payload = {
        "shape": payload.shape,
        "x": payload.x,
        "y": payload.y,
        "width": payload.width,
        "height": payload.height,
        "template_variant": payload.template_variant,
        "style": _style_to_dict(payload.style),
    }
    return draw_payload, BBox(payload.x, payload.y, payload.width, payload.height)


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
    return draw_payload, BBox(min_x, min_y, max_x - min_x, max_y - min_y)

# TODO: This needs to change according to what we have set in the models.py
def _build_highlight_element(payload: HighlightPayload) -> tuple[dict, BBox]:
    draw_payload = {
        "x": payload.x,
        "y": payload.y,
        "width": payload.width,
        "height": payload.height,
        "style": _style_to_dict(payload.style),
    }
    return draw_payload, BBox(payload.x, payload.y, payload.width, payload.height)


def _translate_style_for_frontend(style: dict) -> dict:
    return {
        "color": style.get("stroke_color", "#111111"),
        "stroke_width": style.get("stroke_width", 2.0),
        "fill_color": style.get("fill_color"),
        "opacity": style.get("opacity", 1.0),
        "z_index": style.get("z_index", 0),
        "delay_ms": style.get("delay_ms", 30),
    }


def _create_message(command: DrawCommandRequest, message_type: str, payload: dict) -> DSLMessage:
    return DSLMessage(
        id=_next_message_id(),
        command_id=command.command_id,
        session_id=command.session_id,
        type=message_type,
        payload=payload,
    )

# TODO: figure out why and how we should use it
def _move_bbox(bbox: BBox, dx: float, dy: float) -> BBox:
    return BBox(x=_clamp(bbox.x + dx), y=_clamp(bbox.y + dy), width=bbox.width, height=bbox.height)

# TODO: figure out why and how we should use it
def _resize_bbox(bbox: BBox, sx: float, sy: float) -> BBox:
    cx = bbox.x + (bbox.width / 2)
    cy = bbox.y + (bbox.height / 2)
    nw = min(1.0, bbox.width * sx)
    nh = min(1.0, bbox.height * sy)
    return BBox(
        x=_clamp(cx - (nw / 2)),
        y=_clamp(cy - (nh / 2)),
        width=nw,
        height=nh,
    )

# TODO: Everything related to moving, we need to later think if we just allow the agent to move, or we can allow the user to "select elements and move them himself"
def _move_payload(element: StoredElement, dx: float, dy: float) -> None:
    if element.element_type == "freehand":
        points = []
        for point in element.payload["points"]:
            points.append({"x": _clamp(float(point["x"]) + dx), "y": _clamp(float(point["y"]) + dy)})
        element.payload["points"] = points
        xs = [point["x"] for point in points]
        ys = [point["y"] for point in points]
        element.bbox = BBox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        return

    if {"x", "y"}.issubset(element.payload):
        element.payload["x"] = _clamp(float(element.payload["x"]) + dx)
        element.payload["y"] = _clamp(float(element.payload["y"]) + dy)

    element.bbox = _move_bbox(element.bbox, dx, dy)


def _resize_payload(element: StoredElement, scale_x: float, scale_y: float) -> None:
    new_bbox = _resize_bbox(element.bbox, scale_x, scale_y)

    if element.element_type == "freehand":
        old_bbox = element.bbox
        if old_bbox.width == 0 or old_bbox.height == 0:
            element.bbox = new_bbox
            return
        sx = new_bbox.width / old_bbox.width
        sy = new_bbox.height / old_bbox.height
        points = []
        for point in element.payload["points"]:
            rel_x = (float(point["x"]) - old_bbox.x) / old_bbox.width
            rel_y = (float(point["y"]) - old_bbox.y) / old_bbox.height
            points.append(
                {
                    "x": _clamp(new_bbox.x + (rel_x * new_bbox.width)),
                    "y": _clamp(new_bbox.y + (rel_y * new_bbox.height)),
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

# TODO: Figure out what this does, and why is it used
def apply_command(
    command: DrawCommandRequest,
    element_store: dict[str, dict[str, StoredElement]],
) -> tuple[list[DSLMessage], DrawResponse]:
    session_elements = element_store.setdefault(command.session_id, {})
    messages: list[DSLMessage] = []
    failures: list[DrawCommandFailure] = []
    created_element_ids: list[str] = []
    applied_count = 0

    payload = command.payload

    if isinstance(payload, ClearPayload):
        session_elements.clear()
        messages.append(_create_message(command, "clear", {"mode": "full"}))
        applied_count = 1

    elif isinstance(payload, DrawShapePayload):
        element_id = _next_element_id()
        draw_payload, bbox = _build_shape_element(payload)
        session_elements[element_id] = StoredElement(
            element_id=element_id,
            element_type="shape",
            payload=draw_payload,
            bbox=bbox,
        )
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
                        "x": draw_payload["x"],
                        "y": draw_payload["y"],
                        "width": draw_payload["width"],
                        "height": draw_payload["height"],
                        "template_variant": draw_payload.get("template_variant"),
                        **_translate_style_for_frontend(draw_payload["style"]),
                    },
                },
            )
        )

    elif isinstance(payload, DrawTextPayload):
        element_id = _next_element_id()
        draw_payload, bbox = _build_text_element(payload)
        session_elements[element_id] = StoredElement(
            element_id=element_id,
            element_type="text",
            payload=draw_payload,
            bbox=bbox,
        )
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
        element_id = _next_element_id()
        draw_payload, bbox = _build_freehand_element(payload)
        session_elements[element_id] = StoredElement(
            element_id=element_id,
            element_type="freehand",
            payload=draw_payload,
            bbox=bbox,
        )
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
        element_id = _next_element_id()
        draw_payload, bbox = _build_highlight_element(payload)
        session_elements[element_id] = StoredElement(
            element_id=element_id,
            element_type="highlight",
            payload=draw_payload,
            bbox=bbox,
        )
        created_element_ids.append(element_id)
        applied_count = 1
        messages.append(
            _create_message(
                command,
                "element_created",
                {
                    "element_id": element_id,
                    "element_type": "highlight",
                    "payload": {
                        "x": draw_payload["x"],
                        "y": draw_payload["y"],
                        "width": draw_payload["width"],
                        "height": draw_payload["height"],
                        **_translate_style_for_frontend(draw_payload["style"]),
                    },
                },
            )
        )

    elif isinstance(payload, DeleteElementsPayload):
        deleted: list[str] = []
        for element_id in payload.element_ids:
            if element_id in session_elements:
                session_elements.pop(element_id, None)
                deleted.append(element_id)
                applied_count += 1
            else:
                failures.append(DrawCommandFailure(element_id=element_id, reason="element not found"))
        if deleted:
            messages.append(_create_message(command, "elements_deleted", {"element_ids": deleted}))

    elif isinstance(payload, EraseRegionPayload):
        target = BBox(payload.x, payload.y, payload.width, payload.height)
        deleted = [element_id for element_id, element in session_elements.items() if _bbox_intersects(element.bbox, target)]
        for element_id in deleted:
            session_elements.pop(element_id, None)
            applied_count += 1
        messages.append(_create_message(command, "elements_deleted", {"element_ids": deleted}))

    elif isinstance(payload, MoveElementsPayload):
        transformed: list[dict] = []
        for element_id in payload.element_ids:
            element = session_elements.get(element_id)
            if element is None:
                failures.append(DrawCommandFailure(element_id=element_id, reason="element not found"))
                continue
            _move_payload(element, payload.dx, payload.dy)
            transformed.append(
                {
                    "element_id": element_id,
                    "element_type": element.element_type,
                    "payload": element.payload,
                }
            )
            applied_count += 1
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
            transformed.append(
                {
                    "element_id": element_id,
                    "element_type": element.element_type,
                    "payload": element.payload,
                }
            )
            applied_count += 1
        if transformed:
            messages.append(_create_message(command, "elements_transformed", {"elements": transformed}))

    elif isinstance(payload, UpdateStylePayload):
        restyled = []
        for element_id in payload.element_ids:
            element = session_elements.get(element_id)
            if element is None:
                failures.append(DrawCommandFailure(element_id=element_id, reason="element not found"))
                continue
            _update_style_payload(element, payload)
            restyled.append(
                {
                    "element_id": element_id,
                    "element_type": element.element_type,
                    "style": _translate_style_for_frontend(element.payload.get("style", {})),
                }
            )
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
        ),
    )
