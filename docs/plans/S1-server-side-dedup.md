# S1: Server-Side Tool Call Deduplication

**Priority**: Highest impact
**Risk**: Low
**Files modified**: 1 (+ 1 test file)
**Estimated scope**: ~80 lines of code

---

## Goal

Prevent duplicate tool calls from reaching the drawing service by deduplicating at the orchestrator's shared execution layer. If the same `(session_id, operation, payload)` is seen within a configurable time window, return the cached result instead of executing again.

---

## Step-by-Step Plan

### Step 1: Create the dedup cache class

**File**: `services/orchestrator/agent/tools/_dedup.py` (new)

Create a `ToolCallDeduplicator` class:

```python
class ToolCallDeduplicator:
    def __init__(self, window_seconds: float = 2.0, max_entries: int = 200):
        ...
```

**Requirements**:
- Store recent calls as `dict[str, tuple[float, DrawingCommandResult]]`
  - Key = MD5 hash of `f"{session_id}:{operation}:{canonical_payload_json}"`
  - Value = `(timestamp_monotonic, cached_result)`
- `get(session_id, operation, payload) -> DrawingCommandResult | None`
  - Compute key hash
  - If key exists and `now - timestamp < window_seconds`, return cached result
  - Otherwise return `None`
- `put(session_id, operation, payload, result) -> None`
  - Store the result with current timestamp
- `_evict()` — called inside `put()`
  - Remove entries older than `window_seconds * 2`
  - If still over `max_entries`, remove oldest entries
- Must be **async-safe** — use `asyncio.Lock` since multiple tool calls may fire concurrently within the same event loop
- Canonical payload JSON: `json.dumps(payload, sort_keys=True, default=str)` to normalize key ordering

### Step 2: Integrate into `execute_tool_command`

**File**: `services/orchestrator/agent/tools/_shared.py`

1. Import `ToolCallDeduplicator` from `_dedup.py`
2. Create module-level instance: `_deduplicator = ToolCallDeduplicator(window_seconds=2.0)`
3. At the top of `execute_tool_command()`, before the HTTP call:
   ```python
   cached = await _deduplicator.get(session_id, operation, payload)
   if cached is not None:
       logger.warning(
           "TOOL_CALL_DEDUP session_id=%s operation=%s",
           session_id, operation,
       )
       return cached
   ```
4. After successful HTTP call, before returning:
   ```python
   await _deduplicator.put(session_id, operation, payload, result)
   ```
5. Do NOT cache errors — only cache successful results

### Step 3: Add configuration

**File**: `services/orchestrator/config.py`

Add two new settings:
```python
dedup_window_seconds: float = 2.0
dedup_max_entries: int = 200
```

Update `_shared.py` to read from `settings.dedup_window_seconds`.

### Step 4: Exclude certain operations from dedup

**File**: `services/orchestrator/agent/tools/_dedup.py`

Some operations should NOT be deduplicated:
- `clear_canvas` — user may intentionally clear twice
- `delete_elements` — deleting same IDs twice is harmless (returns failure on second)

Add a `SKIP_DEDUP_OPERATIONS` set:
```python
SKIP_DEDUP_OPERATIONS = {"clear_canvas"}
```

Check in `execute_tool_command` before dedup lookup.

### Step 5: Write tests

**File**: `services/orchestrator/tests/test_dedup.py` (new)

Tests to write:
1. `test_identical_call_within_window_returns_cached` — same params within 2s returns cache
2. `test_identical_call_after_window_executes_again` — same params after 2s executes fresh
3. `test_different_params_not_deduplicated` — different payload always executes
4. `test_different_sessions_not_deduplicated` — same payload + different session executes
5. `test_different_operations_not_deduplicated` — same payload + different operation executes
6. `test_skip_operations_not_cached` — `clear_canvas` never cached
7. `test_eviction_removes_old_entries` — old entries cleaned up
8. `test_concurrent_access_safe` — multiple concurrent calls don't corrupt state

### Step 6: Verify with logs

After implementation, run the system and check logs for:
- `TOOL_CALL_DEDUP` entries — confirms dedup is catching duplicates
- `TOOL_CALL_REQUEST` / `TOOL_CALL_RESPONSE` entries — confirms non-duplicates still execute
- No `TOOL_CALL_ERROR` entries — confirms dedup doesn't break normal flow

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Two draw_shape calls with same points but different colors | NOT deduplicated (payload differs) |
| Two draw_shape calls with same everything | Deduplicated — second returns cached result |
| draw_shape then draw_text with same coords | NOT deduplicated (different operation) |
| Floating point rounding differences in points | Could miss dedup — acceptable, errs on side of allowing |
| Server restart | Cache cleared — acceptable, cold start re-executes |
| Very rapid burst (10+ calls in <100ms) | All hit cache after first — lock ensures serial check |

---

## Rollback

If dedup causes issues:
- Set `dedup_window_seconds=0.0` in `.env` to effectively disable
- Or remove the `if cached` block in `_shared.py` — single deletion
