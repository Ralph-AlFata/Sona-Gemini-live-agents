from __future__ import annotations

import base64
import json

import httpx
import pytest

from agent import canvas_context
from agent.canvas_context import build_canvas_turn_content, fetch_canvas_state_json


@pytest.mark.asyncio
async def test_fetch_canvas_state_json_mixed_elements() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sessions/s1/canvas_state"
        assert request.headers["Authorization"] == "Bearer token-123"
        return httpx.Response(
            200,
            json={
                "session_id": "s1",
                "element_count": 3,
                "elements": [
                    {
                        "id": "shape_1",
                        "type": "right_triangle",
                        "source": "user",
                        "labels": ["a", "b", "c"],
                        "side_labels": [
                            {"side_index": 0, "text": "a", "element_id": "label_1"},
                            {"side_index": 1, "text": "c", "element_id": "label_2"},
                            {"side_index": 2, "text": "b", "element_id": "label_3"},
                        ],
                        "points": [
                            {"x": 0.1, "y": 0.6},
                            {"x": 0.4, "y": 0.6},
                            {"x": 0.1, "y": 0.2},
                            {"x": 0.1, "y": 0.6},
                        ],
                        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                    },
                    {
                        "id": "text_1",
                        "type": "text",
                        "source": "ai",
                        "text": "Pythagorean theorem",
                        "bbox": {"x": 0.55, "y": 0.1, "width": 0.2, "height": 0.05},
                    },
                    {
                        "id": "free_1",
                        "type": "freehand",
                        "source": "user",
                        "points": [{"x": 0.2, "y": 0.7}, {"x": 0.4, "y": 0.8}],
                        "bbox": {"x": 0.2, "y": 0.7, "width": 0.2, "height": 0.1},
                    },
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "AsyncClient", fake_client)
        canvas_state = await fetch_canvas_state_json("s1", "http://drawing:8002", "token-123")

    assert canvas_state["session_id"] == "s1"
    assert canvas_state["element_count"] == 3
    assert isinstance(canvas_state["elements"], list)


@pytest.mark.asyncio
async def test_fetch_canvas_state_json_empty_returns_empty_payload() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"session_id": "s1", "element_count": 0, "elements": []})

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "AsyncClient", fake_client)
        canvas_state = await fetch_canvas_state_json("s1", "http://drawing:8002")

    assert canvas_state == {"session_id": "s1", "element_count": 0, "elements": []}


@pytest.mark.asyncio
async def test_build_canvas_turn_content_combines_snapshot_and_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_canvas_state_json(
        session_id: str,
        drawing_service_url: str,
        auth_token: str | None = None,
    ) -> dict:
        assert session_id == "session-1"
        assert drawing_service_url == "http://drawing:8002"
        assert auth_token == "token-abc"
        return {
            "session_id": "session-1",
            "element_count": 1,
            "elements": [
                {
                    "id": "shape_1",
                    "type": "right_triangle",
                    "points": [
                        {"x": 0.1, "y": 0.6},
                        {"x": 0.4, "y": 0.6},
                        {"x": 0.1, "y": 0.2},
                        {"x": 0.1, "y": 0.6},
                    ],
                }
            ],
        }

    monkeypatch.setattr(canvas_context, "fetch_canvas_state_json", fake_fetch_canvas_state_json)
    content = await build_canvas_turn_content(
        "session-1",
        "http://drawing:8002",
        base64.b64decode(base64.b64encode(b"jpeg-bytes")),
        "token-abc",
    )

    assert content is not None
    assert len(content.parts) == 2
    assert content.parts[0].inline_data is not None
    assert content.parts[0].inline_data.mime_type == "image/jpeg"
    assert content.parts[0].inline_data.data == b"jpeg-bytes"
    assert content.parts[1].text is not None
    assert content.parts[1].text.startswith("CURRENT_CANVAS_STATE_JSON:\n")
    payload = json.loads(content.parts[1].text.split("\n", 1)[1])
    assert payload["element_count"] == 1
    assert payload["elements"][0]["hypotenuse_side"] == 1
