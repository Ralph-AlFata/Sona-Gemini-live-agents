"""Per-session command batch that collects tool calls for a single HTTP flush.

During a model turn, each tool call queues its command here instead of
sending an individual HTTP request.  When the turn ends, the orchestrator
flushes the batch as a single ``POST /draw/batch`` call.

Element IDs for creation operations are pre-generated so that tool results
returned to Gemini are consistent with what the drawing service will use.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from drawing_client import BatchResult, DrawingCommandResult

logger = logging.getLogger(__name__)

# Operations that create new canvas elements and need a pre-generated ID.
_CREATION_OPS = frozenset({"draw_shape", "draw_text", "draw_freehand"})


class CommandBatch:
    """Accumulates draw commands for a single session turn."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.commands: list[dict] = []
        self._lock = asyncio.Lock()

    async def queue(self, operation: str, payload: dict) -> DrawingCommandResult:
        """Queue a command and return a synthetic result immediately.

        For creation operations, a pre-generated element ID is included in both
        the queued payload and the synthetic result so that Gemini can reference
        it in later tool calls within the same turn.
        """
        command_id = uuid4().hex[:12]
        element_id = f"el_{uuid4().hex[:12]}" if operation in _CREATION_OPS else None
        created_ids = [element_id] if element_id else []

        command = {
            "command_id": command_id,
            "operation": operation,
            "session_id": self.session_id,
            "payload": payload,
        }
        if element_id is not None:
            command["element_id"] = element_id

        async with self._lock:
            self.commands.append(command)

        logger.info(
            "BATCH_QUEUE session_id=%s operation=%s element_id=%s batch_size=%d",
            self.session_id,
            operation,
            element_id,
            len(self.commands),
        )

        return DrawingCommandResult(
            session_id=self.session_id,
            command_id=command_id,
            operation=operation,
            applied_count=1,
            created_element_ids=created_ids,
            failed_operations=[],
            emitted_count=0,
        )

    async def drain(self) -> list[dict]:
        """Return all queued commands and clear the batch."""
        async with self._lock:
            commands = self.commands.copy()
            self.commands.clear()
        return commands


# ---------------------------------------------------------------------------
# Global batch registry keyed by session_id
# ---------------------------------------------------------------------------

_active_batches: dict[str, CommandBatch] = {}
_registry_lock = asyncio.Lock()


async def get_or_create_batch(session_id: str) -> CommandBatch:
    async with _registry_lock:
        if session_id not in _active_batches:
            _active_batches[session_id] = CommandBatch(session_id)
        return _active_batches[session_id]


async def pop_batch(session_id: str) -> CommandBatch | None:
    async with _registry_lock:
        return _active_batches.pop(session_id, None)
