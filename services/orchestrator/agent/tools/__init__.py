"""Tool exports for drawing and math helpers."""

# Original granular tools (used internally and by existing tests).
from agent.tools.core import clear_canvas, draw_freehand, draw_shape, draw_text, highlight_region
from agent.tools.editing import (
    delete_elements,
    erase_region,
    move_elements,
    resize_elements,
    set_shape_labels,
    update_element_points,
    update_element_style,
)
from agent.tools.math_helpers import draw_axes_grid, draw_number_line, mark_graph_intersection, plot_function_2d

# Unified tools plus the single agent-facing batch dispatcher.
from agent.tools.unified import canvas_actions, draw, edit_canvas, graph, highlight

__all__ = [
    # Agent-facing batch tool
    "canvas_actions",
    # Unified building blocks
    "draw",
    "edit_canvas",
    "graph",
    "highlight",
    # Original (internal / tests)
    "draw_shape",
    "draw_text",
    "draw_freehand",
    "highlight_region",
    "clear_canvas",
    "delete_elements",
    "erase_region",
    "move_elements",
    "resize_elements",
    "set_shape_labels",
    "update_element_points",
    "update_element_style",
    "draw_axes_grid",
    "draw_number_line",
    "plot_function_2d",
    "mark_graph_intersection",
]
