"""Server-side cursor for automatic element placement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# Layout constants
LEFT_MARGIN = 0.06
TOP_MARGIN = 0.03
RIGHT_EDGE = 0.94
BOTTOM_EDGE = 0.96
GAP_HORIZONTAL = 0.03
GAP_VERTICAL = 0.02
GAP_NEWLINE = 0.04
GAP_SECTION = 0.06
GAP_COLUMN = 0.04


@dataclass
class BBox:
    """Bounding box of a placed element."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height
    
    # TODO: Might need to add Top and Left


@dataclass
class CursorState:
    """Tracks the current writing position on the canvas."""

    x: float = LEFT_MARGIN
    y: float = TOP_MARGIN
    row_start_y: float = TOP_MARGIN
    row_max_bottom: float = TOP_MARGIN
    row_start_x: float = LEFT_MARGIN
    column_max_right: float = LEFT_MARGIN
    bottom_edge: float = BOTTOM_EDGE

    def place(self, width: float, height: float, next_direction: str = "below") -> BBox:
        """Place an element at the cursor position and advance the cursor."""
        width = max(0.0, width)
        height = max(0.0, height)
        self._ensure_vertical_room(height=height, required_width=width)

        if self.x + width > RIGHT_EDGE and self.x > LEFT_MARGIN + 0.01:
            self._reset_to_below_row()
            self._ensure_vertical_room(height=height, required_width=width)

        bbox = BBox(x=self.x, y=self.y, width=width, height=height)
        self.row_max_bottom = max(self.row_max_bottom, bbox.bottom)
        self.column_max_right = max(self.column_max_right, bbox.right)
        # TODO: Double check if I want to add above
        if next_direction == "right":
            next_x = bbox.right + GAP_HORIZONTAL
            if next_x > RIGHT_EDGE:
                self._reset_to_below_row()
            else:
                self.x = next_x
                self.y = bbox.y
        elif next_direction == "left":
            self.x = max(LEFT_MARGIN, bbox.x - width - GAP_HORIZONTAL)
            self.y = bbox.y
        elif next_direction == "below_all":
            self._reset_to_below_row()
        else:
            self.y = bbox.bottom + GAP_VERTICAL
            if self.y > self.bottom_edge:
                self._wrap_to_next_column(required_width=width)

        return bbox

    # TODO: Double check what that already existing function does.
    # TODO: When we are working with a "relative" cursor, the already existing absolute cursor should remain where it is.
    # Also, if an element is added on a non-standard place, the cursor should take into consideration the already existing bounding boxes, and skip them by either going to the bottom, left, right, or above, or it might even choose to move it.
    def advance_from_bbox(self, bbox: BBox, next_direction: str = "below") -> None:
        """
        Advance cursor using an already-placed element bbox.

        This is used for manual/freehand drawing where placement did not start
        from the current cursor position.
        """
        self.row_max_bottom = max(self.row_max_bottom, bbox.bottom)
        self.y = max(self.y, bbox.y)
        self.column_max_right = max(self.column_max_right, bbox.right)

        if next_direction == "right":
            next_x = bbox.right + GAP_HORIZONTAL
            if next_x > RIGHT_EDGE:
                self._reset_to_below_row()
            else:
                self.x = next_x
                self.y = bbox.y
            self.row_start_y = min(self.row_start_y, bbox.y)
            return

        if next_direction == "left":
            self.x = max(LEFT_MARGIN, bbox.x - bbox.width - GAP_HORIZONTAL)
            self.y = bbox.y
            self.row_start_y = min(self.row_start_y, bbox.y)
            return

        if next_direction == "below_all":
            self._reset_to_below_row()
            return

        self.x = max(self.x, bbox.x)
        self.y = bbox.bottom + GAP_VERTICAL
        if self.y > self.bottom_edge:
            self._wrap_to_next_column(required_width=bbox.width)

    def new_line(self) -> None:
        """Explicit line break below the current row."""
        self.y = self.row_max_bottom + GAP_NEWLINE
        self.x = self.row_start_x
        self.row_start_y = self.y
        self.row_max_bottom = self.y
        if self.y > self.bottom_edge:
            self._wrap_to_next_column()

    def new_section(self) -> None:
        """Start a new section with a larger vertical gap."""
        self.y = self.row_max_bottom + GAP_SECTION
        self.x = LEFT_MARGIN
        self.row_start_x = LEFT_MARGIN
        self.row_start_y = self.y
        self.row_max_bottom = self.y
        if self.y > self.bottom_edge:
            self._wrap_to_next_column()

    def move_to(self, x: float, y: float) -> None:
        """Jump cursor to an explicit position."""
        clamped_x = _clamp(x, LEFT_MARGIN, RIGHT_EDGE)
        clamped_y = _clamp(y, TOP_MARGIN, self.bottom_edge)
        self.x = clamped_x
        self.y = clamped_y
        self.row_start_y = clamped_y
        self.row_start_x = clamped_x
        self.row_max_bottom = clamped_y
        self.column_max_right = max(self.column_max_right, clamped_x)

    def clear(self) -> None:
        """Reset cursor to the top-left origin."""
        self.x = LEFT_MARGIN
        self.y = TOP_MARGIN
        self.row_start_y = TOP_MARGIN
        self.row_max_bottom = TOP_MARGIN
        self.row_start_x = LEFT_MARGIN
        self.column_max_right = LEFT_MARGIN

    def _reset_to_below_row(self) -> None:
        self.y = self.row_max_bottom + GAP_VERTICAL
        self.x = self.row_start_x
        self.row_start_y = self.y
        self.row_max_bottom = self.y
        if self.y > self.bottom_edge:
            self._wrap_to_next_column()

    def _ensure_vertical_room(self, *, height: float, required_width: float) -> None:
        if self.y + height <= self.bottom_edge:
            return
        self._wrap_to_next_column(required_width=required_width)

    def _wrap_to_next_column(self, required_width: float = 0.0) -> None:
        min_required = max(required_width, 0.12)
        next_x = self.column_max_right + GAP_COLUMN
        if next_x + min_required <= RIGHT_EDGE:
            self.x = next_x
            self.y = TOP_MARGIN
            self.row_start_x = next_x
            self.row_start_y = TOP_MARGIN
            self.row_max_bottom = TOP_MARGIN
            self.column_max_right = max(self.column_max_right, next_x)
            return
        self.clear()

    def to_dict(self) -> dict[str, float]:
        return {"x": round(self.x, 4), "y": round(self.y, 4)}

    def to_snapshot_dict(self) -> dict[str, float]:
        return {
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "row_start_y": round(self.row_start_y, 4),
            "row_max_bottom": round(self.row_max_bottom, 4),
            "row_start_x": round(self.row_start_x, 4),
            "column_max_right": round(self.column_max_right, 4),
            "bottom_edge": round(self.bottom_edge, 4),
        }

    # TODO: Checkout what this is
    @classmethod
    def from_snapshot_dict(cls, raw: Mapping[str, object]) -> "CursorState":
        state = cls()
        state.bottom_edge = _clamp(
            _coerce_float(raw.get("bottom_edge"), BOTTOM_EDGE),
            TOP_MARGIN + 0.05,
            2.0,
        )
        state.x = _clamp(_coerce_float(raw.get("x"), LEFT_MARGIN), LEFT_MARGIN, RIGHT_EDGE)
        state.y = _clamp(_coerce_float(raw.get("y"), TOP_MARGIN), TOP_MARGIN, state.bottom_edge)
        state.row_start_y = _clamp(
            _coerce_float(raw.get("row_start_y"), state.y),
            TOP_MARGIN,
            state.bottom_edge,
        )
        state.row_max_bottom = _clamp(
            max(_coerce_float(raw.get("row_max_bottom"), state.y), state.row_start_y),
            TOP_MARGIN,
            state.bottom_edge,
        )
        state.row_start_x = _clamp(
            _coerce_float(raw.get("row_start_x"), state.x),
            LEFT_MARGIN,
            RIGHT_EDGE,
        )
        state.column_max_right = _clamp(
            max(_coerce_float(raw.get("column_max_right"), state.x), state.row_start_x),
            LEFT_MARGIN,
            RIGHT_EDGE,
        )
        return state

    def set_bottom_edge(self, bottom_edge: float) -> None:
        """Update runtime bottom bound used for auto placement flow."""
        self.bottom_edge = _clamp(bottom_edge, TOP_MARGIN + 0.05, 2.0)
        self.y = _clamp(self.y, TOP_MARGIN, self.bottom_edge)
        self.row_start_y = _clamp(self.row_start_y, TOP_MARGIN, self.bottom_edge)
        self.row_max_bottom = _clamp(
            max(self.row_max_bottom, self.row_start_y),
            TOP_MARGIN,
            self.bottom_edge,
        )


def _coerce_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
