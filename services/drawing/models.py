"""Pydantic models for the Sona Drawing Command Service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictBase(BaseModel):
    """Base strict model used across request/response contracts."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
    )


class Point(_StrictBase):
    """Normalized canvas point where x and y are both within [0, 1]."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class FreehandPayload(_StrictBase):
    points: list[Point] = Field(min_length=1)
    color: str = Field(min_length=1, max_length=64)
    stroke_width: float = Field(gt=0.0, le=64.0)
    delay_ms: int = Field(ge=0, le=1_000)


class ShapePayload(_StrictBase):
    shape: Literal["rectangle", "ellipse", "line", "triangle", "polygon"]
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    color: str = Field(min_length=1, max_length=64)
    fill_color: str | None = Field(default=None, min_length=1, max_length=64)
    template_variant: Literal[
        "right_triangle",
        "circle_outline",
        "number_line",
        "cartesian_axes",
    ] | None = None


class TextPayload(_StrictBase):
    text: str = Field(min_length=1, max_length=2_000)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    font_size: int = Field(ge=8, le=256)
    color: str = Field(min_length=1, max_length=64)


class HighlightPayload(_StrictBase):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    color: str = Field(min_length=1, max_length=64)


class ClearPayload(_StrictBase):
    mode: Literal["full"] = "full"


DrawMessageType = Literal["freehand", "shape", "text", "highlight", "clear"]


class DrawRequest(_StrictBase):
    session_id: str = Field(min_length=1, max_length=128)
    message_type: DrawMessageType
    payload: FreehandPayload | ShapePayload | TextPayload | HighlightPayload | ClearPayload | dict[str, Any]

    @model_validator(mode="after")
    def validate_payload_type(self) -> "DrawRequest":
        payload_model: type[BaseModel]
        if self.message_type == "freehand":
            payload_model = FreehandPayload
        elif self.message_type == "shape":
            payload_model = ShapePayload
        elif self.message_type == "text":
            payload_model = TextPayload
        elif self.message_type == "highlight":
            payload_model = HighlightPayload
        else:
            payload_model = ClearPayload

        if isinstance(self.payload, payload_model):
            return self

        if isinstance(self.payload, dict):
            self.payload = payload_model.model_validate(self.payload)
            return self

        raise ValueError(
            f"payload does not match message_type={self.message_type!r}; "
            f"expected {payload_model.__name__}"
        )


class DrawRequestBody(_StrictBase):
    session_id: str = Field(min_length=1, max_length=128)
    message_type: Literal["freehand", "shape", "text", "highlight"]
    payload: FreehandPayload | ShapePayload | TextPayload | HighlightPayload | dict[str, Any]

    def to_draw_request(self) -> DrawRequest:
        return DrawRequest(
            session_id=self.session_id,
            message_type=self.message_type,
            payload=self.payload,
        )


class ClearRequestBody(_StrictBase):
    session_id: str = Field(min_length=1, max_length=128)


class DSLMessage(_StrictBase):
    version: Literal["1.0"] = "1.0"
    id: str = Field(min_length=8, max_length=8)
    session_id: str = Field(min_length=1, max_length=128)
    type: DrawMessageType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: FreehandPayload | ShapePayload | TextPayload | HighlightPayload | ClearPayload


class DrawResponse(_StrictBase):
    session_id: str
    emitted_count: int = Field(ge=0)


class HealthResponse(_StrictBase):
    status: Literal["ok"] = "ok"
    service: Literal["drawing"] = "drawing"
