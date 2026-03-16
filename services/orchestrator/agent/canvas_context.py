from __future__ import annotations

import logging
import math
import json

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


async def fetch_canvas_state_json(
    session_id: str,
    drawing_service_url: str,
    auth_token: str | None = None,
) -> dict:
    """Fetch the current structured canvas state as JSON for Gemini."""
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
            if isinstance(data, dict):
                return data
            logger.warning(
                "CANVAS_STATE_FETCH_INVALID session_id=%s response_type=%s",
                session_id,
                type(data).__name__,
            )
    except Exception as exc:
        logger.warning(
            "CANVAS_STATE_FETCH_FAILED session_id=%s url=%s timeout_s=%.2f error=%r",
            session_id,
            f"{drawing_service_url.rstrip('/')}/sessions/{session_id}/canvas_state",
            CANVAS_STATE_TIMEOUT_SECONDS,
            exc,
        )
    return {
        "session_id": session_id,
        "element_count": 0,
        "elements": [],
        "error": "canvas_state_unavailable",
    }


def serialize_canvas_state_for_model(canvas_state: dict) -> str:
    """Serialize canvas state into a stable JSON string for the model."""
    normalized = dict(canvas_state)
    elements = normalized.get("elements")
    if isinstance(elements, list):
        for raw in elements:
            if not isinstance(raw, dict):
                continue
            if raw.get("type") == "right_triangle" and isinstance(raw.get("points"), list):
                hypotenuse_index = _hypotenuse_side_index(raw["points"])
                if hypotenuse_index is not None:
                    raw["hypotenuse_side"] = hypotenuse_index
    return "CURRENT_CANVAS_STATE_JSON:\n" + json.dumps(normalized, separators=(",", ":"), sort_keys=True)


async def build_canvas_turn_content(
    session_id: str,
    drawing_service_url: str,
    snapshot_bytes: bytes | None,
    auth_token: str | None = None,
) -> types.Content | None:
    """Build the multimodal canvas context payload for a user turn."""
    canvas_state = await fetch_canvas_state_json(
        session_id,
        drawing_service_url,
        auth_token=auth_token,
    )
    parts: list[types.Part] = []
    if snapshot_bytes:
        parts.append(types.Part.from_bytes(data=snapshot_bytes, mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text=serialize_canvas_state_for_model(canvas_state)))
    return types.Content(role="user", parts=parts)
