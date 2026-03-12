"""Per-turn trace hook for drawing tool commands."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

DrawTraceCallback = Callable[[dict[str, Any]], None]

_draw_trace_callback: ContextVar[DrawTraceCallback | None] = ContextVar(
    "draw_trace_callback",
    default=None,
)


@contextmanager
def draw_trace_span(callback: DrawTraceCallback) -> Iterator[None]:
    """Attach a draw trace callback to the current async context."""
    token = _draw_trace_callback.set(callback)
    try:
        yield
    finally:
        _draw_trace_callback.reset(token)


def emit_draw_trace(event: dict[str, Any]) -> None:
    """Emit a draw trace event to the active callback, if any."""
    callback = _draw_trace_callback.get()
    if callback is None:
        return
    callback(event)
