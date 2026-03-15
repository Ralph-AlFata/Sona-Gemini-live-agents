"""Tool call deduplication for preventing duplicate drawing commands."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

from drawing_client import DrawingCommandResult

logger = logging.getLogger(__name__)

# Operations that should never be deduplicated.
SKIP_DEDUP_OPERATIONS: frozenset[str] = frozenset({"clear_canvas"})


class ToolCallDeduplicator:
    """Time-window deduplicator for tool calls.

    Caches the result of recent ``(session_id, operation, payload)`` triples.
    If the same triple is seen again within ``window_seconds``, the cached
    result metadata is used to suppress re-execution.
    """

    def __init__(self, window_seconds: float = 2.0, max_entries: int = 200) -> None:
        self._window = window_seconds
        self._max_entries = max_entries
        # key -> (monotonic_timestamp, cached_result)
        self._cache: dict[str, tuple[float, DrawingCommandResult]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _make_key(session_id: str, operation: str, payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, default=str)
        raw = f"{session_id}:{operation}:{canonical}"
        return hashlib.md5(raw.encode()).hexdigest()

    async def get(
        self, session_id: str, operation: str, payload: dict
    ) -> DrawingCommandResult | None:
        if operation in SKIP_DEDUP_OPERATIONS:
            return None

        key = self._make_key(session_id, operation, payload)
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts, result = entry
            if time.monotonic() - ts > self._window:
                self._cache.pop(key, None)
                return None
            return result

    async def put(
        self, session_id: str, operation: str, payload: dict, result: DrawingCommandResult
    ) -> None:
        if operation in SKIP_DEDUP_OPERATIONS:
            return

        key = self._make_key(session_id, operation, payload)
        now = time.monotonic()
        async with self._lock:
            self._cache[key] = (now, result)
            self._evict(now)

    def _evict(self, now: float) -> None:
        """Remove expired entries; trim to max size if needed.

        Must be called while ``self._lock`` is held.
        """
        cutoff = now - (self._window * 2)
        expired = [k for k, (ts, _) in self._cache.items() if ts < cutoff]
        for k in expired:
            del self._cache[k]

        if len(self._cache) > self._max_entries:
            sorted_keys = sorted(self._cache, key=lambda k: self._cache[k][0])
            for k in sorted_keys[: len(self._cache) - self._max_entries]:
                del self._cache[k]
