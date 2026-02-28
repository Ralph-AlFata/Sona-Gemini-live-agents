"""Shape renderer registry."""
from __future__ import annotations

from typing import Awaitable, Callable

from renderers.circle import render_circle
from renderers.graph import render_graph
from renderers.number_line import render_number_line
from renderers.polygon import render_regular_polygon
from renderers.quadrilateral import (
    render_parallelogram,
    render_rhombus,
    render_trapezoid,
)
from renderers.rectangle import render_rectangle
from renderers.triangle import render_right_triangle, render_triangle

Renderer = Callable[..., Awaitable[str]]

SHAPE_REGISTRY: dict[str, Renderer] = {
    "triangle": render_triangle,
    "right triangle": render_right_triangle,
    "circle": render_circle,
    "rectangle": render_rectangle,
    "square": render_rectangle,
    "rhombus": render_rhombus,
    "parallelogram": render_parallelogram,
    "trapezoid": render_trapezoid,
    "pentagon": render_regular_polygon(5),
    "hexagon": render_regular_polygon(6),
    "octagon": render_regular_polygon(8),
    "number line": render_number_line,
}

__all__ = [
    "SHAPE_REGISTRY",
    "render_graph",
]
