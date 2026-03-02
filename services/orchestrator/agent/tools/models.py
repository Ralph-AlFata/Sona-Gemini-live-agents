"""Pydantic schemas for orchestrator drawing tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ToolStyle(_StrictModel):
    stroke_color: str = Field(default="#111111", min_length=1, max_length=64)
    stroke_width: float = Field(default=2.0, gt=0.0, le=64.0)
    fill_color: str | None = Field(default=None, min_length=1, max_length=64)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_index: int = Field(default=0, ge=0, le=10_000)
    delay_ms: int = Field(default=30, ge=0, le=1_000)


class PointInput(_StrictModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class DrawShapeInput(_StrictModel):
    """
    Input for the draw_shape tool.

    `shape` is a rendering hint (e.g. "rectangle", "line", "triangle",
    "right_triangle", "ellipse", "polygon", "square").
    `points` are explicit vertex coordinates in normalised [0, 1] space.
    Lines need 2 points; closed shapes should repeat the first point at the end.
    """

    shape: Literal[
        "rectangle",
        "ellipse",
        "line",
        "triangle",
        "right_triangle",
        "polygon",
        "square",
    ]
    points: list[PointInput] = Field(min_length=2)
    style: ToolStyle = Field(default_factory=ToolStyle)


class DrawTextInput(_StrictModel):
    text: str = Field(min_length=1, max_length=2_000)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    font_size: int = Field(default=24, ge=8, le=256)
    style: ToolStyle = Field(default_factory=ToolStyle)


class DrawFreehandInput(_StrictModel):
    points: list[PointInput] = Field(min_length=2)
    style: ToolStyle = Field(default_factory=ToolStyle)


class HighlightInput(_StrictModel):
    """
    Input for the highlight_region tool.

    `element_ids` is a list of IDs returned by previous draw operations.
    The drawing service computes the union bounding box and renders the
    appropriate visual based on `highlight_type`:
    - "marker"       — semi-transparent rectangle (default)
    - "circle"       — ellipse outline
    - "pointer"      — ellipse + arrow
    - "color_change" — applies the style to the target elements directly
    """

    element_ids: list[str] = Field(min_length=1, max_length=50)
    highlight_type: Literal["marker", "circle", "pointer", "color_change"] = "marker"
    padding: float = Field(default=0.02, ge=0.0, le=0.1)
    style: ToolStyle = Field(default_factory=ToolStyle)


class DeleteElementsInput(_StrictModel):
    element_ids: list[str] = Field(min_length=1, max_length=500)


class EraseRegionInput(_StrictModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)


class MoveElementsInput(_StrictModel):
    element_ids: list[str] = Field(min_length=1, max_length=500)
    dx: float = Field(ge=-1.0, le=1.0)
    dy: float = Field(ge=-1.0, le=1.0)


class ResizeElementsInput(_StrictModel):
    element_ids: list[str] = Field(min_length=1, max_length=500)
    scale_x: float = Field(gt=0.0, le=10.0)
    scale_y: float = Field(gt=0.0, le=10.0)


class UpdateStyleInput(_StrictModel):
    element_ids: list[str] = Field(min_length=1, max_length=500)
    stroke_color: str | None = Field(default=None, min_length=1, max_length=64)
    stroke_width: float | None = Field(default=None, gt=0.0, le=64.0)
    fill_color: str | None = Field(default=None, min_length=1, max_length=64)
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    z_index: int | None = Field(default=None, ge=0, le=10_000)
    delay_ms: int | None = Field(default=None, ge=0, le=1_000)

    @model_validator(mode="after")
    def _ensure_at_least_one(self) -> "UpdateStyleInput":
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
            raise ValueError("at least one style update field is required")
        return self


class ToolResult(_StrictModel):
    status: str
    operation: str
    applied_count: int = 0
    created_element_ids: list[str] = Field(default_factory=list)
    failed_operations: list[dict[str, str | None]] = Field(default_factory=list)
    command_id: str
