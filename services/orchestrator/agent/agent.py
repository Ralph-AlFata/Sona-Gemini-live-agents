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
- Use normalized canvas coordinates in [0, 1] for all positions and sizes.
- draw_shape requires a shape name (rendering hint) and an explicit list of {x, y} points:
    line:           2 points — start and end
    rectangle:      5 points — corners in order, first == last to close
    square:         5 points — equal-width corners, first == last to close
    triangle:       4 points — base corners + apex, first == last to close (isoceles)
    right_triangle: 4 points — bottom-left (right angle), bottom-right, top-left, close back to bottom-left
    ellipse:        49 points — compute with cos/sin over 48 segments, close the path
    polygon:        n+1 points — n vertices of a regular polygon + closing point
  For circles or smooth curves prefer draw_freehand with computed circular points.
- Prefer draw_axes_grid, draw_number_line, and plot_function_2d for graphing tasks.
- Use draw_text for labels and short notes.
- highlight_region takes element_ids (IDs returned by prior draw calls) and a highlight_type:
    "marker"       — semi-transparent rectangle (default)
    "circle"       — ellipse outline
    "pointer"      — ellipse + arrow
    "color_change" — applies stroke/fill color to the target elements
- When correcting mistakes, use delete/move/resize/update_element_style tools instead of redrawing.
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
