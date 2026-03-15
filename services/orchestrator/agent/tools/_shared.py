"""Shared helpers for drawing tools."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from google.adk.tools import ToolContext

from agent.tools._auth import get_current_auth_token
from agent.tools._dedup import ToolCallDeduplicator
from agent.tools._trace import emit_draw_trace
from config import settings
from drawing_client import DrawingClient, DrawingCommandResult

_client: DrawingClient | None = None
_deduplicator: ToolCallDeduplicator | None = None
logger = logging.getLogger(__name__)
_DEDUP_NOTICE = (
    "This exact tool call was ALREADY successful earlier. "
    "DO NOT call the same tool again with the same arguments. "
    "Proceed as if the earlier tool call already completed. "
    "Do not repeat the same narration, redraw, or follow-up for this duplicate call."
)


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
    response = {
        "status": "success",
        "operation": result.operation,
        "command_id": result.command_id,
        "applied_count": result.applied_count,
        "created_element_ids": result.created_element_ids,
        "failed_operations": result.failed_operations,
    }
    if result.deduplicated:
        response["deduplicated"] = True
        response["already_completed"] = True
        response["message"] = result.dedup_notice or _DEDUP_NOTICE
        response["previous_command_id"] = result.prior_command_id or result.command_id
    return response


def _payload_preview(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True)[:1000]


async def execute_tool_command(
    *,
    session_id: str,
    operation: str,
    payload: dict,
    dedup_payload: dict | None = None,
) -> DrawingCommandResult:
    """Execute a drawing command immediately (synchronous tool behavior)."""
    # --- Deduplication check ---
    dedup = _get_deduplicator()
    key_payload = dedup_payload if dedup_payload is not None else payload
    cached = await dedup.get(session_id, operation, key_payload)
    if cached is not None:
        logger.warning(
            "TOOL_CALL_DEDUP session_id=%s operation=%s payload=%s",
            session_id,
            operation,
            _payload_preview(payload),
        )
        return DrawingCommandResult(
            session_id=session_id,
            command_id=cached.command_id,
            operation=operation,
            applied_count=0,
            created_element_ids=list(cached.created_element_ids),
            failed_operations=[],
            emitted_count=0,
            deduplicated=True,
            dedup_notice=_DEDUP_NOTICE,
            prior_command_id=cached.command_id,
        )

    logger.info(
        "TOOL_CALL_EXEC session_id=%s operation=%s payload=%s",
        session_id,
        operation,
        _payload_preview(payload),
    )
    result = await get_client().execute(
        session_id=session_id,
        operation=operation,
        payload=payload,
        command_id=uuid4().hex[:12],
        auth_token=get_current_auth_token(),
    )

    emit_draw_trace(
        {
            "draw_command_request": {
                "command_id": result.command_id,
                "operation": operation,
                "session_id": session_id,
                "payload": payload,
            },
            "dsl_messages": result.dsl_messages,
        }
    )

    # --- Cache result for dedup (uses the pre-generated element IDs) ---
    await dedup.put(session_id, operation, key_payload, result)

    return result
