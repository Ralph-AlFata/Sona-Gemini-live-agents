"""Editing tools for existing canvas elements."""

from __future__ import annotations

from google.adk.tools import ToolContext

from agent.tools._shared import execute_tool_command, resolve_session_id, result_to_dict
from agent.tools.models import (
    DeleteElementsInput,
    EraseRegionInput,
    MoveElementsInput,
    ResizeElementsInput,
    SetShapeLabelsInput,
    UpdatePointsInput,
    UpdateStyleInput,
)


async def delete_elements(element_ids: list[str], tool_context: ToolContext | None = None) -> dict:
    """Delete elements from the canvas by ID.

    Invocation condition: Call ONLY with element IDs confirmed to exist from
    previous tool call responses. Do not call repeatedly with the same IDs.
    """
    data = DeleteElementsInput.model_validate({"element_ids": element_ids})
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="delete_elements",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def erase_region(
    x: float,
    y: float,
    width: float,
    height: float,
    tool_context: ToolContext | None = None,
) -> dict:
    data = EraseRegionInput.model_validate(
        {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }
    )
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="erase_region",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def move_elements(
    element_ids: list[str],
    dx: float,
    dy: float,
    tool_context: ToolContext | None = None,
) -> dict:
    """Move elements by a delta offset.

    Invocation condition: Call ONLY when repositioning is needed. Do not call
    repeatedly with the same element_ids and dx/dy.
    """
    data = MoveElementsInput.model_validate({"element_ids": element_ids, "dx": dx, "dy": dy})
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="move_elements",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def resize_elements(
    element_ids: list[str],
    scale_x: float,
    scale_y: float,
    tool_context: ToolContext | None = None,
) -> dict:
    data = ResizeElementsInput.model_validate(
        {"element_ids": element_ids, "scale_x": scale_x, "scale_y": scale_y}
    )
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="resize_elements",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def update_element_points(
    element_id: str,
    points: list[dict[str, float]],
    mode: str = "replace",
    tool_context: ToolContext | None = None,
) -> dict:
    data = UpdatePointsInput.model_validate(
        {
            "element_id": element_id,
            "points": points,
            "mode": mode,
        }
    )
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="update_points",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def update_element_style(
    element_ids: list[str],
    stroke_color: str | None = None,
    stroke_width: float | None = None,
    fill_color: str | None = None,
    opacity: float | None = None,
    z_index: int | None = None,
    delay_ms: int | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    data = UpdateStyleInput.model_validate(
        {
            "element_ids": element_ids,
            "stroke_color": stroke_color,
            "stroke_width": stroke_width,
            "fill_color": fill_color,
            "opacity": opacity,
            "z_index": z_index,
            "delay_ms": delay_ms,
        }
    )
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="update_style",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def set_shape_labels(
    element_id: str,
    labels: list[str],
    font_size: int = 22,
    tool_context: ToolContext | None = None,
) -> dict:
    """Attach or replace side labels on an existing shape element."""
    data = SetShapeLabelsInput.model_validate(
        {
            "element_id": element_id,
            "labels": labels,
            "font_size": font_size,
        }
    )
    result = await execute_tool_command(
        session_id=resolve_session_id(tool_context),
        operation="set_shape_labels",
        payload=data.model_dump(mode="json"),
    )
    response = result_to_dict(result)
    response["shape_id"] = element_id
    response["label_ids"] = result.created_element_ids
    return response
