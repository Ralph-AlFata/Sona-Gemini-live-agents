"""Tool logging decorator for ADK streaming mode."""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Awaitable, Callable

from google.adk.tools import ToolContext

logger = logging.getLogger("sona.tools")


def logged_tool(func: Callable[..., Awaitable[dict[str, str]]]) -> Callable[..., Awaitable[dict[str, str]]]:
    """Log tool call args/result latency and map unexpected errors to a tool-safe payload."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> dict[str, str]:
        tool_context = kwargs.get("tool_context")
        if tool_context is None:
            for arg in args:
                if isinstance(arg, ToolContext):
                    tool_context = arg
                    break

        session_id = "unknown"
        if isinstance(tool_context, ToolContext):
            session_id = str(tool_context.state.get("session_id", "unknown"))

        start = time.monotonic()
        logger.info(
            "tool_call | session=%s | tool=%s | args=%s",
            session_id,
            func.__name__,
            {k: v for k, v in kwargs.items() if k != "tool_context"},
        )

        try:
            result = await func(*args, **kwargs)
        except Exception:
            latency_ms = (time.monotonic() - start) * 1000
            logger.exception(
                "tool_error | session=%s | tool=%s | latency=%.0fms",
                session_id,
                func.__name__,
                latency_ms,
            )
            return {"status": "error", "message": "Internal tool error"}

        latency_ms = (time.monotonic() - start) * 1000
        logger.info(
            "tool_done | session=%s | tool=%s | latency=%.0fms | status=%s",
            session_id,
            func.__name__,
            latency_ms,
            result.get("status", "?"),
        )
        return result

    return wrapper
