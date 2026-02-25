"""Normalized point templates used by the drawing translator."""

from __future__ import annotations

import math

from models import Point


def right_triangle() -> list[Point]:
    return [
        Point(x=0.1, y=0.9),
        Point(x=0.9, y=0.9),
        Point(x=0.1, y=0.1),
        Point(x=0.1, y=0.9),
    ]


def circle_outline(segments: int = 40) -> list[Point]:
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
    # One continuous polyline includes baseline and short tick marks.
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
    # Polyline path draws x-axis, then y-axis, then simple arrowheads.
    return [
        Point(x=0.05, y=0.5),
        Point(x=0.95, y=0.5),
        Point(x=0.9, y=0.45),
        Point(x=0.95, y=0.5),
        Point(x=0.9, y=0.55),
        Point(x=0.5, y=0.5),
        Point(x=0.5, y=0.95),
        Point(x=0.45, y=0.9),
        Point(x=0.5, y=0.95),
        Point(x=0.55, y=0.9),
        Point(x=0.5, y=0.5),
        Point(x=0.5, y=0.05),
    ]
