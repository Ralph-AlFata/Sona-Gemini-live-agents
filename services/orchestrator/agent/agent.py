"""ADK root agent definition for Sona."""

from __future__ import annotations

from google.adk.agents.llm_agent import Agent

from agent.tools import (
    clear_canvas,
    delete_elements,
    draw_axes_grid,
    draw_freehand,
    draw_number_line,
    draw_shape,
    draw_text,
    erase_region,
    highlight_region,
    move_elements,
    plot_function_2d,
    resize_elements,
    update_element_style,
)
from config import settings

SYSTEM_PROMPT = """
You are Sona, a voice-first math tutor working on a shared whiteboard.
Keep explanations concise, structured, and student-friendly.
Use drawing tools to show work step-by-step while speaking.

Tool usage policy:
- Use normalized canvas coordinates in [0, 1].
- Prefer draw_axes_grid, draw_number_line, and plot_function_2d for graphing tasks.
- Use draw_text for labels and short notes.
- When correcting mistakes, use delete/move/resize/update style tools instead of redrawing everything.
- Keep drawings readable; avoid dense overlapping marks.
""".strip()

root_agent = Agent(
    name="sona",
    model=settings.model_name,
    instruction=SYSTEM_PROMPT,
    tools=[
        draw_shape,
        draw_text,
        draw_freehand,
        highlight_region,
        clear_canvas,
        delete_elements,
        erase_region,
        move_elements,
        resize_elements,
        update_element_style,
        draw_axes_grid,
        draw_number_line,
        plot_function_2d,
    ],
)
