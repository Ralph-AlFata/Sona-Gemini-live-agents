"""Pydantic v2 models for drawing command service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictBase(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=False,
        populate_by_name=True,
        extra="forbid",
    )


class Point(_StrictBase):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=2.0)  # width-uniform coords: y range = height/width


class StylePayload(_StrictBase):
    stroke_color: str = Field(default="#111111", min_length=1, max_length=64)
    stroke_width: float = Field(default=2.0, gt=0.0, le=64.0)
    fill_color: str | None = Field(default=None, min_length=1, max_length=64)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_index: int = Field(default=0, ge=0, le=10_000)
    delay_ms: int = Field(default=30, ge=0, le=1_000)
    animate: bool = True


class DrawShapePayload(_StrictBase):
    """
    Draw a shape defined by explicit vertex points.

    `shape` is a rendering hint for the frontend (e.g. "rectangle", "line",
    "triangle", "ellipse", "polygon", "square", "right_triangle"). Points are
    in normalised [0, 1] canvas coordinates. At least 2 points are required.
    Lines use 2 points; closed shapes should repeat the first point at the end.
    """

    shape: Literal[
        "rectangle",
        "ellipse",
        "circle",
        "line",
        "triangle",
        "right_triangle",
        "polygon",
        "square",
        "rhombus",
        "parallelogram",
        "trapezoid",
        "pentagon",
        "hexagon",
        "octagon",
        "number_line",
    ]
    points: list[Point] = Field(min_length=2)
    style: StylePayload = Field(default_factory=StylePayload)


class DrawTextPayload(_StrictBase):
    """
    Draw a text label on the canvas.

    `x, y` is the top-left origin of the text bounding box in normalised
    [0, 1] canvas coordinates. `font_size` is in pixels.
    """

    text: str = Field(min_length=1, max_length=2_000)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=2.0)
    font_size: int = Field(default=24, ge=8, le=256)
    text_format: Literal["plain", "latex"] = "plain"
    display_mode: bool = False
    style: StylePayload = Field(default_factory=StylePayload)


class DrawFreehandPayload(_StrictBase):
    points: list[Point] = Field(min_length=2)
    render_mode: Literal["freehand", "polyline"] = "freehand"
    graph_clip: "GraphClipPayload | None" = None
    style: StylePayload = Field(default_factory=StylePayload)


class GraphClipPayload(_StrictBase):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=2.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=2.0)


class HighlightPayload(_StrictBase):
    """
    Highlight one or more existing canvas elements.

    `element_ids` references elements created by previous draw operations.
    The service looks up their bounding boxes, computes a union region with
    `padding`, and creates a visual highlight of the requested type:

    - "marker"      — semi-transparent rectangle over the region (default)
    - "circle"      — ellipse outline around the region
    - "pointer"     — ellipse outline + arrow pointing at the region
    - "color_change"— updates the stroke/fill color of the target elements
                      directly (no new element is created)
    - "x_marker"   — two crossed diagonal lines at an explicit (point_x, point_y)
                      coordinate, used to mark an intersection or specific point
    """

    element_ids: list[str] = Field(default_factory=list, max_length=50)
    highlight_type: Literal["marker", "circle", "pointer", "color_change", "x_marker"] = "marker"
    padding: float = Field(default=0.02, ge=0.0, le=0.1)
    style: StylePayload = Field(default_factory=StylePayload)
    point_x: float | None = Field(default=None, ge=0.0, le=1.0)
    point_y: float | None = Field(default=None, ge=0.0, le=2.0)
    label: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _validate_for_type(self) -> "HighlightPayload":
        if self.highlight_type == "x_marker":
            if self.point_x is None or self.point_y is None:
                raise ValueError("x_marker requires point_x and point_y")
        else:
            if not self.element_ids:
                raise ValueError(f"{self.highlight_type} requires at least one element_id")
        return self


class ClearPayload(_StrictBase):
    mode: Literal["full"] = "full"


class GraphViewportPayload(_StrictBase):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=2.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=2.0)
    domain_min: float = Field(default=-10.0)
    domain_max: float = Field(default=10.0)
    y_min: float = Field(default=-10.0)
    y_max: float = Field(default=10.0)
    grid_lines: int = Field(default=10, ge=2, le=30)
    show_border: bool = True
    border_color: str = Field(default="#444444", min_length=1, max_length=64)
    border_opacity: float = Field(default=0.5, ge=0.0, le=1.0)
    axis_color: str = Field(default="#111111", min_length=1, max_length=64)
    axis_width: float = Field(default=2.0, gt=0.0, le=64.0)
    grid_color: str = Field(default="#bbbbbb", min_length=1, max_length=64)
    grid_opacity: float = Field(default=0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_ranges(self) -> "GraphViewportPayload":
        if self.domain_max <= self.domain_min:
            raise ValueError("domain_max must be greater than domain_min")
        if self.y_max <= self.y_min:
            raise ValueError("y_max must be greater than y_min")
        return self


class DeleteElementsPayload(_StrictBase):
    element_ids: list[str] = Field(min_length=1, max_length=500)


class EraseRegionPayload(_StrictBase):
    """
    Delete all elements whose bounding box intersects the given region.

    Equivalent to finding all elements in the area and passing their IDs to
    DeleteElementsPayload — the deletion logic is shared internally.
    """

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=2.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=2.0)

class MoveElementsPayload(_StrictBase):
    """
    Translate existing elements by a normalized delta.

    Final element coordinates are clamped to [0, 1] in the DSL layer to keep
    every element within the canvas bounds.
    """

    element_ids: list[str] = Field(min_length=1, max_length=500)
    dx: float = Field(ge=-1.0, le=1.0)
    dy: float = Field(ge=-2.0, le=2.0)


class ResizeElementsPayload(_StrictBase):
    element_ids: list[str] = Field(min_length=1, max_length=500)
    scale_x: float = Field(gt=0.0, le=10.0)
    scale_y: float = Field(gt=0.0, le=10.0)


class UpdatePointsPayload(_StrictBase):
    element_id: str = Field(min_length=1, max_length=128)
    points: list[Point] = Field(min_length=1)
    mode: Literal["replace", "append"] = "replace"

    @model_validator(mode="after")
    def _validate_points_for_mode(self) -> "UpdatePointsPayload":
        if self.mode == "replace" and len(self.points) < 2:
            raise ValueError("replace mode requires at least 2 points")
        return self


class UpdateStylePayload(_StrictBase):
    element_ids: list[str] = Field(min_length=1, max_length=500)
    stroke_color: str | None = Field(default=None, min_length=1, max_length=64)
    stroke_width: float | None = Field(default=None, gt=0.0, le=64.0)
    fill_color: str | None = Field(default=None, min_length=1, max_length=64)
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    z_index: int | None = Field(default=None, ge=0, le=10_000)
    delay_ms: int | None = Field(default=None, ge=0, le=1_000)

    @model_validator(mode="after")
    def _ensure_one_field(self) -> "UpdateStylePayload":
        if all(
            value is None
            for value in (
                self.stroke_color,
                self.stroke_width,
                self.fill_color,
                self.opacity,
                self.z_index,
                self.delay_ms,
            )
        ):
            raise ValueError("at least one style field must be provided")
        return self


class SetShapeLabelsPayload(_StrictBase):
    element_id: str = Field(min_length=1, max_length=128)
    labels: list[str] = Field(default_factory=list, max_length=64)
    font_size: int = Field(default=22, ge=8, le=256)


DrawOperation = Literal[
    "draw_shape",
    "draw_text",
    "draw_freehand",
    "highlight_region",
    "clear_canvas",
    "set_graph_viewport",
    "delete_elements",
    "erase_region",
    "move_elements",
    "resize_elements",
    "update_points",
    "update_style",
    "set_shape_labels",
]


DrawPayload = (
    DrawShapePayload
    | DrawTextPayload
    | DrawFreehandPayload
    | HighlightPayload
    | ClearPayload
    | GraphViewportPayload
    | DeleteElementsPayload
    | EraseRegionPayload
    | MoveElementsPayload
    | ResizeElementsPayload
    | UpdatePointsPayload
    | UpdateStylePayload
    | SetShapeLabelsPayload
)


_PAYLOAD_MODEL_MAP: dict[str, type[BaseModel]] = {
    "draw_shape": DrawShapePayload,
    "draw_text": DrawTextPayload,
    "draw_freehand": DrawFreehandPayload,
    "highlight_region": HighlightPayload,
    "clear_canvas": ClearPayload,
    "set_graph_viewport": GraphViewportPayload,
    "delete_elements": DeleteElementsPayload,
    "erase_region": EraseRegionPayload,
    "move_elements": MoveElementsPayload,
    "resize_elements": ResizeElementsPayload,
    "update_points": UpdatePointsPayload,
    "update_style": UpdateStylePayload,
    "set_shape_labels": SetShapeLabelsPayload,
}


class DrawCommandRequest(_StrictBase):
    command_id: str = Field(default_factory=lambda: uuid4().hex[:12], min_length=1, max_length=128)
    operation: DrawOperation
    session_id: str = Field(min_length=1, max_length=128)
    payload: DrawPayload
    element_id: str | None = Field(default=None, min_length=1, max_length=128)
    source: Literal["ai", "user"] = "ai"

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        op = data.get("operation")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return data

        model_cls = _PAYLOAD_MODEL_MAP.get(str(op))
        if model_cls is not None:
            data = {**data, "payload": model_cls.model_validate(data["payload"])}
        return data


DSLMessageType = Literal[
    "element_created",
    "elements_deleted",
    "elements_transformed",
    "elements_restyled",
    "graph_viewport_set",
    "clear",
]


class DSLMessage(_StrictBase):
    """
    A single DSL reconciliation message broadcast to WebSocket subscribers.

    `id` is an 8-char unique message identifier. `command_id` links this
    message back to the originating DrawCommandRequest.

    Element-specific IDs are carried inside `payload`, not at the top level,
    because different message types reference different numbers of elements:
    - element_created:       payload.element_id  (single)
    - elements_deleted:      payload.element_ids (list)
    - elements_transformed:  payload.elements[].element_id (list)
    - elements_restyled:     payload.elements[].element_id (list)
    - clear:                 payload.mode
    """

    version: Literal["2.0"] = "2.0"
    id: str = Field(min_length=8, max_length=8)
    command_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    type: DSLMessageType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any]


class DrawCommandFailure(_StrictBase):
    element_id: str | None = None
    reason: str = Field(min_length=1, max_length=500)


class DrawResponse(_StrictBase):
    session_id: str
    command_id: str
    operation: DrawOperation
    applied_count: int = Field(ge=0)
    created_element_ids: list[str] = Field(default_factory=list)
    failed_operations: list[DrawCommandFailure] = Field(default_factory=list)
    emitted_count: int = Field(ge=0)
    dsl_messages: list[DSLMessage] = Field(default_factory=list)


class SessionStateResponse(_StrictBase):
    session_id: str
    element_count: int = Field(ge=0)
    dsl_messages: list[DSLMessage] = Field(default_factory=list)


class SessionElementSnapshot(_StrictBase):
    session_id: str
    element_id: str
    element_type: str
    source: Literal["ai", "user"] = "ai"
    payload: dict[str, Any] = Field(default_factory=dict)


class CanvasStateElement(_StrictBase):
    id: str
    type: str
    source: Literal["ai", "user"] = "ai"
    points: list[Point] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    side_labels: list[dict[str, Any]] = Field(default_factory=list)
    text: str | None = None
    style: dict[str, Any] = Field(default_factory=dict)
    bbox: dict[str, float] = Field(default_factory=dict)


class CanvasStateResponse(_StrictBase):
    session_id: str
    element_count: int = Field(ge=0)
    elements: list[CanvasStateElement] = Field(default_factory=list)


class ClearRequest(_StrictBase):
    session_id: str = Field(min_length=1, max_length=128)


class HealthResponse(_StrictBase):
    status: Literal["ok"] = "ok"
    service: Literal["drawing"] = "drawing"
