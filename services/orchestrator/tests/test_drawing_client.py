from __future__ import annotations

import httpx
import pytest

from drawing_client import DrawingClient


@pytest.mark.asyncio
async def test_execute_posts_command_payload() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        return httpx.Response(
            status_code=202,
            json={
                "session_id": "s1",
                "command_id": "cmd_1",
                "operation": "draw_text",
                "applied_count": 1,
                "created_element_ids": ["el_1"],
                "failed_operations": [],
                "emitted_count": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    client = DrawingClient("http://drawing:8002")
    client._client = httpx.AsyncClient(base_url="http://drawing:8002", transport=transport, timeout=3.0)

    result = await client.execute(
        session_id="s1",
        operation="draw_text",
        payload={"text": "hello", "x": 0.1, "y": 0.1, "font_size": 18, "style": {}},
        command_id="cmd_1",
    )

    assert captured["path"] == "/draw"
    assert "\"operation\":\"draw_text\"" in captured["body"]
    assert result.created_element_ids == ["el_1"]

    await client.close()


@pytest.mark.asyncio
async def test_execute_falls_back_to_requested_operation_if_missing_in_response() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=202,
            json={
                "session_id": "s1",
                "command_id": "cmd_2",
                "applied_count": 1,
                "created_element_ids": ["el_2"],
                "failed_operations": [],
                "emitted_count": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    client = DrawingClient("http://drawing:8002")
    client._client = httpx.AsyncClient(base_url="http://drawing:8002", transport=transport, timeout=3.0)

    result = await client.execute(
        session_id="s1",
        operation="draw_shape",
        payload={"shape": "line", "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}], "style": {}},
        command_id="cmd_2",
    )

    assert result.operation == "draw_shape"
    await client.close()
