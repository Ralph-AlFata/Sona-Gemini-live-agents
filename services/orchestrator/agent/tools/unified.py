"""Unified tool wrappers that consolidate 14 tools into 4.

These thin dispatchers reduce the tool surface area Gemini sees, which
decreases hallucinated and duplicate tool calls.  The original functions
in ``core.py``, ``editing.py`` and ``math_helpers.py`` remain unchanged
and continue to be tested independently.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from agent.tools.core import (
    clear_canvas as _clear_canvas,
    draw_freehand as _draw_freehand,
    draw_shape as _draw_shape,
    draw_text as _draw_text,
    highlight_region as _highlight_region,
)
from agent.tools.editing import (
    delete_elements as _delete_elements,
    erase_region as _erase_region,
    move_elements as _move_elements,
    resize_elements as _resize_elements,
    update_element_points as _update_element_points,
    update_element_style as _update_element_style,
)
from agent.tools.math_helpers import (
    draw_axes_grid as _draw_axes_grid,
    draw_number_line as _draw_number_line,
    plot_function_2d as _plot_function_2d,
)


# ---------------------------------------------------------------------------
# 1. draw — shape / text / freehand creation
# ---------------------------------------------------------------------------

async def draw(
    action: str,
    # shape-specific
    shape: str | None = None,
    points: list[dict[str, float]] | None = None,
    # text-specific
    text: str | None = None,
    x: float | None = None,
    y: float | None = None,
    font_size: int = 24,
    # common style
    stroke_color: str = "#111111",
    stroke_width: float = 2.0,
    fill_color: str | None = None,
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    animate: bool = True,
    tool_context: ToolContext | None = None,
) -> dict:
    """Create a new visual element on the canvas.

    action must be one of:
      "shape"    — draw a geometric shape.  Requires `shape` (e.g. "rectangle",
                   "triangle", "circle") and `points` (list of {x, y}).
      "text"     — place a text label.  Requires `text`, `x`, `y`.
      "freehand" — draw a freehand stroke.  Requires `points`.

    Style parameters (stroke_color, stroke_width, fill_color, opacity,
    z_index, delay_ms, animate) apply to all actions.

    Invocation condition: Call ONLY to create a NEW element that does not
    already exist on the canvas.  Never repeat a call whose previous
    response already returned a created_element_id.
    """
    if action == "shape":
        if shape is None or points is None:
            raise ValueError("action='shape' requires 'shape' and 'points'")
        return await _draw_shape(
            shape=shape,
            points=points,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            fill_color=fill_color,
            opacity=opacity,
            z_index=z_index,
            delay_ms=delay_ms,
            animate=animate,
            tool_context=tool_context,
        )

    if action == "text":
        if text is None or x is None or y is None:
            raise ValueError("action='text' requires 'text', 'x', and 'y'")
        return await _draw_text(
            text=text,
            x=x,
            y=y,
            font_size=font_size,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            fill_color=fill_color,
            opacity=opacity,
            z_index=z_index,
            delay_ms=delay_ms,
            animate=animate,
            tool_context=tool_context,
        )

    if action == "freehand":
        if points is None:
            raise ValueError("action='freehand' requires 'points'")
        return await _draw_freehand(
            points=points,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            fill_color=fill_color,
            opacity=opacity,
            z_index=z_index,
            delay_ms=delay_ms,
            animate=animate,
            tool_context=tool_context,
        )

    raise ValueError(f"draw: unknown action '{action}'. Must be 'shape', 'text', or 'freehand'.")


# ---------------------------------------------------------------------------
# 2. edit_canvas — modifications to existing elements + clear
# ---------------------------------------------------------------------------

async def edit_canvas(
    action: str,
    # element targeting
    element_ids: list[str] | None = None,
    element_id: str | None = None,
    # move
    dx: float | None = None,
    dy: float | None = None,
    # resize
    scale_x: float | None = None,
    scale_y: float | None = None,
    # erase_region
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
    # update_points
    points: list[dict[str, float]] | None = None,
    mode: str = "replace",
    # update_style
    stroke_color: str | None = None,
    stroke_width: float | None = None,
    fill_color: str | None = None,
    opacity: float | None = None,
    z_index: int | None = None,
    delay_ms: int | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    """Modify or remove existing canvas elements.

    action must be one of:
      "delete"        — remove elements by ID.  Requires `element_ids`.
      "erase"         — erase everything in a region.  Requires `x`, `y`,
                         `width`, `height`.
      "move"          — translate elements.  Requires `element_ids`, `dx`, `dy`.
      "resize"        — scale elements.  Requires `element_ids`, `scale_x`,
                         `scale_y`.
      "update_points" — replace or append points on an element.  Requires
                         `element_id`, `points`.  Optional `mode`
                         ("replace" or "append").
      "update_style"  — change visual style.  Requires `element_ids` and at
                         least one style field (stroke_color, stroke_width,
                         fill_color, opacity, z_index, delay_ms).
      "clear"         — wipe the entire canvas.

    Invocation condition: Only call when you need to change something that
    already exists.  Do not repeat a call with identical parameters.
    """
    if action == "delete":
        if not element_ids:
            raise ValueError("action='delete' requires 'element_ids'")
        return await _delete_elements(element_ids=element_ids, tool_context=tool_context)

    if action == "erase":
        if x is None or y is None or width is None or height is None:
            raise ValueError("action='erase' requires 'x', 'y', 'width', 'height'")
        return await _erase_region(x=x, y=y, width=width, height=height, tool_context=tool_context)

    if action == "move":
        if not element_ids or dx is None or dy is None:
            raise ValueError("action='move' requires 'element_ids', 'dx', 'dy'")
        return await _move_elements(element_ids=element_ids, dx=dx, dy=dy, tool_context=tool_context)

    if action == "resize":
        if not element_ids or scale_x is None or scale_y is None:
            raise ValueError("action='resize' requires 'element_ids', 'scale_x', 'scale_y'")
        return await _resize_elements(
            element_ids=element_ids, scale_x=scale_x, scale_y=scale_y, tool_context=tool_context,
        )

    if action == "update_points":
        if not element_id or points is None:
            raise ValueError("action='update_points' requires 'element_id' and 'points'")
        return await _update_element_points(
            element_id=element_id, points=points, mode=mode, tool_context=tool_context,
        )

    if action == "update_style":
        if not element_ids:
            raise ValueError("action='update_style' requires 'element_ids'")
        return await _update_element_style(
            element_ids=element_ids,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            fill_color=fill_color,
            opacity=opacity,
            z_index=z_index,
            delay_ms=delay_ms,
            tool_context=tool_context,
        )

    if action == "clear":
        return await _clear_canvas(tool_context=tool_context)

    raise ValueError(
        f"edit_canvas: unknown action '{action}'. "
        "Must be 'delete', 'erase', 'move', 'resize', 'update_points', 'update_style', or 'clear'."
    )


# ---------------------------------------------------------------------------
# 3. graph — axes, number lines, function plotting
# ---------------------------------------------------------------------------

async def graph(
    action: str,
    # common viewport
    x: float = 0.1,
    y: float = 0.05,
    width: float = 0.8,
    height: float = 0.45,
    domain_min: float = -10.0,
    domain_max: float = 10.0,
    y_min: float = -10.0,
    y_max: float = 10.0,
    # axes_grid specific
    grid_lines: int = 10,
    # number_line specific
    min_value: int = -5,
    max_value: int = 5,
    tick_height: float = 0.04,
    # plot_function specific
    expression: str | None = None,
    samples: int = 200,
    tool_context: ToolContext | None = None,
) -> dict:
    """Create mathematical graphs and plots on the canvas.

    action must be one of:
      "axes_grid"     — set up a graph viewport with axes and grid lines.
      "number_line"   — draw a number line with ticks and labels.
                         Requires `x`, `y`, `width`.
      "plot_function" — plot a mathematical expression (e.g. "2*x + 1").
                         Requires `expression`.

    Use matching x/y/width/height/domain_min/domain_max/y_min/y_max between
    axes_grid and plot_function so curves align with the grid.

    Invocation condition: Call axes_grid ONCE per graph.  Call plot_function
    ONCE per expression.  Do not redraw if already on the canvas.
    """
    if action == "axes_grid":
        return await _draw_axes_grid(
            x=x, y=y, width=width, height=height,
            grid_lines=grid_lines,
            domain_min=domain_min, domain_max=domain_max,
            y_min=y_min, y_max=y_max,
            tool_context=tool_context,
        )

    if action == "number_line":
        return await _draw_number_line(
            x=x, y=y, width=width,
            min_value=min_value, max_value=max_value,
            tick_height=tick_height,
            tool_context=tool_context,
        )

    if action == "plot_function":
        if expression is None:
            raise ValueError("action='plot_function' requires 'expression'")
        return await _plot_function_2d(
            expression=expression,
            x=x, y=y, width=width, height=height,
            domain_min=domain_min, domain_max=domain_max,
            y_min=y_min, y_max=y_max,
            samples=samples,
            tool_context=tool_context,
        )

    raise ValueError(
        f"graph: unknown action '{action}'. Must be 'axes_grid', 'number_line', or 'plot_function'."
    )


# ---------------------------------------------------------------------------
# 4. highlight — re-exported directly (already a single purpose tool)
# ---------------------------------------------------------------------------

highlight = _highlight_region
