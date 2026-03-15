from __future__ import annotations

import pytest

from dsl import apply_command
from models import DrawCommandRequest
from store import InMemoryElementStore


@pytest.mark.asyncio
async def test_set_shape_labels_places_last_label_on_hypotenuse_for_right_triangle() -> None:
    store = InMemoryElementStore()
    points = [
        {"x": 0.1, "y": 0.5},
        {"x": 0.4, "y": 0.5},
        {"x": 0.1, "y": 0.2},
        {"x": 0.1, "y": 0.5},
    ]
    create = DrawCommandRequest(
        command_id="cmd_rt_create",
        session_id="s1",
        operation="draw_shape",
        payload={"shape": "right_triangle", "points": points, "style": {}},
    )
    _, create_response = await apply_command(create, store)
    shape_id = create_response.created_element_ids[0]

    label = DrawCommandRequest(
        command_id="cmd_rt_labels",
        session_id="s1",
        operation="set_shape_labels",
        payload={"element_id": shape_id, "labels": ["3", "4", "5"], "font_size": 22},
    )
    _, response = await apply_command(label, store)

    assert response.applied_count == 3
    elements = await store.get_all_elements("s1")
    side_labels = sorted(
        elements[shape_id].payload["side_labels"],
        key=lambda entry: entry["side_index"],
    )

    assert [entry["text"] for entry in side_labels] == ["3", "5", "4"]

