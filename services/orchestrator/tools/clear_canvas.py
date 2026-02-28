"""Tool: clear whiteboard and reset cursor state."""
from __future__ import annotations

from google.adk.tools import ToolContext

from canvas.store import get_canvas_state
from drawing_client import get_drawing_client
from tools._logging import logged_tool


@logged_tool
async def clear_canvas(tool_context: ToolContext) -> dict[str, str]:
    """Erase everything on the whiteboard and reset cursor position."""
    session_id = str(tool_context.state["session_id"])
    canvas = get_canvas_state(session_id)
    await get_drawing_client().send_clear(session_id)
    canvas.clear()
    return {"status": "success", "drawn": "Canvas cleared"}
