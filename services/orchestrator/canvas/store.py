"""Per-session canvas state storage with TTL-based cleanup."""
from __future__ import annotations

import time

from canvas.state import CanvasState

_sessions: dict[str, tuple[CanvasState, float]] = {}
_TTL = 3600  # 1 hour


def get_canvas_state(session_id: str) -> CanvasState:
    if session_id in _sessions:
        state, _ = _sessions[session_id]
        _sessions[session_id] = (state, time.monotonic())
        return state
    state = CanvasState()
    _sessions[session_id] = (state, time.monotonic())
    _cleanup_stale()
    return state


def clear_canvas_state(session_id: str) -> None:
    _sessions.pop(session_id, None)


def _cleanup_stale() -> None:
    now = time.monotonic()
    stale = [k for k, (_, ts) in _sessions.items() if now - ts > _TTL]
    for k in stale:
        del _sessions[k]
