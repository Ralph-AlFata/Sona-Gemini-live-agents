"""Execution-mode flags for orchestrator tools."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_fire_and_forget_enabled: ContextVar[bool] = ContextVar(
    "fire_and_forget_enabled",
    default=False,
)


@contextmanager
def fire_and_forget_tool_calls(enabled: bool) -> Iterator[None]:
    token = _fire_and_forget_enabled.set(enabled)
    try:
        yield
    finally:
        _fire_and_forget_enabled.reset(token)


def is_fire_and_forget_enabled() -> bool:
    return _fire_and_forget_enabled.get()
