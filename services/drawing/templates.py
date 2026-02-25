"""Normalized point templates used by the drawing translator.

Each function returns a list of Points in [0, 1] normalized coordinates.
The drawing service transforms these into absolute canvas coordinates
based on the ShapePayload's position and size.
"""

from __future__ import annotations

import math

from models import Point


def right_triangle() -> list[Point]:
    """Closed right triangle: bottom-left → bottom-right → top-left → close."""
    return [
        Point(x=0.1, y=0.9),
        Point(x=0.9, y=0.9),
        Point(x=0.1, y=0.1),
        Point(x=0.1, y=0.9),
    ]


def circle_outline(segments: int = 40) -> list[Point]:
    """Circle centered at (0.5, 0.5) with radius 0.4, closing back to start."""
    points: list[Point] = []
    for i in range(segments + 1):
        theta = (2 * math.pi * i) / segments
        points.append(
            Point(
                x=0.5 + 0.4 * math.cos(theta),
                y=0.5 + 0.4 * math.sin(theta),
            )
        )
    return points


def number_line() -> list[Point]:
    """Horizontal number line with 5 evenly spaced tick marks."""
    points: list[Point] = [Point(x=0.05, y=0.5), Point(x=0.95, y=0.5)]
    for x in (0.2, 0.35, 0.5, 0.65, 0.8):
        points.extend(
            [
                Point(x=x, y=0.45),
                Point(x=x, y=0.55),
                Point(x=x, y=0.5),
            ]
        )
    return points


def cartesian_axes() -> list[Point]:
    """X-axis and Y-axis with arrowheads, centered at (0.5, 0.5)."""
    return [
        # X-axis left → right
        Point(x=0.05, y=0.5),
        Point(x=0.95, y=0.5),
        # X arrowhead
        Point(x=0.9, y=0.45),
        Point(x=0.95, y=0.5),
        Point(x=0.9, y=0.55),
        # Move to center
        Point(x=0.5, y=0.5),
        # Y-axis bottom → top (note: y=0.95 is bottom in screen coords)
        Point(x=0.5, y=0.95),
        # Y arrowhead at bottom
        Point(x=0.45, y=0.9),
        Point(x=0.5, y=0.95),
        Point(x=0.55, y=0.9),
        # Back to center then up
        Point(x=0.5, y=0.5),
        Point(x=0.5, y=0.05),
    ]
