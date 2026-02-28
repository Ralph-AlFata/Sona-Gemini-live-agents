"""Pydantic v2 models for the Sona Drawing Command Service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─── Shared config ────────────────────────────────────────────────────────────

class _StrictBase(BaseModel):
    """Base model with strict mode for all drawing service models."""

    model_config = ConfigDict(
        strict=True,
        frozen=False,
        populate_by_name=True,
        extra="forbid",
    )


# ─── Payload types ────────────────────────────────────────────────────────────

class Point(_StrictBase):
    """Normalized canvas point where x and y are both within [0, 1]."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class FreehandPayload(_StrictBase):
    """Points for a freehand stroke with visual properties."""

    points: list[Point] = Field(min_length=2)
    color: str = Field(min_length=1, max_length=64)
    stroke_width: float = Field(gt=0.0, le=64.0)
    delay_ms: int = Field(ge=0, le=1_000)


class ShapePayload(_StrictBase):
    """A geometric shape with position, size, and optional template variant."""

    shape: Literal["rectangle", "ellipse", "line", "triangle", "polygon", "square"]
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
    """Text to render at a normalized position."""

    text: str = Field(min_length=1, max_length=2_000)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    font_size: int = Field(ge=8, le=256)
    color: str = Field(min_length=1, max_length=64)


class HighlightPayload(_StrictBase):
    """A rectangular highlight region."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    color: str = Field(min_length=1, max_length=64)


class ClearPayload(_StrictBase):
    """Payload for clearing the canvas."""

    mode: Literal["full"] = "full"


# ─── Draw message type ────────────────────────────────────────────────────────

DrawMessageType = Literal["freehand", "shape", "text", "highlight", "clear"]

_PAYLOAD_MODEL_MAP: dict[str, type[BaseModel]] = {
    "freehand": FreehandPayload,
    "shape": ShapePayload,
    "text": TextPayload,
    "highlight": HighlightPayload,
    "clear": ClearPayload,
}


# ─── Draw request ─────────────────────────────────────────────────────────────

class DrawRequest(_StrictBase):
    """Incoming draw command — used directly as the POST /draw request body."""

    session_id: str = Field(min_length=1, max_length=128)
    message_type: DrawMessageType
    payload: FreehandPayload | ShapePayload | TextPayload | HighlightPayload | ClearPayload

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        msg_type = data.get("message_type")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return data
        model_cls = _PAYLOAD_MODEL_MAP.get(msg_type or "")
        if model_cls is not None:
            data = {**data, "payload": model_cls.model_validate(payload)}
        return data


class ClearRequest(_StrictBase):
    """Request body for POST /draw/clear."""

    session_id: str = Field(min_length=1, max_length=128)


# ─── DSL message ──────────────────────────────────────────────────────────────

class DSLMessage(_StrictBase):
    """Versioned DSL message broadcast over WebSocket to frontends."""

    version: Literal["1.0"] = "1.0"
    id: str = Field(min_length=8, max_length=8)
    session_id: str = Field(min_length=1, max_length=128)
    type: DrawMessageType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: FreehandPayload | ShapePayload | TextPayload | HighlightPayload | ClearPayload


# ─── API response models ─────────────────────────────────────────────────────

class DrawResponse(_StrictBase):
    """Response for POST /draw and POST /draw/clear."""

    session_id: str
    emitted_count: int = Field(ge=0)


class HealthResponse(_StrictBase):
    """Response for GET /health."""

    status: Literal["ok"] = "ok"
    service: Literal["drawing"] = "drawing"
