from __future__ import annotations

import pytest

from dsl import FREEHAND_CHUNK_SIZE, translate
from models import DrawRequest


def test_translate_freehand_chunks_and_preserves_order() -> None:
    points = [{"x": i / 20, "y": i / 20} for i in range(20)]
    req = DrawRequest(
        session_id="s1",
        message_type="freehand",
        payload={
            "points": points,
            "color": "#111111",
            "stroke_width": 2.0,
            "delay_ms": 40,
        },
    )

    msgs = translate(req)

    assert len(msgs) == 3
    flattened = [p for m in msgs for p in m.payload.points]  # type: ignore[attr-defined]
    assert [p.x for p in flattened] == [i / 20 for i in range(20)]
    assert all(m.payload.delay_ms == 40 for m in msgs)  # type: ignore[attr-defined]
    assert all(len(m.id) == 8 for m in msgs)


def test_translate_template_shape_to_freehand_messages() -> None:
    req = DrawRequest(
        session_id="s2",
        message_type="shape",
        payload={
            "shape": "triangle",
            "x": 0.1,
            "y": 0.2,
            "width": 0.5,
            "height": 0.6,
            "color": "#ff0000",
            "template_variant": "right_triangle",
        },
    )

    msgs = translate(req)

    assert len(msgs) == 1
    assert msgs[0].type == "freehand"
    payload = msgs[0].payload
    assert payload.points[0].x == pytest.approx(0.15)
    assert payload.points[0].y == pytest.approx(0.74)


def test_translate_plain_shape_single_message() -> None:
    req = DrawRequest(
        session_id="s3",
        message_type="shape",
        payload={
            "shape": "rectangle",
            "x": 0.2,
            "y": 0.3,
            "width": 0.3,
            "height": 0.2,
            "color": "#00ff00",
        },
    )

    msgs = translate(req)

    assert len(msgs) == 1
    assert msgs[0].type == "shape"


def test_translate_text_highlight_and_clear() -> None:
    text_msgs = translate(
        DrawRequest(
            session_id="s4",
            message_type="text",
            payload={
                "text": "hello",
                "x": 0.4,
                "y": 0.5,
                "font_size": 20,
                "color": "#000",
            },
        )
    )
    highlight_msgs = translate(
        DrawRequest(
            session_id="s4",
            message_type="highlight",
            payload={
                "x": 0.2,
                "y": 0.3,
                "width": 0.3,
                "height": 0.3,
                "color": "rgba(255,255,0,0.4)",
            },
        )
    )
    clear_msgs = translate(
        DrawRequest(
            session_id="s4",
            message_type="clear",
            payload={"mode": "full"},
        )
    )

    assert len(text_msgs) == 1 and text_msgs[0].type == "text"
    assert len(highlight_msgs) == 1 and highlight_msgs[0].type == "highlight"
    assert len(clear_msgs) == 1 and clear_msgs[0].type == "clear"


def test_invalid_coordinates_raise_validation_error() -> None:
    with pytest.raises(Exception):
        DrawRequest(
            session_id="s5",
            message_type="freehand",
            payload={
                "points": [{"x": 1.1, "y": 0.1}],
                "color": "#111111",
                "stroke_width": 2.0,
                "delay_ms": 40,
            },
        )


def test_chunk_size_default_is_in_expected_range() -> None:
    assert 5 <= FREEHAND_CHUNK_SIZE <= 10
