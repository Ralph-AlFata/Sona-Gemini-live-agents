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
    y: float = Field(ge=0.0, le=1.0)


class StylePayload(_StrictBase):
    stroke_color: str = Field(default="#111111", min_length=1, max_length=64)
    stroke_width: float = Field(default=2.0, gt=0.0, le=64.0)
    fill_color: str | None = Field(default=None, min_length=1, max_length=64)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_index: int = Field(default=0, ge=0, le=10_000)
    delay_ms: int = Field(default=30, ge=0, le=1_000)


# TODO: Review the way we are thinking about the Shapes. Instead of defining them with x,y,width,height. I think we should define them using a series of points
# I think this is why it could not draw a right angle triangle previously
# This could make it easier for us later, because we can define more things because we know the exact location of the points that matter
class DrawShapePayload(_StrictBase):
    shape: Literal["rectangle", "ellipse", "line", "triangle", "polygon", "square"]
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    style: StylePayload = Field(default_factory=StylePayload)
    template_variant: Literal[
        "right_triangle",
        "circle_outline",
        "number_line",
        "cartesian_axes",
    ] | None = None

# TODO: Check if the x, y is the location where the text starts? or something else
class DrawTextPayload(_StrictBase):
    text: str = Field(min_length=1, max_length=2_000)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    font_size: int = Field(default=24, ge=8, le=256)
    style: StylePayload = Field(default_factory=StylePayload)


class DrawFreehandPayload(_StrictBase):
    points: list[Point] = Field(min_length=2)
    style: StylePayload = Field(default_factory=StylePayload)

# TODO: For the highlighlit payload, I think the width and heigh should not be random, they should be based on what is the object you are trying to highlight
# Therefore, the arguments isntead of x,y,width,height, they would become like "what is the object/objects you aim to highlight"
# I also want several types of highlighting: One which is "circle around something", another "circle with a pointer", "highilight like marker", or "change the color of the element"
class HighlightPayload(_StrictBase):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    style: StylePayload = Field(default_factory=StylePayload)


class ClearPayload(_StrictBase):
    mode: Literal["full"] = "full"


class DeleteElementsPayload(_StrictBase):
    element_ids: list[str] = Field(min_length=1, max_length=500)

# TODO: Double check if it's about deleting everything in a certain area.
# The way this needs to be processed is that it takes the area, finds the elements in this area, then deletes them through the DeleteElements
class EraseRegionPayload(_StrictBase):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)


class MoveElementsPayload(_StrictBase):
    element_ids: list[str] = Field(min_length=1, max_length=500)
    dx: float = Field(ge=-1.0, le=1.0)
    dy: float = Field(ge=-1.0, le=1.0)


class ResizeElementsPayload(_StrictBase):
    element_ids: list[str] = Field(min_length=1, max_length=500)
    scale_x: float = Field(gt=0.0, le=10.0)
    scale_y: float = Field(gt=0.0, le=10.0)


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


DrawOperation = Literal[
    "draw_shape",
    "draw_text",
    "draw_freehand",
    "highlight_region",
    "clear_canvas",
    "delete_elements",
    "erase_region",
    "move_elements",
    "resize_elements",
    "update_style",
]


DrawPayload = (
    DrawShapePayload
    | DrawTextPayload
    | DrawFreehandPayload
    | HighlightPayload
    | ClearPayload
    | DeleteElementsPayload
    | EraseRegionPayload
    | MoveElementsPayload
    | ResizeElementsPayload
    | UpdateStylePayload
)


_PAYLOAD_MODEL_MAP: dict[str, type[BaseModel]] = {
    "draw_shape": DrawShapePayload,
    "draw_text": DrawTextPayload,
    "draw_freehand": DrawFreehandPayload,
    "highlight_region": HighlightPayload,
    "clear_canvas": ClearPayload,
    "delete_elements": DeleteElementsPayload,
    "erase_region": EraseRegionPayload,
    "move_elements": MoveElementsPayload,
    "resize_elements": ResizeElementsPayload,
    "update_style": UpdateStylePayload,
}

class DrawCommandRequest(_StrictBase):
    command_id: str = Field(default_factory=lambda: uuid4().hex[:12], min_length=1, max_length=128)
    operation: DrawOperation
    session_id: str = Field(min_length=1, max_length=128)
    payload: DrawPayload

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
    "clear",
]

# TODO: Check if we should add element_id here
class DSLMessage(_StrictBase):
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


class ClearRequest(_StrictBase):
    session_id: str = Field(min_length=1, max_length=128)


class HealthResponse(_StrictBase):
    status: Literal["ok"] = "ok"
    service: Literal["drawing"] = "drawing"
