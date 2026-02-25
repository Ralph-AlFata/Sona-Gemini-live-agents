"""Draw request to DSL message translator.

Converts a single DrawRequest into one or more versioned DSLMessage objects
that are broadcast over WebSocket to connected frontends.
"""

from __future__ import annotations

from uuid import uuid4

from models import (
    ClearPayload,
    DSLMessage,
    DrawRequest,
    FreehandPayload,
    HighlightPayload,
    Point,
    ShapePayload,
    TextPayload,
)
from templates import cartesian_axes, circle_outline, number_line, right_triangle

FREEHAND_CHUNK_SIZE = 8

_TEMPLATE_MAP = {
    "right_triangle": right_triangle,
    "circle_outline": circle_outline,
    "number_line": number_line,
    "cartesian_axes": cartesian_axes,
}


def _next_message_id() -> str:
    return uuid4().hex[:8]


def _chunk_points(points: list[Point], size: int = FREEHAND_CHUNK_SIZE) -> list[list[Point]]:
    if not 5 <= size <= 10:
        raise ValueError("freehand chunk size must be between 5 and 10")
    chunks = [points[i : i + size] for i in range(0, len(points), size)]
    # FreehandPayload requires each emitted chunk to contain at least 2 points.
    # If the last chunk has a single point, rebalance one point from the prior chunk.
    if len(chunks) >= 2 and len(chunks[-1]) == 1:
        tail = chunks[-1][0]
        donor = chunks[-2]
        chunks[-2] = donor[:-1]
        chunks[-1] = [donor[-1], tail]
    return chunks


def _transform_template_points(payload: ShapePayload) -> list[Point]:
    """Look up a named template and transform its normalized points into
    absolute coordinates using the shape's position and dimensions."""
    template_builder = _TEMPLATE_MAP.get(payload.template_variant or "")
    if template_builder is None:
        return []

    transformed: list[Point] = []
    for point in template_builder():
        transformed.append(
            point.model_copy(
                update={
                    "x": payload.x + (point.x * payload.width),
                    "y": payload.y + (point.y * payload.height),
                }
            )
        )
    return transformed


def translate(draw_request: DrawRequest) -> list[DSLMessage]:
    """Translate one draw action into one or more versioned DSL messages."""
    message_type = draw_request.message_type
    payload = draw_request.payload

    if message_type == "freehand" and isinstance(payload, FreehandPayload):
        chunks = _chunk_points(payload.points)
        return [
            DSLMessage(
                id=_next_message_id(),
                session_id=draw_request.session_id,
                type="freehand",
                payload=FreehandPayload(
                    points=chunk,
                    color=payload.color,
                    stroke_width=payload.stroke_width,
                    delay_ms=payload.delay_ms,
                ),
            )
            for chunk in chunks
        ]

    if message_type == "shape" and isinstance(payload, ShapePayload):
        if payload.template_variant:
            transformed_points = _transform_template_points(payload)
            if not transformed_points:
                raise ValueError(f"Unknown template_variant: {payload.template_variant}")

            chunks = _chunk_points(transformed_points)
            return [
                DSLMessage(
                    id=_next_message_id(),
                    session_id=draw_request.session_id,
                    type="freehand",
                    payload=FreehandPayload(
                        points=chunk,
                        color=payload.color,
                        stroke_width=2.0,
                        delay_ms=35,
                    ),
                )
                for chunk in chunks
            ]

        return [
            DSLMessage(
                id=_next_message_id(),
                session_id=draw_request.session_id,
                type="shape",
                payload=payload,
            )
        ]

    if message_type == "text" and isinstance(payload, TextPayload):
        return [
            DSLMessage(
                id=_next_message_id(),
                session_id=draw_request.session_id,
                type="text",
                payload=payload,
            )
        ]

    if message_type == "highlight" and isinstance(payload, HighlightPayload):
        return [
            DSLMessage(
                id=_next_message_id(),
                session_id=draw_request.session_id,
                type="highlight",
                payload=payload,
            )
        ]

    if message_type == "clear" and isinstance(payload, ClearPayload):
        return [
            DSLMessage(
                id=_next_message_id(),
                session_id=draw_request.session_id,
                type="clear",
                payload=payload,
            )
        ]

    raise ValueError(
        f"translate: unhandled message_type={message_type!r} "
        f"with payload type {type(payload).__name__}"
    )
