"""Tool: advance cursor to the next whiteboard line."""
from __future__ import annotations

from google.adk.tools import ToolContext

from canvas.store import get_canvas_state
from tools._logging import logged_tool


@logged_tool
async def new_line(tool_context: ToolContext) -> dict[str, str]:
    """Move the writing cursor down to a new line."""
    session_id = str(tool_context.state["session_id"])
    canvas = get_canvas_state(session_id)
    canvas.newline()
    return {"status": "success"}
