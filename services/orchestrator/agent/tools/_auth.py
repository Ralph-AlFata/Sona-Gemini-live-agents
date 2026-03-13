"""Per-request auth token context for orchestrator tool calls."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_auth_token: ContextVar[str | None] = ContextVar("orchestrator_auth_token", default=None)


@contextmanager
def auth_token_span(token: str | None) -> Iterator[None]:
    token_handle = _auth_token.set(token)
    try:
        yield
    finally:
        _auth_token.reset(token_handle)


def get_current_auth_token() -> str | None:
    return _auth_token.get()
