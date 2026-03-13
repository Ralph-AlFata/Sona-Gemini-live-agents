"""
Pydantic v2 models for the Sona Session Service.

Session document structure in Firestore:
    sessions/{session_id} → summary document (status, timestamps, latest snapshot)
    sessions/{session_id}/turns/{turn_id} → ConversationTurn document
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ─── Shared config ────────────────────────────────────────────────────────────

class _StrictBase(BaseModel):
    """Base model with strict mode for all Sona models."""

    model_config = ConfigDict(
        strict=True,
        frozen=False,
        populate_by_name=True,
        extra="forbid",
    )


# ─── Conversation ─────────────────────────────────────────────────────────────

class ConversationTurn(_StrictBase):
    """A single exchange in the tutoring session."""

    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    role: Literal["student", "sona"]
    content: str = Field(min_length=1, max_length=8_000)
    metadata: dict[str, object] | None = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def to_firestore_dict(self) -> dict[str, object]:
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_firestore_dict(cls, data: dict[str, object]) -> "ConversationTurn":
        ts = data.get("timestamp")
        if isinstance(ts, str):
            data = {**data, "timestamp": datetime.fromisoformat(ts)}
        return cls(**data)


# ─── Canvas Snapshot ──────────────────────────────────────────────────────────

class CanvasSnapshot(_StrictBase):
    """Metadata for a canvas PNG stored in GCS."""

    snapshot_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    gcs_path: str = Field(description="GCS object path: snapshots/{session_id}/{timestamp}.png")
    public_url: str = Field(description="Public HTTPS URL of the PNG in GCS")
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def to_firestore_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "gcs_path": self.gcs_path,
            "public_url": self.public_url,
            "uploaded_at": self.uploaded_at.isoformat(),
        }

    @classmethod
    def from_firestore_dict(cls, data: dict[str, object]) -> "CanvasSnapshot":
        ts = data.get("uploaded_at")
        if isinstance(ts, str):
            data = {**data, "uploaded_at": datetime.fromisoformat(ts)}
        return cls(**data)


# ─── Session ──────────────────────────────────────────────────────────────────

class SessionCreate(_StrictBase):
    """Request body for POST /sessions."""

    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Optional caller-supplied session identifier",
    )
    student_id: str | None = Field(
        default=None,
        description=(
            "Optional student identifier. "
            "Ignored when SESSION_AUTH_ENABLED=true (derived from token claims)."
        ),
    )
    topic: str | None = Field(
        default=None,
        max_length=120,
        description="Optional initial topic hint (e.g. 'Pythagorean theorem')",
    )


class Session(_StrictBase):
    """Full session document as stored in Firestore and returned by the API."""

    session_id: str = Field(default_factory=lambda: uuid4().hex)
    student_id: str
    topic: str | None = None
    status: Literal["active", "ended"] = "active"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    turn_count: int = Field(default=0, ge=0)
    last_turn_at: datetime | None = None
    turns: list[ConversationTurn] = Field(default_factory=list)
    latest_snapshot: CanvasSnapshot | None = None

    def to_firestore_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "topic": self.topic,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "turn_count": self.turn_count,
            "last_turn_at": (
                self.last_turn_at.isoformat()
                if self.last_turn_at is not None
                else None
            ),
            "turns": [t.to_firestore_dict() for t in self.turns],
            "latest_snapshot": (
                self.latest_snapshot.to_firestore_dict()
                if self.latest_snapshot
                else None
            ),
        }

    def to_firestore_summary_dict(self) -> dict[str, object]:
        """Session summary fields persisted on the root session document."""
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "topic": self.topic,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "turn_count": self.turn_count,
            "last_turn_at": (
                self.last_turn_at.isoformat()
                if self.last_turn_at is not None
                else None
            ),
            "latest_snapshot": (
                self.latest_snapshot.to_firestore_dict()
                if self.latest_snapshot
                else None
            ),
        }

    @classmethod
    def from_firestore_dict(cls, data: dict[str, object]) -> "Session":
        """Reconstruct a Session from a raw Firestore document dict."""
        turns_raw: list[dict[str, object]] = data.get("turns", [])  # type: ignore[assignment]
        snapshot_raw: dict[str, object] | None = data.get("latest_snapshot")  # type: ignore[assignment]

        def _to_dt(val: object) -> datetime:
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            raise ValueError(f"Unexpected timestamp type: {type(val)}")

        def _to_optional_dt(val: object) -> datetime | None:
            if val is None:
                return None
            return _to_dt(val)

        return cls(
            session_id=str(data["session_id"]),
            student_id=str(data["student_id"]),
            topic=data.get("topic"),  # type: ignore[arg-type]
            status=str(data.get("status", "active")),  # type: ignore[arg-type]
            created_at=_to_dt(data["created_at"]),
            updated_at=_to_dt(data["updated_at"]),
            turn_count=int(data.get("turn_count", len(turns_raw))),
            last_turn_at=_to_optional_dt(data.get("last_turn_at")),
            turns=[ConversationTurn.from_firestore_dict(t) for t in turns_raw],
            latest_snapshot=(
                CanvasSnapshot.from_firestore_dict(snapshot_raw)
                if snapshot_raw
                else None
            ),
        )


# ─── API Request/Response helpers ─────────────────────────────────────────────

class AppendTurnRequest(_StrictBase):
    """Request body for POST /sessions/{id}/turns."""

    role: Literal["student", "sona"]
    content: str = Field(min_length=1, max_length=8_000)
    metadata: dict[str, object] | None = None


class SnapshotUploadResponse(_StrictBase):
    """Response body for POST /sessions/{id}/snapshot."""

    session_id: str
    snapshot: CanvasSnapshot


class HealthResponse(_StrictBase):
    """Response body for GET /health."""

    status: Literal["ok"] = "ok"
    service: Literal["session"] = "session"
