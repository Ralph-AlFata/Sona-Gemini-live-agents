"""Tool: plot linear equations on a coordinate plane."""
from __future__ import annotations

from google.adk.tools import ToolContext

from canvas.store import get_canvas_state
from math_verify import compute_intersection, parse_linear_equation
from renderers.graph import render_graph
from drawing_client import get_drawing_client
from tools._logging import logged_tool


@logged_tool
async def plot_graph(
    equations: list[str],
    tool_context: ToolContext,
    x_min: float = -5.0,
    x_max: float = 5.0,
) -> dict[str, str]:
    """Plot one or more linear equations with axes."""
    if x_min >= x_max:
        return {"status": "error", "message": "x_min must be less than x_max"}

    session_id = str(tool_context.state["session_id"])
    canvas = get_canvas_state(session_id)
    bbox = canvas.allocate(width=0.38, height=0.35)

    parsed: list[tuple[str, float, float]] = []
    for eq in equations:
        try:
            slope, intercept = parse_linear_equation(eq)
            parsed.append((eq, slope, intercept))
        except ValueError:
            return {"status": "error", "message": f"Cannot parse equation: {eq}"}

    description = await render_graph(
        client=get_drawing_client(),
        session_id=session_id,
        bbox=bbox,
        equations=equations,
        x_min=x_min,
        x_max=x_max,
    )

    if len(parsed) == 2:
        m1, b1 = parsed[0][1], parsed[0][2]
        m2, b2 = parsed[1][1], parsed[1][2]
        intersection = compute_intersection(m1, b1, m2, b2)
        if intersection:
            ix, iy = intersection
            description += f". Intersection at ({ix:.1f}, {iy:.1f})"

    return {"status": "success", "drawn": description}
