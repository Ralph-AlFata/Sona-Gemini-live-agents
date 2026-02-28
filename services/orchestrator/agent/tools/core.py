"""Core drawing primitives."""

from __future__ import annotations

from google.adk.tools import ToolContext

from agent.tools._shared import get_client, resolve_session_id, result_to_dict
from agent.tools.models import DrawFreehandInput, DrawShapeInput, DrawTextInput, HighlightInput


async def draw_shape(
    shape: str,
    x: float,
    y: float,
    width: float,
    height: float,
    stroke_color: str = "#111111",
    stroke_width: float = 2.0,
    fill_color: str | None = None,
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    template_variant: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    data = DrawShapeInput.model_validate(
        {
            "shape": shape,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "template_variant": template_variant,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "fill_color": fill_color,
                "opacity": opacity,
                "z_index": z_index,
                "delay_ms": delay_ms,
            },
        }
    )
    result = await get_client().execute(
        session_id=resolve_session_id(tool_context),
        operation="draw_shape",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def draw_text(
    text: str,
    x: float,
    y: float,
    font_size: int = 24,
    stroke_color: str = "#111111",
    stroke_width: float = 2.0,
    fill_color: str | None = None,
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    tool_context: ToolContext | None = None,
) -> dict:
    data = DrawTextInput.model_validate(
        {
            "text": text,
            "x": x,
            "y": y,
            "font_size": font_size,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "fill_color": fill_color,
                "opacity": opacity,
                "z_index": z_index,
                "delay_ms": delay_ms,
            },
        }
    )
    result = await get_client().execute(
        session_id=resolve_session_id(tool_context),
        operation="draw_text",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def draw_freehand(
    points: list[dict[str, float]],
    stroke_color: str = "#111111",
    stroke_width: float = 2.0,
    fill_color: str | None = None,
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    tool_context: ToolContext | None = None,
) -> dict:
    data = DrawFreehandInput.model_validate(
        {
            "points": points,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "fill_color": fill_color,
                "opacity": opacity,
                "z_index": z_index,
                "delay_ms": delay_ms,
            },
        }
    )
    result = await get_client().execute(
        session_id=resolve_session_id(tool_context),
        operation="draw_freehand",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def highlight_region(
    x: float,
    y: float,
    width: float,
    height: float,
    stroke_color: str = "rgba(255,255,0,0.4)",
    stroke_width: float = 1.0,
    fill_color: str | None = "rgba(255,255,0,0.25)",
    opacity: float = 1.0,
    z_index: int = 0,
    delay_ms: int = 30,
    tool_context: ToolContext | None = None,
) -> dict:
    data = HighlightInput.model_validate(
        {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "style": {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "fill_color": fill_color,
                "opacity": opacity,
                "z_index": z_index,
                "delay_ms": delay_ms,
            },
        }
    )
    result = await get_client().execute(
        session_id=resolve_session_id(tool_context),
        operation="highlight_region",
        payload=data.model_dump(mode="json"),
    )
    return result_to_dict(result)


async def clear_canvas(tool_context: ToolContext | None = None) -> dict:
    result = await get_client().execute(
        session_id=resolve_session_id(tool_context),
        operation="clear_canvas",
        payload={"mode": "full"},
    )
    return result_to_dict(result)
