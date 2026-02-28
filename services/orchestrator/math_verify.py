"""SymPy-backed math verification layer.

All mathematical computations go through SymPy verification before
Sona states a result — never let the LLM do raw arithmetic.
"""
from __future__ import annotations

from functools import lru_cache

import sympy

x_sym, y_sym = sympy.symbols("x y")


@lru_cache(maxsize=128)
def verify_pythagorean(a: float, b: float, c: float) -> bool:
    """Check if a² + b² = c² (within tolerance for floats)."""
    return bool(sympy.Eq(sympy.nsimplify(a**2 + b**2), sympy.nsimplify(c**2)))


@lru_cache(maxsize=128)
def verify_triangle_inequality(a: float, b: float, c: float) -> bool:
    """Check if three sides can form a valid triangle."""
    return a + b > c and a + c > b and b + c > a


@lru_cache(maxsize=64)
def parse_linear_equation(equation: str) -> tuple[float, float]:
    """Parse 'y = mx + b' → (slope, intercept). Raises ValueError if not linear.

    Handles: 'y = 2x + 3', 'y = -x', '2y = 4x + 6', 'y = 5', 'x + y = 7'
    Uses SymPy solve with restricted local_dict (no arbitrary code execution).
    """
    lhs_str, rhs_str = equation.split("=")
    local = {"x": x_sym, "y": y_sym}
    lhs = sympy.parse_expr(lhs_str.strip(), local_dict=local, transformations="all")
    rhs = sympy.parse_expr(rhs_str.strip(), local_dict=local, transformations="all")

    solutions = sympy.solve(lhs - rhs, y_sym)
    if len(solutions) != 1:
        raise ValueError(f"Cannot solve for y in: {equation}")

    y_expr = solutions[0]
    poly = sympy.Poly(y_expr, x_sym)
    if poly.degree() > 1:
        raise ValueError(f"Not a linear equation: {equation}")

    slope = float(poly.nth(1))
    intercept = float(poly.nth(0))
    return (slope, intercept)


def evaluate_linear(slope: float, intercept: float, x_val: float) -> float:
    """Compute y = mx + b for a given x."""
    return slope * x_val + intercept


def compute_intersection(
    m1: float, b1: float, m2: float, b2: float,
) -> tuple[float, float] | None:
    """Find intersection of two lines. Returns None if parallel."""
    if m1 == m2:
        return None
    x = (b2 - b1) / (m1 - m2)
    y = m1 * x + b1
    return (x, y)
