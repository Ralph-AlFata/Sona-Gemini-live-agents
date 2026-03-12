from __future__ import annotations

import firestore as fs


def test_extract_dsl_messages_from_metadata_collects_all_known_containers() -> None:
    metadata: dict[str, object] = {
        "dsl_messages": [
            {
                "id": "msg00001",
                "type": "element_created",
                "payload": {
                    "element_id": "el_1",
                    "element_type": "shape",
                    "payload": {"points": [{"x": 0.1, "y": 0.2}, {"x": 0.3, "y": 0.4}]},
                },
            }
        ],
        "draw_command_results": [
            {
                "dsl_messages": [
                    {
                        "id": "msg00002",
                        "type": "elements_deleted",
                        "payload": {"element_ids": ["el_1"]},
                    }
                ]
            },
            {"dsl_messages": "invalid"},
            "invalid",
        ],
    }

    extracted = fs._extract_dsl_messages_from_metadata(metadata)

    assert [msg["id"] for msg in extracted] == ["msg00001", "msg00002"]


def test_apply_dsl_messages_tracks_create_transform_restyle_delete() -> None:
    elements_by_id: dict[str, dict[str, object]] = {}

    created = fs._apply_dsl_messages_to_elements(
        elements_by_id=elements_by_id,
        dsl_messages=[
            {
                "id": "msg00001",
                "type": "element_created",
                "timestamp": "2026-03-12T17:01:00+00:00",
                "payload": {
                    "element_id": "el_1",
                    "element_type": "shape",
                    "payload": {
                        "points": [{"x": 0.1, "y": 0.2}, {"x": 0.4, "y": 0.8}],
                        "color": "#111111",
                        "stroke_width": 2.0,
                    },
                },
            }
        ],
    )
    assert created is True
    assert set(elements_by_id) == {"el_1"}
    assert elements_by_id["el_1"]["bbox"] == {
        "x": 0.1,
        "y": 0.2,
        "width": 0.30000000000000004,
        "height": 0.6000000000000001,
    }

    transformed = fs._apply_dsl_messages_to_elements(
        elements_by_id=elements_by_id,
        dsl_messages=[
            {
                "id": "msg00002",
                "type": "elements_transformed",
                "payload": {
                    "elements": [
                        {
                            "element_id": "el_1",
                            "element_type": "shape",
                            "payload": {
                                "points": [{"x": 0.2, "y": 0.3}, {"x": 0.5, "y": 0.9}],
                                "style": {"stroke_color": "#222222"},
                            },
                        }
                    ]
                },
            }
        ],
    )
    assert transformed is True
    assert elements_by_id["el_1"]["bbox"] == {
        "x": 0.2,
        "y": 0.3,
        "width": 0.3,
        "height": 0.6000000000000001,
    }

    restyled = fs._apply_dsl_messages_to_elements(
        elements_by_id=elements_by_id,
        dsl_messages=[
            {
                "id": "msg00003",
                "type": "elements_restyled",
                "payload": {
                    "elements": [
                        {
                            "element_id": "el_1",
                            "style": {
                                "color": "#00ff00",
                                "stroke_width": 5,
                            },
                        }
                    ]
                },
            }
        ],
    )
    assert restyled is True
    payload = elements_by_id["el_1"]["payload"]
    assert isinstance(payload, dict)
    assert payload["color"] == "#00ff00"
    style_payload = payload["style"]
    assert isinstance(style_payload, dict)
    assert style_payload["stroke_color"] == "#00ff00"
    assert style_payload["stroke_width"] == 5

    deleted = fs._apply_dsl_messages_to_elements(
        elements_by_id=elements_by_id,
        dsl_messages=[
            {
                "id": "msg00004",
                "type": "elements_deleted",
                "payload": {"element_ids": ["el_1"]},
            }
        ],
    )
    assert deleted is True
    assert elements_by_id == {}


def test_apply_dsl_messages_clear_removes_all_elements() -> None:
    elements_by_id: dict[str, dict[str, object]] = {
        "el_1": {
            "element_id": "el_1",
            "element_type": "shape",
            "payload": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        },
        "el_2": {
            "element_id": "el_2",
            "element_type": "text",
            "payload": {"x": 0.4, "y": 0.5, "text": "abc"},
        },
    }

    changed = fs._apply_dsl_messages_to_elements(
        elements_by_id=elements_by_id,
        dsl_messages=[
            {
                "id": "msg00005",
                "type": "clear",
                "payload": {"mode": "full"},
            }
        ],
    )

    assert changed is True
    assert elements_by_id == {}
