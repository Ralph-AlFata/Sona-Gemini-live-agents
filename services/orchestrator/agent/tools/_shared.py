"""Shared helpers for drawing tools."""

from __future__ import annotations

import json
import logging
import time

from google.adk.tools import ToolContext

from agent.tools._dedup import ToolCallDeduplicator
from config import settings
from drawing_client import DrawingClient, DrawingCommandResult

_client: DrawingClient | None = None
_deduplicator: ToolCallDeduplicator | None = None
logger = logging.getLogger(__name__)


def get_client() -> DrawingClient:
    global _client
    if _client is None:
        _client = DrawingClient(settings.drawing_service_url)
    return _client


def _get_deduplicator() -> ToolCallDeduplicator:
    global _deduplicator
    if _deduplicator is None:
        _deduplicator = ToolCallDeduplicator(
            window_seconds=settings.dedup_window_seconds,
            max_entries=settings.dedup_max_entries,
        )
    return _deduplicator


def resolve_session_id(tool_context: ToolContext | None) -> str:
    if tool_context is not None:
        session_id = tool_context.state.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id
    return settings.default_session_id


def result_to_dict(result: DrawingCommandResult) -> dict:
    return {
        "status": "success",
        "operation": result.operation,
        "command_id": result.command_id,
        "applied_count": result.applied_count,
        "created_element_ids": result.created_element_ids,
        "failed_operations": result.failed_operations,
    }


def _payload_preview(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True)[:1000]


async def execute_tool_command(
    *,
    session_id: str,
    operation: str,
    payload: dict,
) -> DrawingCommandResult:
    # --- Deduplication check ---
    dedup = _get_deduplicator()
    cached = await dedup.get(session_id, operation, payload)
    if cached is not None:
        logger.warning(
            "TOOL_CALL_DEDUP session_id=%s operation=%s payload=%s",
            session_id,
            operation,
            _payload_preview(payload),
        )
        return cached

    start = time.perf_counter()
    logger.info(
        "TOOL_CALL_REQUEST session_id=%s operation=%s payload=%s",
        session_id,
        operation,
        _payload_preview(payload),
    )
    try:
        result = await get_client().execute(
            session_id=session_id,
            operation=operation,
            payload=payload,
        )
    except Exception:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.exception(
            "TOOL_CALL_ERROR session_id=%s operation=%s elapsed_ms=%s",
            session_id,
            operation,
            elapsed_ms,
        )
        raise

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "TOOL_CALL_RESPONSE session_id=%s operation=%s elapsed_ms=%s command_id=%s applied_count=%s created=%s failed=%s",
        session_id,
        operation,
        elapsed_ms,
        result.command_id,
        result.applied_count,
        len(result.created_element_ids),
        len(result.failed_operations),
    )

    # --- Cache successful result for dedup ---
    await dedup.put(session_id, operation, payload, result)

    return result
