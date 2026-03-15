"""Pydantic schemas for orchestrator drawing tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NextDirection = Literal["below", "right", "left", "below_all"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ToolStyle(_StrictModel):
    stroke_color: str = Field(default="#111111", min_length=1, max_length=64)
    stroke_width: float = Field(default=2.0, gt=0.0, le=64.0)
    fill_color: str | None = Field(default=None, min_length=1, max_length=64)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_index: int = Field(default=0, ge=0, le=10_000)
    delay_ms: int = Field(default=30, ge=0, le=1_000)
    animate: bool = True


class PointInput(_StrictModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=2.0)  # width-uniform coords: y range = height/width


class CircleCenterInput(_StrictModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=2.0)


class DrawShapeInput(_StrictModel):
    """
    Input for the draw_shape tool.

    `shape` is a rendering hint (e.g. "rectangle", "line", "triangle",
    "right_triangle", "ellipse", "polygon", "square").
    Two modes are supported:
    - manual placement with explicit `points`
    - cursor placement with `width`/`height` (points generated server-side)
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
    ]
    points: list[PointInput] | None = Field(default=None, min_length=2)
    center: CircleCenterInput | None = None
    radius: float | None = Field(default=None, gt=0.0, le=1.0)
    width: float | None = Field(default=None, gt=0.0, le=1.0)
    height: float | None = Field(default=None, gt=0.0, le=2.0)
    next: NextDirection = "below"
    labels: list[str] = Field(default_factory=list, max_length=64)
    style: ToolStyle = Field(default_factory=ToolStyle)

    @model_validator(mode="after")
    def _validate_labels(self) -> "DrawShapeInput":
        if self.shape != "circle" and (self.center is not None or self.radius is not None):
            raise ValueError("center/radius are only supported for shape 'circle'")

        if self.shape in {"circle", "ellipse"} and self.labels:
            raise ValueError(f"labels are not supported for shape '{self.shape}'")

        has_center = self.center is not None
        has_radius = self.radius is not None
        if has_center != has_radius:
            raise ValueError("circle center and radius must be provided together")

        if self.points is not None and has_center:
            raise ValueError("provide either explicit points or center/radius, not both")

        if self.points is None:
            if self.shape == "circle" and has_center:
                if self.width is not None or self.height is not None:
                    raise ValueError("circle center/radius cannot be combined with width/height")
                return self
            if self.width is None:
                raise ValueError("provide 'points' or 'width' for shape placement")
            if self.labels:
                raise ValueError("labels require explicit shape points")
            return self

        if not self.labels:
            return self

        edge_count = len(self.points) - 1
        if edge_count < 1:
            raise ValueError("labels require at least one side")
        if len(self.labels) > edge_count:
            raise ValueError(f"labels can have at most {edge_count} entries for this shape")

        return self


class DrawTextInput(_StrictModel):
    text: str = Field(min_length=1, max_length=2_000)
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    y: float | None = Field(default=None, ge=0.0, le=2.0)
    next: NextDirection = "below"
    font_size: int = Field(default=24, ge=8, le=256)
    style: ToolStyle = Field(default_factory=ToolStyle)

    @model_validator(mode="after")
    def _validate_text_coords(self) -> "DrawTextInput":
        has_x = self.x is not None
        has_y = self.y is not None
        if has_x != has_y:
            raise ValueError("x and y must be both provided or both omitted")
        return self


class DrawFreehandInput(_StrictModel):
    points: list[PointInput] = Field(min_length=2)
    next: NextDirection = "below"
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
    - "x_marker"     — two crossed diagonal lines at (point_x, point_y)
    """

    element_ids: list[str] = Field(default_factory=list, max_length=50)
    highlight_type: Literal["marker", "circle", "pointer", "color_change", "x_marker"] = "marker"
    padding: float = Field(default=0.02, ge=0.0, le=0.1)
    style: ToolStyle = Field(default_factory=ToolStyle)
    point_x: float | None = Field(default=None, ge=0.0, le=1.0)
    point_y: float | None = Field(default=None, ge=0.0, le=2.0)
    label: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _validate_for_type(self) -> "HighlightInput":
        if self.highlight_type == "x_marker":
            if self.point_x is None or self.point_y is None:
                raise ValueError("x_marker requires point_x and point_y")
        else:
            if not self.element_ids:
                raise ValueError(f"{self.highlight_type} requires at least one element_id")
        return self


class DeleteElementsInput(_StrictModel):
    element_ids: list[str] = Field(min_length=1, max_length=500)


class EraseRegionInput(_StrictModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=2.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=2.0)


class MoveElementsInput(_StrictModel):
    element_ids: list[str] = Field(min_length=1, max_length=500)
    dx: float = Field(ge=-1.0, le=1.0)
    dy: float = Field(ge=-2.0, le=2.0)


class ResizeElementsInput(_StrictModel):
    element_ids: list[str] = Field(min_length=1, max_length=500)
    scale_x: float = Field(gt=0.0, le=10.0)
    scale_y: float = Field(gt=0.0, le=10.0)


class UpdatePointsInput(_StrictModel):
    element_id: str = Field(min_length=1, max_length=128)
    points: list[PointInput] = Field(min_length=1)
    mode: Literal["replace", "append"] = "replace"

    @model_validator(mode="after")
    def _validate_points_for_mode(self) -> "UpdatePointsInput":
        if self.mode == "replace" and len(self.points) < 2:
            raise ValueError("replace mode requires at least 2 points")
        return self


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


class SetShapeLabelsInput(_StrictModel):
    element_id: str = Field(min_length=1, max_length=128)
    labels: list[str] = Field(default_factory=list, max_length=64)
    font_size: int = Field(default=22, ge=8, le=256)


class ToolResult(_StrictModel):
    status: str
    operation: str
    applied_count: int = 0
    created_element_ids: list[str] = Field(default_factory=list)
    failed_operations: list[dict[str, str | None]] = Field(default_factory=list)
    command_id: str
    deduplicated: bool = False
    already_completed: bool = False
    message: str | None = None
    previous_command_id: str | None = None
