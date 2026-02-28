"""Canvas layout engine — two-panel cursor model.

Content flows left-to-right, top-to-bottom across two panels,
like a teacher writing on a whiteboard. Tools never take x/y
coordinates — the canvas state allocates positions automatically.
"""
from __future__ import annotations

from dataclasses import dataclass

MARGIN = 0.04
GAP = 0.03
LINE_BREAK_GAP = 0.04


@dataclass
class Region:
    x_min: float
    x_max: float
    y_min: float
    y_max: float


PANEL_1 = Region(x_min=0.02, x_max=0.48, y_min=0.03, y_max=0.97)
PANEL_2 = Region(x_min=0.52, x_max=0.98, y_min=0.03, y_max=0.97)


@dataclass
class BBox:
    x: float
    y: float
    width: float
    height: float


class CanvasState:
    """Tracks cursor position only. No element registry — keeps memory footprint
    minimal and avoids sending unnecessary state back to Gemini."""

    def __init__(self) -> None:
        self.panel = PANEL_1
        self.cursor_x = PANEL_1.x_min
        self.cursor_y = PANEL_1.y_min
        self.line_height = 0.0

    def allocate(self, width: float, height: float) -> BBox:
        """Allocate a region for the next element.

        Flows left-to-right within the current panel.
        Wraps to next line when the right edge is reached.
        Jumps to Panel 2 when Panel 1 is full.
        """
        if self.cursor_x + width > self.panel.x_max:
            self._newline()

        if self.cursor_y + height > self.panel.y_max:
            if self.panel is PANEL_1:
                self._jump_to_panel_2()

        bbox = BBox(x=self.cursor_x, y=self.cursor_y, width=width, height=height)

        self.cursor_x += width + GAP
        self.line_height = max(self.line_height, height)

        return bbox

    def newline(self) -> None:
        """Public: force a line break."""
        self._newline()

    def clear(self) -> None:
        """Reset all state."""
        self.panel = PANEL_1
        self.cursor_x = PANEL_1.x_min
        self.cursor_y = PANEL_1.y_min
        self.line_height = 0.0

    def _newline(self) -> None:
        self.cursor_x = self.panel.x_min
        self.cursor_y += self.line_height + LINE_BREAK_GAP
        self.line_height = 0.0

    def _jump_to_panel_2(self) -> None:
        self.panel = PANEL_2
        self.cursor_x = PANEL_2.x_min
        self.cursor_y = PANEL_2.y_min
        self.line_height = 0.0
