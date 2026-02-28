from tools.draw_diagram import parse_shape_request


def test_parse_right_triangle_with_sides() -> None:
    shape, params = parse_shape_request("right triangle with sides 3, 4, 5")
    assert shape == "right triangle"
    assert params["sides"] == [3.0, 4.0, 5.0]


def test_parse_circle_with_radius() -> None:
    shape, params = parse_shape_request("circle with radius 7")
    assert shape == "circle"
    assert params["radius"] == 7.0


def test_parse_rectangle_dimensions() -> None:
    shape, params = parse_shape_request("rectangle 4 by 3")
    assert shape == "rectangle"
    assert params["width_val"] == 4.0
    assert params["height_val"] == 3.0


def test_parse_equilateral_triangle() -> None:
    shape, params = parse_shape_request("equilateral triangle side 5")
    assert shape == "triangle"
    assert params["equilateral"] is True
    assert params["sides"] == [5.0]


def test_parse_number_line_range() -> None:
    shape, params = parse_shape_request("number line from -3 to 5")
    assert shape == "number line"
    assert params["values"] == [-3.0, 5.0]
