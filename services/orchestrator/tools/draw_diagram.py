"""Tool: draw labeled geometric diagrams."""
from __future__ import annotations

import re

from google.adk.tools import ToolContext

from canvas.store import get_canvas_state
from drawing_client import get_drawing_client
from renderers import SHAPE_REGISTRY
from tools._logging import logged_tool


def parse_shape_request(description: str) -> tuple[str, dict]:
    """Parse natural-language shape request into shape type and params."""
    desc = description.lower().strip()

    matched_type = ""
    for shape_name in sorted(SHAPE_REGISTRY.keys(), key=len, reverse=True):
        if desc.startswith(shape_name):
            matched_type = shape_name
            break

    if not matched_type:
        for shape_name in SHAPE_REGISTRY:
            if shape_name in desc:
                matched_type = shape_name
                break

    if not matched_type:
        matched_type = desc.split(" ")[0]

    params: dict = {}
    numbers = [float(n) for n in re.findall(r"-?\d+\.?\d*", desc)]

    if "side" in desc and numbers:
        params["sides"] = numbers
    elif "radius" in desc and numbers:
        params["radius"] = numbers[0]
    elif "diagonal" in desc and numbers:
        params["diagonals"] = numbers
    elif " by " in desc and len(numbers) >= 2:
        params["width_val"] = numbers[0]
        params["height_val"] = numbers[1]
    elif numbers:
        params["values"] = numbers

    if "equilateral" in desc:
        params["equilateral"] = True

    return matched_type, params


@logged_tool
async def draw_diagram(
    shape: str,
    tool_context: ToolContext,
    labels: list[str] | None = None,
    title: str = "",
) -> dict[str, str]:
    """Draw a shape/diagram with optional labels and title."""
    session_id = str(tool_context.state["session_id"])
    canvas = get_canvas_state(session_id)
    shape_type, params = parse_shape_request(shape)
    labels = labels or []

    renderer = SHAPE_REGISTRY.get(shape_type)
    if renderer is None:
        return {"status": "error", "message": f"Unknown shape: {shape_type}"}

    size = 0.28 if shape_type != "number line" else 0.36
    height = 0.28 if shape_type != "number line" else 0.18
    bbox = canvas.allocate(width=size, height=height)

    if title:
        await get_drawing_client().send_text(
            session_id=session_id,
            text=title,
            x=bbox.x,
            y=max(0.0, bbox.y - 0.04),
            font_size=16,
            color="#555",
        )

    description = await renderer(
        client=get_drawing_client(),
        session_id=session_id,
        bbox=bbox,
        params=params,
        labels=labels,
    )
    return {"status": "success", "drawn": description}
