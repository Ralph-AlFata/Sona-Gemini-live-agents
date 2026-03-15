from __future__ import annotations

import logging
import math

import httpx
from google.genai import types

logger = logging.getLogger(__name__)
CANVAS_STATE_TIMEOUT_SECONDS = 2.0


def _hypotenuse_side_index(points: list[dict]) -> int | None:
    if len(points) < 4:
        return None
    vertices = points[:-1] if points and points[0] == points[-1] else points
    if len(vertices) != 3:
        return None
    side_lengths = [
        math.hypot(
            float(vertices[(index + 1) % 3]["x"]) - float(vertices[index]["x"]),
            float(vertices[(index + 1) % 3]["y"]) - float(vertices[index]["y"]),
        )
        for index in range(3)
    ]
    return max(range(3), key=side_lengths.__getitem__)


async def fetch_canvas_description(
    session_id: str,
    drawing_service_url: str,
    auth_token: str | None = None,
) -> str | None:
    """Fetch the current structured canvas state and summarize it for Gemini."""
    try:
        async with httpx.AsyncClient(timeout=CANVAS_STATE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{drawing_service_url.rstrip('/')}/sessions/{session_id}/canvas_state",
                headers=(
                    {"Authorization": f"Bearer {auth_token}"}
                    if isinstance(auth_token, str) and auth_token
                    else None
                ),
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "CANVAS_STATE_FETCH_OK session_id=%s element_count=%s",
                session_id,
                data.get("element_count"),
            )
    except Exception as exc:
        logger.warning(
            "CANVAS_STATE_FETCH_FAILED session_id=%s url=%s timeout_s=%.2f error=%r",
            session_id,
            f"{drawing_service_url.rstrip('/')}/sessions/{session_id}/canvas_state",
            CANVAS_STATE_TIMEOUT_SECONDS,
            exc,
        )
        return None

    elements = data.get("elements", [])
    if not isinstance(elements, list) or not elements:
        return None

    lines: list[str] = []
    for raw in elements:
        if not isinstance(raw, dict):
            continue
        source_tag = "[STUDENT]" if raw.get("source") == "user" else "[TUTOR]"
        element_type = str(raw.get("type", "element"))
        bbox = raw.get("bbox") if isinstance(raw.get("bbox"), dict) else {}

        if element_type == "text":
            text_content = str(raw.get("text", "")).strip()
            if not text_content:
                continue
            lines.append(
                f'{source_tag} text "{text_content}" at '
                f'({float(bbox.get("x", 0.0)):.2f}, {float(bbox.get("y", 0.0)):.2f})'
            )
            continue

        if element_type == "freehand":
            points = raw.get("points")
            if isinstance(points, list) and len(points) >= 2:
                start = points[0] if isinstance(points[0], dict) else {}
                end = points[-1] if isinstance(points[-1], dict) else {}
                lines.append(
                    f'{source_tag} freehand stroke from '
                    f'({float(start.get("x", 0.0)):.2f}, {float(start.get("y", 0.0)):.2f}) '
                    f'to ({float(end.get("x", 0.0)):.2f}, {float(end.get("y", 0.0)):.2f}), '
                    f'{len(points)} points'
                )
            continue

        labels = raw.get("labels")
        label_str = f", labels: {labels}" if isinstance(labels, list) and labels else ""
        element_id = str(raw.get("id", "")).strip()
        id_str = f" id={element_id}" if element_id else ""
        side_labels = raw.get("side_labels")
        side_label_str = ""
        if isinstance(side_labels, list) and side_labels:
            side_bits: list[str] = []
            for entry in side_labels:
                if not isinstance(entry, dict):
                    continue
                side_index = entry.get("side_index")
                text = entry.get("text")
                if isinstance(side_index, int) and isinstance(text, str) and text.strip():
                    side_bits.append(f"side{side_index}='{text.strip()}'")
            if side_bits:
                side_label_str = ", side_labels: [" + ", ".join(side_bits) + "]"
        hypotenuse_str = ""
        points = raw.get("points")
        if element_type == "right_triangle" and isinstance(points, list):
            hypotenuse_index = _hypotenuse_side_index(points)
            if hypotenuse_index is not None:
                hypotenuse_str = f", hypotenuse_side=side{hypotenuse_index}"
        lines.append(
            f"{source_tag} {element_type}{id_str} at "
            f'({float(bbox.get("x", 0.0)):.2f}, {float(bbox.get("y", 0.0)):.2f}), '
            f'size {float(bbox.get("width", 0.0)):.2f}x{float(bbox.get("height", 0.0)):.2f}'
            f"{label_str}"
            f"{side_label_str}"
            f"{hypotenuse_str}"
        )

    if not lines:
        return None
    return "CURRENT CANVAS STATE:\n" + "\n".join(lines)


async def build_canvas_turn_content(
    session_id: str,
    drawing_service_url: str,
    snapshot_bytes: bytes | None,
    auth_token: str | None = None,
) -> types.Content | None:
    """Build the multimodal canvas context payload for a user turn."""
    canvas_description = await fetch_canvas_description(
        session_id,
        drawing_service_url,
        auth_token=auth_token,
    )
    parts: list[types.Part] = []
    if snapshot_bytes:
        parts.append(types.Part.from_bytes(data=snapshot_bytes, mime_type="image/jpeg"))
    if canvas_description:
        parts.append(types.Part.from_text(text=canvas_description))
    if not parts:
        return None
    return types.Content(role="user", parts=parts)
