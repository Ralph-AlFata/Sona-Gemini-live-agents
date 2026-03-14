"""Canonical label enforcement for shape drawing."""

from __future__ import annotations

import math


def _side_length(p1: dict[str, float], p2: dict[str, float]) -> float:
    """Return the Euclidean distance between two points."""
    return math.hypot(p2["x"] - p1["x"], p2["y"] - p1["y"])


def _get_vertices(points: list[dict[str, float]]) -> list[dict[str, float]]:
    """Extract unique vertices from an open or closed point list."""
    if len(points) >= 3 and points[0] == points[-1]:
        return points[:-1]
    return points


def _enforce_right_triangle(
    points: list[dict[str, float]],
    labels: list[str],
) -> list[str]:
    """Place the last label on the hypotenuse, preserving leg order."""
    if len(labels) != 3:
        return labels

    vertices = _get_vertices(points)
    if len(vertices) != 3:
        return labels

    side_lengths = [
        _side_length(vertices[i], vertices[(i + 1) % 3])
        for i in range(3)
    ]
    hypotenuse_index = max(range(3), key=side_lengths.__getitem__)

    remapped: list[str] = [""] * 3
    remapped[hypotenuse_index] = labels[-1]

    leg_labels = labels[:-1]
    leg_index = 0
    for index in range(3):
        if index == hypotenuse_index:
            continue
        remapped[index] = leg_labels[leg_index]
        leg_index += 1

    return remapped


def enforce_canonical_labels(
    shape: str,
    points: list[dict[str, float]],
    labels: list[str],
) -> list[str]:
    """Remap labels to shape-specific canonical positions when defined."""
    if not labels:
        return labels

    if shape == "right_triangle":
        return _enforce_right_triangle(points, labels)

    return labels
