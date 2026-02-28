"""Tool: write text/equations on the whiteboard."""
from __future__ import annotations

from google.adk.tools import ToolContext

from canvas.store import get_canvas_state
from drawing_client import get_drawing_client
from tools._logging import logged_tool


def estimate_text_width(text: str, font_size: int = 28) -> float:
    """Estimate normalized width for a text span at a given font size."""
    char_width = 0.012 * (font_size / 28)
    wide_chars = sum(1 for c in text if c in "²³√∑∏∫≤≥≠±×÷")
    effective_len = len(text) + wide_chars * 0.5
    return min(effective_len * char_width, 0.44)


@logged_tool
async def write_math(text: str, tool_context: ToolContext) -> dict[str, str]:
    """Write a math expression or plain text at the current cursor position."""
    session_id = str(tool_context.state["session_id"])
    canvas = get_canvas_state(session_id)

    width = estimate_text_width(text, font_size=28)
    height = 0.06
    bbox = canvas.allocate(width, height)

    await get_drawing_client().send_text(
        session_id=session_id,
        text=text,
        x=bbox.x,
        y=bbox.y,
        font_size=28,
        color="#222",
    )
    return {"status": "success", "drawn": f"Wrote: {text}"}
