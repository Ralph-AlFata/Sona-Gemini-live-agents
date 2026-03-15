# S2: System Prompt Constraints

**Priority**: High impact, zero code risk
**Risk**: None (prompt-only change)
**Files modified**: 1
**Estimated scope**: ~20 lines added to prompt

---

## Goal

Add explicit instructions to the Gemini system prompt that prevent the model from making duplicate or excessive tool calls. This leverages Google's own recommended best practice of "progress recapping" and "invocation conditions."

---

## Step-by-Step Plan

### Step 1: Analyze current prompt gaps

**File**: `services/orchestrator/agent/agent.py:25-75`

Current prompt tells Sona:
- How to use the coordinate system
- How to format tool parameters
- When to prefer certain tools

Missing:
- Any constraint on tool call frequency
- Any instruction to avoid repeating calls
- Any progress-tracking guidance (Google's official loop prevention)
- Any instruction to check tool call results before calling again

### Step 2: Add "Drawing Discipline" section to SYSTEM_PROMPT

**File**: `services/orchestrator/agent/agent.py`

Append the following block **after** the existing "Tool usage policy" section (after line 73, before the closing `""".strip()`):

```
Drawing discipline (CRITICAL — follow these rules strictly):
- NEVER call the same drawing tool twice with identical or near-identical parameters.
  Each tool call response includes created_element_ids confirming the element exists.
  If you received a successful response with an element ID, that element is drawn. Do NOT redraw it.
- Call ONE drawing tool at a time. After each call, speak to the student about what
  you just drew before making the next drawing call. This creates a natural teach-then-draw rhythm.
- Before making any drawing call, mentally inventory what is already on the canvas
  based on the element IDs you have received. Do not draw over existing elements
  unless deliberately replacing them (in which case, delete the old one first).
- When you are about to call a tool, verify:
  1. Have I already drawn this exact element? (check your received element IDs)
  2. Is this call meaningfully different from my last call?
  3. Am I under the 5-call limit for this turn?
  If any check fails, do NOT make the call.
```

### Step 3: Add "Progress Tracking" instruction

This is Google's **official recommendation** from their troubleshooting docs for preventing loops.

Append after the drawing discipline section:

```
Progress tracking:
- Before each response, briefly recall what you have already drawn and said in this session.
- Consider whether the current task is already complete before making additional tool calls.
- If the student hasn't responded yet, do not continue drawing — wait for their input.
```

### Step 4: Add invocation conditions to tool docstrings

**File**: `services/orchestrator/agent/tools/core.py`

Update each tool's docstring to include an explicit "Invocation Condition" line. This follows Google's best practice for Live API tool definitions.

Example for `draw_shape` (line 115-131):

Add to the docstring:
```
Invocation condition: Call this tool ONLY when you need to draw a NEW shape
that does not already exist on the canvas. Never call with the same shape
and points as a previous successful call.
```

Repeat for:
- `draw_text` — "Call ONLY when placing NEW text not already on the canvas."
- `draw_freehand` — "Call ONLY for NEW freehand strokes."
- `highlight_region` — "Call ONLY when highlighting elements not already highlighted."

**File**: `services/orchestrator/agent/tools/editing.py`

- `delete_elements` — "Call ONLY with element IDs confirmed to exist."
- `move_elements` — "Call ONLY when repositioning is needed. Do not call repeatedly with same dx/dy."

**File**: `services/orchestrator/agent/tools/math_helpers.py`

- `draw_axes_grid` — "Call ONCE per graph. Do not redraw the grid."
- `plot_function_2d` — "Call ONCE per function expression. Do not replot the same expression."
- `draw_number_line` — "Call ONCE per number line."

### Step 5: Verify prompt token count

After adding all text, verify the prompt stays within reasonable limits:
- Current prompt: ~1500 characters (~400 tokens)
- Added text: ~1200 characters (~300 tokens)
- Total: ~2700 characters (~700 tokens) — well within limits

### Step 6: Test with live session

1. Start the orchestrator + drawing service locally
2. Connect via frontend
3. Ask Sona to "draw a right triangle and label its sides"
4. Observe tool call logs — should see:
   - One `draw_shape` call (triangle)
   - Speech about the triangle
   - One or more `draw_text` calls (labels)
   - NO duplicate `draw_shape` calls
5. Ask Sona to "now explain the Pythagorean theorem using this triangle"
6. Observe — should NOT redraw the triangle, should reference existing element IDs

---

## Verification Checklist

- [ ] No duplicate `TOOL_CALL_REQUEST` entries in logs for same operation+payload
- [ ] Sona speaks between tool calls (teach-then-draw rhythm)
- [ ] Sona references `created_element_ids` from previous calls (e.g., highlighting existing elements)
- [ ] Tool call count per turn stays at or below 5
- [ ] Sona still draws correctly when asked (no over-suppression)

---

## Rollback

Revert the single file `agent.py` to remove the added prompt sections. No code changes to undo.
