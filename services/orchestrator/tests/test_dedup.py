"""Tests for ToolCallDeduplicator."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from agent.tools._dedup import SKIP_DEDUP_OPERATIONS, ToolCallDeduplicator
from drawing_client import DrawingCommandResult


def _make_result(
    operation: str = "draw_shape",
    command_id: str = "cmd_abc",
    element_ids: list[str] | None = None,
) -> DrawingCommandResult:
    return DrawingCommandResult(
        session_id="sess1",
        command_id=command_id,
        operation=operation,
        applied_count=1,
        created_element_ids=element_ids or ["el_001"],
        failed_operations=[],
        emitted_count=1,
    )


SHAPE_PAYLOAD = {
    "shape": "rectangle",
    "points": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.5}],
    "style": {"stroke_color": "#111"},
}


@pytest.mark.asyncio
async def test_first_call_returns_none() -> None:
    dedup = ToolCallDeduplicator(window_seconds=2.0)
    result = await dedup.get("sess1", "draw_shape", SHAPE_PAYLOAD)
    assert result is None


@pytest.mark.asyncio
async def test_identical_call_within_window_returns_cached() -> None:
    dedup = ToolCallDeduplicator(window_seconds=2.0)
    original = _make_result()
    await dedup.put("sess1", "draw_shape", SHAPE_PAYLOAD, original)

    cached = await dedup.get("sess1", "draw_shape", SHAPE_PAYLOAD)
    assert cached is not None
    assert cached.command_id == original.command_id
    assert cached.created_element_ids == original.created_element_ids


@pytest.mark.asyncio
async def test_identical_call_after_window_returns_none() -> None:
    dedup = ToolCallDeduplicator(window_seconds=0.05)
    await dedup.put("sess1", "draw_shape", SHAPE_PAYLOAD, _make_result())

    await asyncio.sleep(0.1)

    cached = await dedup.get("sess1", "draw_shape", SHAPE_PAYLOAD)
    assert cached is None


@pytest.mark.asyncio
async def test_different_payload_not_deduplicated() -> None:
    dedup = ToolCallDeduplicator(window_seconds=2.0)
    await dedup.put("sess1", "draw_shape", SHAPE_PAYLOAD, _make_result())

    different_payload = {
        "shape": "circle",
        "points": [{"x": 0.2, "y": 0.2}, {"x": 0.6, "y": 0.6}],
        "style": {"stroke_color": "#222"},
    }
    cached = await dedup.get("sess1", "draw_shape", different_payload)
    assert cached is None


@pytest.mark.asyncio
async def test_different_session_not_deduplicated() -> None:
    dedup = ToolCallDeduplicator(window_seconds=2.0)
    await dedup.put("sess1", "draw_shape", SHAPE_PAYLOAD, _make_result())

    cached = await dedup.get("sess2", "draw_shape", SHAPE_PAYLOAD)
    assert cached is None


@pytest.mark.asyncio
async def test_different_operation_not_deduplicated() -> None:
    dedup = ToolCallDeduplicator(window_seconds=2.0)
    await dedup.put("sess1", "draw_shape", SHAPE_PAYLOAD, _make_result())

    cached = await dedup.get("sess1", "draw_text", SHAPE_PAYLOAD)
    assert cached is None


@pytest.mark.asyncio
async def test_skip_operations_not_cached() -> None:
    dedup = ToolCallDeduplicator(window_seconds=2.0)

    for op in SKIP_DEDUP_OPERATIONS:
        await dedup.put("sess1", op, {"mode": "full"}, _make_result(operation=op))
        cached = await dedup.get("sess1", op, {"mode": "full"})
        assert cached is None, f"{op} should not be cached"


@pytest.mark.asyncio
async def test_eviction_removes_old_entries() -> None:
    dedup = ToolCallDeduplicator(window_seconds=0.05, max_entries=5)

    # Fill cache with 5 entries
    for i in range(5):
        payload = {"index": i}
        await dedup.put("sess1", "draw_shape", payload, _make_result(command_id=f"cmd_{i}"))

    # Wait for them to expire
    await asyncio.sleep(0.15)

    # Add a new entry to trigger eviction
    new_payload = {"index": 99}
    await dedup.put("sess1", "draw_shape", new_payload, _make_result(command_id="cmd_new"))

    # Old entries should be gone
    for i in range(5):
        cached = await dedup.get("sess1", "draw_shape", {"index": i})
        assert cached is None

    # New entry should exist
    cached = await dedup.get("sess1", "draw_shape", new_payload)
    assert cached is not None
    assert cached.command_id == "cmd_new"


@pytest.mark.asyncio
async def test_max_entries_evicts_oldest() -> None:
    dedup = ToolCallDeduplicator(window_seconds=10.0, max_entries=3)

    for i in range(5):
        payload = {"index": i}
        await dedup.put("sess1", "draw_shape", payload, _make_result(command_id=f"cmd_{i}"))

    # Oldest entries (0, 1) should have been evicted; newest (2, 3, 4) remain
    assert await dedup.get("sess1", "draw_shape", {"index": 0}) is None
    assert await dedup.get("sess1", "draw_shape", {"index": 1}) is None
    assert await dedup.get("sess1", "draw_shape", {"index": 4}) is not None


@pytest.mark.asyncio
async def test_concurrent_access_safe() -> None:
    dedup = ToolCallDeduplicator(window_seconds=2.0)

    async def put_and_get(index: int) -> DrawingCommandResult | None:
        payload = {"index": index % 3}  # intentional overlap
        result = _make_result(command_id=f"cmd_{index}")
        await dedup.put("sess1", "draw_shape", payload, result)
        return await dedup.get("sess1", "draw_shape", payload)

    results = await asyncio.gather(*[put_and_get(i) for i in range(20)])
    # All should return a result (no None, no exception)
    assert all(r is not None for r in results)


@pytest.mark.asyncio
async def test_payload_key_order_independent() -> None:
    """Payloads with same content but different key order should deduplicate."""
    dedup = ToolCallDeduplicator(window_seconds=2.0)

    payload_a = {"shape": "rect", "color": "#111"}
    payload_b = {"color": "#111", "shape": "rect"}

    await dedup.put("sess1", "draw_shape", payload_a, _make_result())
    cached = await dedup.get("sess1", "draw_shape", payload_b)
    assert cached is not None
