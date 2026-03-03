"""Tool exports for drawing and math helpers."""

from agent.tools.core import clear_canvas, draw_freehand, draw_shape, draw_text, highlight_region
from agent.tools.editing import (
    delete_elements,
    erase_region,
    move_elements,
    resize_elements,
    update_element_points,
    update_element_style,
)
from agent.tools.math_helpers import draw_axes_grid, draw_number_line, plot_function_2d

__all__ = [
    "draw_shape",
    "draw_text",
    "draw_freehand",
    "highlight_region",
    "clear_canvas",
    "delete_elements",
    "erase_region",
    "move_elements",
    "resize_elements",
    "update_element_points",
    "update_element_style",
    "draw_axes_grid",
    "draw_number_line",
    "plot_function_2d",
]
