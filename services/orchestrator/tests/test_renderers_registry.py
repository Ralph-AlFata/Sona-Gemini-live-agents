from renderers import SHAPE_REGISTRY


def test_registry_contains_core_shapes() -> None:
    for shape in [
        "triangle",
        "right triangle",
        "circle",
        "rectangle",
        "rhombus",
        "parallelogram",
        "trapezoid",
        "number line",
    ]:
        assert shape in SHAPE_REGISTRY


def test_registry_polygon_factories_are_callable() -> None:
    assert callable(SHAPE_REGISTRY["pentagon"])
    assert callable(SHAPE_REGISTRY["hexagon"])
    assert callable(SHAPE_REGISTRY["octagon"])
