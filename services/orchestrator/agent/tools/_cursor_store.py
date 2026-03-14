"""Per-session cursor state storage."""

from __future__ import annotations

import time
from typing import Mapping

from agent.tools._cursor import CursorState, TOP_MARGIN

_sessions: dict[str, tuple[CursorState, float]] = {}
_TTL_SECONDS = 3600


def get_cursor(session_id: str) -> CursorState:
    """Return existing cursor for a session or create a new one."""
    now = time.monotonic()
    existing = _sessions.get(session_id)
    if existing is not None:
        state, _ = existing
        _sessions[session_id] = (state, now)
        return state

    state = CursorState()
    _sessions[session_id] = (state, now)
    _cleanup_stale(now)
    return state


def set_cursor(session_id: str, snapshot: Mapping[str, object]) -> CursorState:
    """Hydrate/overwrite a session cursor from a persisted snapshot."""
    state = CursorState.from_snapshot_dict(snapshot)
    now = time.monotonic()
    _sessions[session_id] = (state, now)
    _cleanup_stale(now)
    return state


def get_cursor_snapshot(session_id: str) -> dict[str, float]:
    """Return a serializable cursor snapshot for persistence."""
    return get_cursor(session_id).to_snapshot_dict()


def update_cursor_viewport(
    session_id: str,
    *,
    canvas_width_px: float,
    canvas_height_px: float,
    bottom_padding: float = 0.03,
) -> CursorState:
    """Update cursor bottom boundary from actual whiteboard pixel dimensions."""
    width = float(canvas_width_px)
    height = float(canvas_height_px)
    if width <= 0 or height <= 0:
        raise ValueError("canvas_width_px and canvas_height_px must be greater than 0")

    y_max = height / width
    safe_padding = max(0.0, bottom_padding)
    bottom_edge = max(TOP_MARGIN + 0.05, min(2.0, y_max - safe_padding))

    state = get_cursor(session_id)
    state.set_bottom_edge(bottom_edge)
    _sessions[session_id] = (state, time.monotonic())
    return state


def clear_cursor(session_id: str) -> None:
    """Reset a session cursor to the initial origin."""
    state = _sessions.get(session_id)
    if state is None:
        return
    state[0].clear()
    _sessions[session_id] = (state[0], time.monotonic())


def _cleanup_stale(now: float | None = None) -> None:
    ts_now = time.monotonic() if now is None else now
    stale_keys = [key for key, (_, ts) in _sessions.items() if ts_now - ts > _TTL_SECONDS]
    for key in stale_keys:
        del _sessions[key]
