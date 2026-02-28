# Sona — Tool Implementation Plan (Revised)

## Context

The orchestrator service doesn't exist yet. The drawing service and frontend are fully built — the drawing service accepts POST /draw commands and broadcasts DSL messages via WebSocket, and the frontend renders all 5 DSL types (text, freehand, shape, highlight, clear) with progressive animation.

This plan covers building the orchestrator's tool layer: the functions Gemini calls to draw on the whiteboard during a tutoring session.

---

## Design Principles

### 1. Tools Map to Teaching Intent, Not Primitives

A teacher does 3 things on a whiteboard: **writes**, **draws diagrams**, and **graphs equations**. That's 3 drawing tools + 2 control tools = **5 tools total**.

Adding a new shape (rhombus, trapezoid, hexagon) never requires a new tool — it's a new renderer inside `draw_diagram`.

### 2. Cursor Model — Left-to-Right Flow

No zones, no grids. Content flows like a teacher's hand: left-to-right, top-to-bottom, across two panels. Tools never take x/y coordinates — the canvas state allocates positions automatically.

### 3. Two-Panel Whiteboard

```
┌──────────────────────────┬──────────────────────────┐
│       PANEL 1            │       PANEL 2            │
│   x: 0.02 – 0.48        │   x: 0.52 – 0.98        │
│   y: 0.03 – 0.97        │   y: 0.03 – 0.97        │
│                          │                          │
│   Fills first            │   Overflow goes here     │
│   left → right           │   left → right           │
│   top → bottom           │   top → bottom           │
└──────────────────────────┴──────────────────────────┘
```

### 4. Ultra-Fast Async Tools — Imperceptible Pause

ADK v1.10.0+ executes async tool functions **in parallel automatically**. All drawing tools are `async def` functions that fire HTTP POSTs to the drawing service with a 500ms timeout. The round-trip per tool is ~50–100ms. When Gemini calls multiple tools in one turn, they execute concurrently, so total block time stays ~50–100ms — imperceptible to the student.

> **Why not NON_BLOCKING?** The Gemini Live API's `NON_BLOCKING` function behavior is a raw WebSocket-level feature. ADK abstracts this away — there is no `BidiGenerateContentSetup` to configure manually when using `runner.run_live()`. Since our tools complete in <100ms, the brief audio pause is unnoticeable, making NON_BLOCKING unnecessary.

### 5. Minimal Tool Responses — No Canvas Summary

Tools return only `{"status": "success", "drawn": "..."}`. No canvas summary, no element list. This reduces:
- Token count in Gemini's context window
- Latency per tool round-trip
- Risk of Gemini narrating internal state

The cursor model is server-side only — Gemini never needs to know coordinates.

### 6. Canvas Snapshots — Silent Pre-Loading

When the student draws on the canvas, the frontend exports a **384×384 JPEG at quality 0.5** (~15–30KB, 258 Gemini tokens). The orchestrator sends this to Gemini via `live_request_queue.send_content()` with `turn_complete=False` — the image enters the conversation context **without triggering a response**. By the time the student speaks, Gemini already has the canvas state loaded. No tool needed — Gemini sees the image natively.

This was chosen over alternatives because:
- 384×384 = minimum token cost (258 tokens, same as ~8s of audio)
- `send_content` with `turn_complete=False` = no latency spike for the student
- No `analyze_canvas` tool needed = eliminates one function-call round-trip
- Keeps session in audio-only mode (15min limit vs 2min for video streams)

---

## File Structure

```
services/orchestrator/
├── pyproject.toml
├── Dockerfile
├── main.py                      # FastAPI app, WebSocket bridge (Phase 2 — not this plan)
├── config.py                    # Settings: API keys, service URLs, model name
│
├── canvas/
│   ├── __init__.py
│   ├── state.py                 # CanvasState, Cursor, BBox, two-panel layout
│   └── store.py                 # Per-session state storage with TTL cleanup
│
├── drawing_client.py            # Async HTTP client for POST /draw with circuit breaker
│
├── tools/
│   ├── __init__.py              # Re-exports all 5 tool functions
│   ├── _logging.py              # @logged_tool decorator (replaces ADK callbacks)
│   ├── write_math.py            # Write equations and text
│   ├── draw_diagram.py          # Draw any labeled shape
│   ├── plot_graph.py            # Coordinate plane + plotted equations
│   ├── new_line.py              # Advance cursor to next line
│   └── clear_canvas.py          # Reset board
│
├── renderers/
│   ├── __init__.py              # Registry: shape name → renderer function
│   ├── triangle.py              # Right triangle, equilateral, scalene
│   ├── circle.py                # Circle with radius/diameter/angle annotations
│   ├── rectangle.py             # Rectangle, square
│   ├── polygon.py               # Regular polygons (pentagon, hexagon, etc.)
│   ├── quadrilateral.py         # Rhombus, parallelogram, trapezoid
│   ├── number_line.py           # Labeled number line with marked points
│   └── graph.py                 # Cartesian axes + line plotting via SymPy
│
├── math_verify.py               # SymPy verification layer
│
└── agent/
    ├── __init__.py
    └── agent.py                 # ADK Agent definition + system prompt
```

---

## Implementation Order

### Step 0: Orchestrator Skeleton

**Files:** `pyproject.toml`, `Dockerfile`, `config.py`, `main.py`

**`pyproject.toml` dependencies:**
```
fastapi[standard]
uvicorn[standard]
pydantic>=2
pydantic-settings
google-adk>=1.10
google-genai
python-dotenv
httpx
sympy
websockets
```

> Note: `google-adk>=1.10` is required for automatic parallel tool execution.

**`config.py`:**
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    google_api_key: str = ""
    drawing_service_url: str = "http://localhost:8002"
    session_service_url: str = "http://localhost:8003"
    model_name: str = "gemini-2.5-flash-native-audio-preview-12-2025"

    model_config = SettingsConfigDict(env_file=".env")
```

**`main.py`** (minimal for now — WebSocket bridge is Phase 2):
```python
from fastapi import FastAPI

app = FastAPI(title="Sona Orchestrator")

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "orchestrator"}
```

**Session state contract** — when the WebSocket bridge (Phase 2) creates an ADK session, it **must** inject `session_id` into the session state. Every tool reads it from there:

```python
# Phase 2 — main.py WebSocket handler will do this:
session = await runner.session_service.create_session(
    app_name="sona",
    user_id=user_id,
    state={"session_id": session_id},  # ← tools read this
)
```

**Verify:** `curl localhost:8001/health` → 200

---

### Step 1: Drawing Client

**File:** `drawing_client.py`

Shared async HTTP client that all tools use to POST to the drawing service. Single responsibility: translate tool parameters into drawing service request format.

Includes a **circuit breaker with time-based recovery** — opens after 3 consecutive failures, retries after 30 seconds.

```python
import time
import httpx

class DrawingClient:
    """Async HTTP client for the drawing command service."""

    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=0.5)
        self._consecutive_failures = 0
        self._circuit_open = False
        self._circuit_opened_at: float = 0.0
        self._recovery_after: float = 30.0  # seconds

    async def _post(self, path: str, json: dict) -> None:
        """POST with circuit breaker. Opens after 3 consecutive failures,
        retries after 30 seconds (half-open state)."""
        if self._circuit_open:
            if time.monotonic() - self._circuit_opened_at > self._recovery_after:
                self._circuit_open = False
                self._consecutive_failures = 0
            else:
                return  # Silently skip — drawing is non-critical during voice tutoring
        try:
            await self._client.post(path, json=json)
            self._consecutive_failures = 0
        except (httpx.TimeoutException, httpx.ConnectError):
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._circuit_open = True
                self._circuit_opened_at = time.monotonic()

    async def send_text(
        self, session_id: str, text: str, x: float, y: float,
        font_size: int = 24, color: str = "#222",
    ) -> None:
        await self._post("/draw", json={
            "session_id": session_id,
            "message_type": "text",
            "payload": {"text": text, "x": x, "y": y, "font_size": font_size, "color": color},
        })

    async def send_freehand(
        self, session_id: str, points: list[dict[str, float]],
        color: str = "#111", stroke_width: float = 2.0, delay_ms: int = 35,
    ) -> None:
        await self._post("/draw", json={
            "session_id": session_id,
            "message_type": "freehand",
            "payload": {
                "points": points, "color": color,
                "stroke_width": stroke_width, "delay_ms": delay_ms,
            },
        })

    async def send_shape(
        self, session_id: str, shape: str, x: float, y: float,
        width: float, height: float, color: str = "#111",
        fill_color: str | None = None, template_variant: str | None = None,
    ) -> None:
        payload: dict = {
            "shape": shape, "x": x, "y": y,
            "width": width, "height": height, "color": color,
        }
        if fill_color:
            payload["fill_color"] = fill_color
        if template_variant:
            payload["template_variant"] = template_variant
        await self._post("/draw", json={
            "session_id": session_id,
            "message_type": "shape",
            "payload": payload,
        })

    async def send_highlight(
        self, session_id: str, x: float, y: float,
        width: float, height: float, color: str = "rgba(255,255,0,0.3)",
    ) -> None:
        await self._post("/draw", json={
            "session_id": session_id,
            "message_type": "highlight",
            "payload": {"x": x, "y": y, "width": width, "height": height, "color": color},
        })

    async def send_clear(self, session_id: str) -> None:
        await self._post("/draw/clear", json={"session_id": session_id})
```

**Verify:** Unit test — mock httpx, confirm correct JSON payloads. Test circuit breaker: 3 failures → open, wait 30s → half-open → success → closed.

---

### Step 2: Canvas State + Cursor Model

**Files:** `canvas/state.py`, `canvas/store.py`

This is the layout engine. It tracks what's on the board and where the cursor is.

**`canvas/state.py`:**

```python
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
```

**`canvas/store.py`:**

Per-session canvas state storage with **TTL-based cleanup** to prevent memory leaks.

```python
import time
from canvas.state import CanvasState

_sessions: dict[str, tuple[CanvasState, float]] = {}
_TTL = 3600  # 1 hour


def get_canvas_state(session_id: str) -> CanvasState:
    if session_id in _sessions:
        state, _ = _sessions[session_id]
        _sessions[session_id] = (state, time.monotonic())
        return state
    state = CanvasState()
    _sessions[session_id] = (state, time.monotonic())
    _cleanup_stale()
    return state


def clear_canvas_state(session_id: str) -> None:
    _sessions.pop(session_id, None)


def _cleanup_stale() -> None:
    now = time.monotonic()
    stale = [k for k, (_, ts) in _sessions.items() if now - ts > _TTL]
    for k in stale:
        del _sessions[k]
```

**Verify:** Unit test — allocate several elements, confirm cursor flows left-to-right, wraps to next line, jumps to Panel 2 when Panel 1 fills. Test TTL cleanup with mock time.

---

### Step 3: Math Verification Layer

**File:** `math_verify.py`

All mathematical computations go through SymPy verification before Sona states a result.

```python
import sympy
from functools import lru_cache

x_sym, y_sym = sympy.symbols("x y")


@lru_cache(maxsize=128)
def verify_pythagorean(a: float, b: float, c: float) -> bool:
    """Check if a² + b² = c² (within tolerance for floats)."""
    return sympy.Eq(sympy.nsimplify(a**2 + b**2), sympy.nsimplify(c**2))


@lru_cache(maxsize=128)
def verify_triangle_inequality(a: float, b: float, c: float) -> bool:
    """Check if three sides can form a valid triangle."""
    return a + b > c and a + c > b and b + c > a


@lru_cache(maxsize=64)
def parse_linear_equation(equation: str) -> tuple[float, float]:
    """Parse 'y = mx + b' → (slope, intercept). Raises ValueError if not linear.

    Handles: 'y = 2x + 3', 'y = -x', '2y = 4x + 6', 'y = 5', 'x + y = 7'
    Uses SymPy solve with restricted local_dict (no arbitrary code execution).
    """
    lhs_str, rhs_str = equation.split("=")
    local = {"x": x_sym, "y": y_sym}
    lhs = sympy.parse_expr(lhs_str.strip(), local_dict=local, transformations="all")
    rhs = sympy.parse_expr(rhs_str.strip(), local_dict=local, transformations="all")

    solutions = sympy.solve(lhs - rhs, y_sym)
    if len(solutions) != 1:
        raise ValueError(f"Cannot solve for y in: {equation}")

    y_expr = solutions[0]
    poly = sympy.Poly(y_expr, x_sym)
    if poly.degree() > 1:
        raise ValueError(f"Not a linear equation: {equation}")

    slope = float(poly.nth(1))
    intercept = float(poly.nth(0))
    return (slope, intercept)


def evaluate_linear(slope: float, intercept: float, x_val: float) -> float:
    """Compute y = mx + b for a given x."""
    return slope * x_val + intercept


def compute_intersection(
    m1: float, b1: float, m2: float, b2: float,
) -> tuple[float, float] | None:
    """Find intersection of two lines. Returns None if parallel."""
    if m1 == m2:
        return None
    x = (b2 - b1) / (m1 - m2)
    y = m1 * x + b1
    return (x, y)
```

**Verify:** Unit tests:
- `parse_linear_equation("y = 2x + 3")` → (2.0, 3.0)
- `parse_linear_equation("y = -x")` → (-1.0, 0.0)
- `parse_linear_equation("2y = 4x + 6")` → (2.0, 3.0)
- `parse_linear_equation("y = 5")` → (0.0, 5.0)
- `parse_linear_equation("x + y = 7")` → (-1.0, 7.0)
- `parse_linear_equation("y = x^2")` → raises ValueError

---

### Step 4: Shape Renderers

**Files:** `renderers/*.py`

Each renderer takes a `BBox` (allocated region) and `session_id`, and sends draw commands to the drawing service. Renderers compute point coordinates, label positions, and annotation geometry.

**Key principle:** All renderers produce coordinates within the allocated `BBox`. They don't know or care about the rest of the canvas. All renderers use `asyncio.gather()` for parallel HTTP calls.

#### `renderers/__init__.py` — Registry

```python
from typing import Callable
from renderers.triangle import render_triangle, render_right_triangle
from renderers.circle import render_circle
from renderers.rectangle import render_rectangle
from renderers.polygon import render_regular_polygon
from renderers.quadrilateral import render_rhombus, render_parallelogram, render_trapezoid
from renderers.number_line import render_number_line
from renderers.graph import render_graph

SHAPE_REGISTRY: dict[str, Callable] = {
    "triangle": render_triangle,
    "right triangle": render_right_triangle,
    "circle": render_circle,
    "rectangle": render_rectangle,
    "square": render_rectangle,
    "rhombus": render_rhombus,
    "parallelogram": render_parallelogram,
    "trapezoid": render_trapezoid,
    "pentagon": render_regular_polygon(5),
    "hexagon": render_regular_polygon(6),
    "octagon": render_regular_polygon(8),
    "number line": render_number_line,
}
```

Adding a rhombus = adding `render_rhombus` function in `quadrilateral.py` + one line in the registry. No tool changes.

#### `renderers/triangle.py` — Example Renderer

```python
import asyncio
from typing import Awaitable
from canvas.state import BBox
from drawing_client import DrawingClient


async def render_right_triangle(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    """Draw a right triangle with labels within the given bbox."""
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height

    draw_calls: list[Awaitable] = []

    # 1. Triangle shape
    draw_calls.append(client.send_shape(
        session_id=session_id,
        shape="polygon",
        x=bbox.x, y=bbox.y,
        width=bbox.width, height=bbox.height,
        color="#222",
        template_variant="right_triangle",
    ))

    # 2. Right angle marker (small square at bottom-left)
    marker_size = min(w, h) * 0.12
    draw_calls.append(client.send_freehand(
        session_id=session_id,
        points=[
            {"x": x + marker_size, "y": y + h},
            {"x": x + marker_size, "y": y + h - marker_size},
            {"x": x, "y": y + h - marker_size},
        ],
        color="#666",
        stroke_width=1.5,
        delay_ms=0,
    ))

    # 3. Labels at side midpoints
    if len(labels) >= 1:
        draw_calls.append(client.send_text(
            session_id, labels[0],
            x=x + w * 0.4, y=y + h + 0.01,
            font_size=16, color="#222",
        ))
    if len(labels) >= 2:
        draw_calls.append(client.send_text(
            session_id, labels[1],
            x=x + w + 0.01, y=y + h * 0.5,
            font_size=16, color="#222",
        ))
    if len(labels) >= 3:
        draw_calls.append(client.send_text(
            session_id, labels[2],
            x=x + w * 0.35, y=y + h * 0.35,
            font_size=16, color="#222",
        ))

    await asyncio.gather(*draw_calls)

    return f"Right triangle with labels {', '.join(labels)}"
```

#### `renderers/quadrilateral.py` — Rhombus Example

```python
import asyncio
from typing import Awaitable
from canvas.state import BBox
from drawing_client import DrawingClient


async def render_rhombus(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    params: dict,
    labels: list[str],
) -> str:
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height
    cx, cy = x + w / 2, y + h / 2

    vertices = [
        {"x": cx, "y": y},
        {"x": x + w, "y": cy},
        {"x": cx, "y": y + h},
        {"x": x, "y": cy},
        {"x": cx, "y": y},  # close
    ]

    draw_calls: list[Awaitable] = []

    # Outline
    draw_calls.append(client.send_freehand(
        session_id=session_id, points=vertices,
        color="#222", stroke_width=2.0, delay_ms=35,
    ))

    # Diagonals
    draw_calls.append(client.send_freehand(
        session_id=session_id,
        points=[{"x": cx, "y": y}, {"x": cx, "y": y + h}],
        color="#888", stroke_width=1.0, delay_ms=0,
    ))
    draw_calls.append(client.send_freehand(
        session_id=session_id,
        points=[{"x": x, "y": cy}, {"x": x + w, "y": cy}],
        color="#888", stroke_width=1.0, delay_ms=0,
    ))

    # Labels
    if len(labels) >= 1:
        draw_calls.append(client.send_text(
            session_id, labels[0], x=cx + 0.01, y=cy - 0.04,
            font_size=14, color="#222",
        ))
    if len(labels) >= 2:
        draw_calls.append(client.send_text(
            session_id, labels[1], x=cx - 0.04, y=cy + 0.01,
            font_size=14, color="#222",
        ))

    await asyncio.gather(*draw_calls)

    return f"Rhombus with labels {', '.join(labels)}"
```

#### `renderers/graph.py` — Coordinate Plane + Line Plotting

```python
import asyncio
from canvas.state import BBox
from drawing_client import DrawingClient
from math_verify import parse_linear_equation, evaluate_linear


async def render_graph(
    client: DrawingClient,
    session_id: str,
    bbox: BBox,
    equations: list[str],
    x_min: float,
    x_max: float,
) -> str:
    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height

    # Compute y_range from all equations
    all_y_vals = []
    for eq_str in equations:
        slope, intercept = parse_linear_equation(eq_str)
        all_y_vals.append(evaluate_linear(slope, intercept, x_min))
        all_y_vals.append(evaluate_linear(slope, intercept, x_max))
    y_min_data = min(all_y_vals) - 1  # padding
    y_max_data = max(all_y_vals) + 1

    # 1. Draw cartesian axes using existing template
    await client.send_shape(
        session_id=session_id,
        shape="polygon",
        x=bbox.x, y=bbox.y,
        width=bbox.width, height=bbox.height,
        color="#999",
        template_variant="cartesian_axes",
    )

    # 2. Axis labels
    await client.send_text(session_id, "x", x=x + w - 0.02, y=y + h * 0.52, font_size=14, color="#999")
    await client.send_text(session_id, "y", x=x + w * 0.52, y=y + 0.01, font_size=14, color="#999")

    # 3. Plot each equation
    colors = ["#e74c3c", "#2980b9", "#27ae60", "#8e44ad"]
    for i, eq_str in enumerate(equations):
        slope, intercept = parse_linear_equation(eq_str)
        color = colors[i % len(colors)]

        points = []
        num_samples = 40
        for s in range(num_samples + 1):
            x_val = x_min + (x_max - x_min) * s / num_samples
            y_val = evaluate_linear(slope, intercept, x_val)

            # Map data coords → normalized bbox coords
            nx = x + w * (x_val - x_min) / (x_max - x_min)
            ny = y + h * (1 - (y_val - y_min_data) / (y_max_data - y_min_data))

            # Clamp to bbox
            if 0 <= nx <= 1 and 0 <= ny <= 1:
                points.append({"x": nx, "y": ny})

        if len(points) >= 2:
            await client.send_freehand(
                session_id=session_id,
                points=points,
                color=color,
                stroke_width=2.5,
                delay_ms=20,
            )

        # Equation label
        await client.send_text(
            session_id, eq_str,
            x=x + w * 0.6, y=y + 0.02 + i * 0.04,
            font_size=14, color=color,
        )

    return f"Graph of {', '.join(equations)} on [{x_min}, {x_max}]"
```

**Verify:** For each renderer, write a test that calls it with a mock DrawingClient and asserts the correct number/type of draw calls were made with coordinates within the bbox.

---

### Step 5: Tool Logging Decorator

**File:** `tools/_logging.py`

ADK streaming mode does **not** support `before_tool_callback` / `after_tool_callback`. Per ADK docs, "Callback" is listed as not yet supported in streaming. Instead, we embed observability directly into the tool functions via a decorator.

```python
import functools
import logging
import time
from google.adk.tools import ToolContext

logger = logging.getLogger("sona.tools")


def logged_tool(func):
    """Decorator that logs every tool call with session ID, args, and latency.

    Replaces ADK's before_tool_callback / after_tool_callback, which are
    not supported in streaming (run_live) mode.
    """
    @functools.wraps(func)
    async def wrapper(*args, tool_context: ToolContext, **kwargs):
        session_id = tool_context.state.get("session_id", "unknown")
        start = time.monotonic()
        logger.info(
            "tool_call | session=%s | tool=%s | args=%s",
            session_id, func.__name__, kwargs,
        )
        try:
            result = await func(*args, tool_context=tool_context, **kwargs)
        except Exception:
            latency_ms = (time.monotonic() - start) * 1000
            logger.exception(
                "tool_error | session=%s | tool=%s | latency=%.0fms",
                session_id, func.__name__, latency_ms,
            )
            return {"status": "error", "message": "Internal tool error"}
        latency_ms = (time.monotonic() - start) * 1000
        logger.info(
            "tool_done | session=%s | tool=%s | latency=%.0fms | status=%s",
            session_id, func.__name__, latency_ms, result.get("status", "?"),
        )
        return result
    return wrapper
```

---

### Step 6: The 5 Tools

**Files:** `tools/write_math.py`, `tools/draw_diagram.py`, `tools/plot_graph.py`, `tools/new_line.py`, `tools/clear_canvas.py`

All tools follow the same pattern:
1. Get `session_id` from `tool_context.state`
2. Get `CanvasState` for that session
3. Estimate element size
4. Call `canvas.allocate()` to get position
5. Delegate to `DrawingClient` or a renderer
6. Return `{"status": "success", "drawn": "..."}` — minimal response, no canvas summary

All tools are wrapped with `@logged_tool` for observability.

#### Tool 1: `write_math.py`

```python
from google.adk.tools import ToolContext
from canvas.store import get_canvas_state
from drawing_client import DrawingClient
from tools._logging import logged_tool

# Module-level client — initialized from config at startup
drawing_client: DrawingClient = None  # set in main.py


def estimate_text_width(text: str, font_size: int = 28) -> float:
    """Estimate normalized canvas width for text at given font size."""
    char_width = 0.012 * (font_size / 28)
    wide_chars = sum(1 for c in text if c in "²³√∑∏∫≤≥≠±×÷")
    effective_len = len(text) + wide_chars * 0.5
    return min(effective_len * char_width, 0.44)


@logged_tool
async def write_math(
    text: str,
    tool_context: ToolContext,
) -> dict[str, str]:
    """Write a math equation or text on the whiteboard.

    Automatically positioned at the current writing position,
    flowing left-to-right like a teacher writing on a board.

    Use for: equations (a² + b² = c²), step labels (Step 1:),
    results (Therefore x = 5), or any text.

    Args:
        text: What to write. Use standard math notation.
    """
    session_id: str = tool_context.state["session_id"]
    canvas = get_canvas_state(session_id)

    width = estimate_text_width(text, font_size=28)
    height = 0.06
    bbox = canvas.allocate(width, height)

    await drawing_client.send_text(
        session_id=session_id,
        text=text,
        x=bbox.x,
        y=bbox.y,
        font_size=28,
        color="#222",
    )

    return {"status": "success", "drawn": f"Wrote: {text}"}
```

#### Tool 2: `draw_diagram.py`

```python
from google.adk.tools import ToolContext
from canvas.store import get_canvas_state
from drawing_client import DrawingClient
from renderers import SHAPE_REGISTRY
from tools._logging import logged_tool

drawing_client: DrawingClient = None


def parse_shape_request(description: str) -> tuple[str, dict]:
    """Parse natural language shape description.

    'right triangle with sides 3, 4, 5'  → ('right triangle', {'sides': [3, 4, 5]})
    'circle with radius 7'               → ('circle', {'radius': 7})
    'rhombus with diagonals 6 and 8'     → ('rhombus', {'diagonals': [6, 8]})
    'hexagon'                             → ('hexagon', {})
    'rectangle 4 by 3'                    → ('rectangle', {'width_val': 4, 'height_val': 3})

    Implementation uses regex patterns, not an LLM. The parser handles:
    1. Shape type extraction (longest match against SHAPE_REGISTRY keys)
    2. Numeric parameter extraction ('sides 3, 4, 5' → [3, 4, 5])
    3. Named parameter extraction ('radius 7' → {radius: 7})
    """
    import re

    desc_lower = description.lower().strip()

    # Match longest known shape type
    matched_type = ""
    for shape_name in sorted(SHAPE_REGISTRY.keys(), key=len, reverse=True):
        if desc_lower.startswith(shape_name):
            matched_type = shape_name
            break

    if not matched_type:
        # Fuzzy fallback: check if any key is a substring
        for shape_name in SHAPE_REGISTRY:
            if shape_name in desc_lower:
                matched_type = shape_name
                break

    if not matched_type:
        matched_type = desc_lower.split(" ")[0]

    # Extract numeric parameters
    params: dict = {}
    numbers = [float(n) for n in re.findall(r"-?\d+\.?\d*", desc_lower)]

    if "side" in desc_lower and numbers:
        params["sides"] = numbers
    elif "radius" in desc_lower and numbers:
        params["radius"] = numbers[0]
    elif "diagonal" in desc_lower and numbers:
        params["diagonals"] = numbers
    elif "by" in desc_lower and len(numbers) >= 2:
        params["width_val"] = numbers[0]
        params["height_val"] = numbers[1]
    elif numbers:
        params["values"] = numbers

    if "equilateral" in desc_lower:
        params["equilateral"] = True

    return (matched_type, params)


@logged_tool
async def draw_diagram(
    shape: str,
    labels: list[str] = [],
    title: str = "",
    tool_context: ToolContext,
) -> dict[str, str]:
    """Draw a labeled geometric shape on the whiteboard.

    Handles any shape: triangle, right triangle, circle, rectangle,
    rhombus, parallelogram, trapezoid, pentagon, hexagon, square, etc.

    The shape is automatically sized and placed at the current writing
    position. Labels are placed at sides or vertices. Use natural
    descriptions for the shape parameter.

    For math-specific properties, include them in the shape description:
    - "right triangle with sides 3, 4, 5"
    - "circle with radius 7"
    - "rhombus with diagonals 6 and 8"

    Args:
        shape: What to draw (e.g. "right triangle with sides 3, 4, 5").
        labels: Side or vertex labels (e.g. ["a=3", "b=4", "c=5"]).
        title: Optional title displayed above the diagram.
    """
    session_id: str = tool_context.state["session_id"]
    canvas = get_canvas_state(session_id)

    shape_type, params = parse_shape_request(shape)

    renderer = SHAPE_REGISTRY.get(shape_type)
    if renderer is None:
        return {"status": "error", "message": f"Unknown shape: {shape_type}"}

    size = 0.28
    bbox = canvas.allocate(width=size, height=size)

    if title:
        await drawing_client.send_text(
            session_id, title,
            x=bbox.x, y=bbox.y - 0.04,
            font_size=16, color="#555",
        )

    description = await renderer(
        client=drawing_client,
        session_id=session_id,
        bbox=bbox,
        params=params,
        labels=labels,
    )

    return {"status": "success", "drawn": description}
```

#### Tool 3: `plot_graph.py`

```python
from google.adk.tools import ToolContext
from canvas.store import get_canvas_state
from drawing_client import DrawingClient
from math_verify import parse_linear_equation, compute_intersection
from renderers.graph import render_graph
from tools._logging import logged_tool

drawing_client: DrawingClient = None


@logged_tool
async def plot_graph(
    equations: list[str],
    x_min: float = -5,
    x_max: float = 5,
    tool_context: ToolContext,
) -> dict[str, str]:
    """Plot equations on a coordinate plane with labeled axes.

    Draws cartesian axes and plots one or more linear equations.
    Supports linear equations in y = mx + b form.
    For systems of equations, pass multiple equations to see their intersection.

    Args:
        equations: Equations to plot (e.g. ["y = 2x + 3"] or ["y = x + 1", "y = -x + 4"]).
        x_min: Left bound of x-axis (default -5).
        x_max: Right bound of x-axis (default 5).
    """
    session_id: str = tool_context.state["session_id"]
    canvas = get_canvas_state(session_id)

    bbox = canvas.allocate(width=0.38, height=0.35)

    # Verify equations parse correctly (SymPy)
    parsed = []
    for eq in equations:
        try:
            slope, intercept = parse_linear_equation(eq)
            parsed.append((eq, slope, intercept))
        except ValueError:
            return {"status": "error", "message": f"Cannot parse equation: {eq}"}

    description = await render_graph(
        client=drawing_client,
        session_id=session_id,
        bbox=bbox,
        equations=equations,
        x_min=x_min,
        x_max=x_max,
    )

    # If system of equations, find and annotate intersection
    if len(parsed) == 2:
        m1, b1 = parsed[0][1], parsed[0][2]
        m2, b2 = parsed[1][1], parsed[1][2]
        intersection = compute_intersection(m1, b1, m2, b2)
        if intersection:
            description += f". Intersection at ({intersection[0]:.1f}, {intersection[1]:.1f})"

    return {"status": "success", "drawn": description}
```

#### Tool 4: `new_line.py`

```python
from google.adk.tools import ToolContext
from canvas.store import get_canvas_state
from tools._logging import logged_tool


@logged_tool
async def new_line(tool_context: ToolContext) -> dict[str, str]:
    """Move to the next line on the whiteboard.

    Like a teacher moving their hand down to start writing on the line below.
    Use this between sections, after a diagram, or when starting a new thought.
    """
    session_id: str = tool_context.state["session_id"]
    canvas = get_canvas_state(session_id)
    canvas.newline()

    return {"status": "success"}
```

#### Tool 5: `clear_canvas.py`

```python
from google.adk.tools import ToolContext
from canvas.store import get_canvas_state
from drawing_client import DrawingClient
from tools._logging import logged_tool

drawing_client: DrawingClient = None


@logged_tool
async def clear_canvas(tool_context: ToolContext) -> dict[str, str]:
    """Erase everything on the whiteboard and start fresh.

    Use when starting a completely new problem or topic.
    The writing position resets to the top-left of the board.
    """
    session_id: str = tool_context.state["session_id"]
    canvas = get_canvas_state(session_id)

    await drawing_client.send_clear(session_id)
    canvas.clear()

    return {"status": "success", "drawn": "Canvas cleared"}
```

#### `tools/__init__.py` — Re-export for ADK Agent

```python
from tools.write_math import write_math
from tools.draw_diagram import draw_diagram
from tools.plot_graph import plot_graph
from tools.new_line import new_line
from tools.clear_canvas import clear_canvas

ALL_TOOLS = [write_math, draw_diagram, plot_graph, new_line, clear_canvas]
```

**Verify:** Integration test — start drawing service + frontend, call each tool function programmatically, confirm drawings appear on canvas.

---

### Step 7: Shape Description Parser

**File:** `tools/draw_diagram.py` (the `parse_shape_request` function — shown above in Step 6)

Converts natural language shape descriptions into structured params:

```
Input                                    → Type              → Params
─────────────────────────────────────────────────────────────────────────
"right triangle with sides 3, 4, 5"     → "right triangle"  → {sides: [3, 4, 5]}
"circle with radius 7"                  → "circle"          → {radius: 7}
"rhombus with diagonals 6 and 8"        → "rhombus"         → {diagonals: [6, 8]}
"hexagon"                               → "hexagon"         → {}
"rectangle 4 by 3"                      → "rectangle"       → {width_val: 4, height_val: 3}
"equilateral triangle side 5"           → "triangle"        → {side: 5, equilateral: True}
"parallelogram"                         → "parallelogram"   → {}
"number line from -3 to 5"             → "number line"     → {values: [-3, 5]}
```

Uses regex patterns, not an LLM. The parser handles:
1. Shape type extraction (longest match against SHAPE_REGISTRY keys)
2. Numeric parameter extraction ("sides 3, 4, 5" → `[3, 4, 5]`)
3. Named parameter extraction ("radius 7" → `{radius: 7}`)

**Verify:** Unit test with ~20 natural language inputs and expected outputs.

---

### Step 8: Wire Tools into ADK Agent

**File:** `agent/agent.py`

```python
import os
from google.adk.agents import Agent
from tools import ALL_TOOLS

SYSTEM_PROMPT = """You are Sona, a friendly AI math tutor for middle school students.

TEACHING STYLE:
- Speak in short, clear sentences
- Draw on the whiteboard AS you explain — don't explain first then draw
- After drawing, pause briefly so the student can see what you drew
- Confirm student understanding before moving on

WHITEBOARD:
- You have a two-panel whiteboard that fills left-to-right like a real classroom board
- Use write_math for equations and text
- Use draw_diagram for ANY geometric shape (triangle, circle, rhombus — anything)
- Use plot_graph for graphing linear equations on coordinate planes
- Use new_line to move down on the board
- Use clear_canvas when switching to a new problem

CANVAS AWARENESS:
- When you see an image of the canvas in the conversation, that is the student's drawing
- Analyze what the student drew and respond to it naturally
- If the student draws something incorrect, gently point it out

SCOPE — You teach these 6 topics ONLY:
1. Linear equations
2. Graphing linear equations
3. Systems of equations
4. Pythagorean theorem
5. Triangle properties
6. Circles

If a student asks about anything outside these topics, politely redirect:
"That's a great question! But I specialize in [list topics]. Want to explore one of those?"

MATH ACCURACY:
- Never state a numerical result without the tool verifying it
- Show your work step by step on the whiteboard
- If you make a mistake, acknowledge it and correct it on the board
"""

root_agent = Agent(
    name="sona",
    model=os.getenv("SONA_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"),
    instruction=SYSTEM_PROMPT,
    description="AI math tutor with collaborative whiteboard",
    tools=ALL_TOOLS,
)

# ── Streaming configuration ──────────────────────────────────
# When running the agent via runner.run_live(), the streaming config
# is passed through RunConfig — NOT through the Agent constructor.
#
# In main.py (Phase 2):
#
#   from google.adk.agents.run_config import RunConfig
#   from google.genai import types
#
#   run_config = RunConfig(
#       response_modalities=["AUDIO"],
#       speech_config=types.SpeechConfig(
#           voice_config=types.VoiceConfig(
#               prebuilt_voice_config=types.PrebuiltVoiceConfig(
#                   voice_name="Puck"
#               )
#           )
#       ),
#   )
#
#   async for event in runner.run_live(
#       user_id=user_id,
#       session_id=session_id,
#       live_request_queue=live_request_queue,
#       run_config=run_config,
#   ):
#       ...

# ── Tool execution strategy ──────────────────────────────────
# ADK v1.10.0+ executes async tool functions in parallel automatically.
# All Sona tools are async and complete in <100ms (HTTP POST + circuit breaker).
# Gemini's audio pauses for ~50-100ms during tool execution — imperceptible.
#
# The raw Gemini Live API supports NON_BLOCKING function behavior, but ADK
# abstracts this away. Since our tools are fast enough, the brief pause
# is acceptable and we avoid the complexity of bypassing ADK.

# ── Tool call cancellation ────────────────────────────────────
# When a student interrupts mid-drawing (barge-in), Gemini Live sends a
# ToolCallCancellation event. ADK surfaces this in the event stream.
# The WebSocket bridge (main.py) should handle this by logging the
# cancellation — the drawing client's fire-and-forget nature means
# already-sent POST requests will complete harmlessly.
```

**Verify:** Run `adk web` locally, select `sona` agent, test each tool fires correctly when Gemini decides to use it. Verify voice responses are fluent and tools execute without noticeable pauses.

---

## Canvas Snapshot Integration (Orchestrator ↔ Frontend)

This section documents how the student's drawings reach Gemini — without a tool.

### Frontend Responsibility

When the student stops drawing (1.5s silence / inactivity), the frontend:

1. Checks a **dirty flag** — skip if nothing changed since last snapshot
2. Exports canvas to **384×384 JPEG, quality 0.5** (~15–30KB)
3. Strips the `data:image/jpeg;base64,` prefix
4. Sends the base64 string to the orchestrator via WebSocket as a JSON message:
   ```json
   {"type": "snapshot", "data": "<base64_jpeg>"}
   ```

```typescript
// src/services/canvasExporter.ts
export function exportCanvas(canvas: HTMLCanvasElement): string {
    const offscreen = document.createElement('canvas');
    offscreen.width = 384;
    offscreen.height = 384;
    const ctx = offscreen.getContext('2d')!;
    ctx.drawImage(canvas, 0, 0, 384, 384);
    return offscreen.toDataURL('image/jpeg', 0.5).split(',')[1];
}
```

### Orchestrator Responsibility

The orchestrator's upstream task (in `main.py`, Phase 2) handles snapshot messages by pushing them into Gemini's conversation context **without triggering a response**:

```python
# Inside upstream_task() in main.py:
elif json_message.get("type") == "snapshot":
    import base64
    jpeg_bytes = base64.b64decode(json_message["data"])
    content = types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
            types.Part(text="[The student updated the canvas]"),
        ],
    )
    # turn_complete=False → Gemini absorbs the image silently
    # without generating a response. Next time the student speaks,
    # Gemini already has the canvas state in context.
    live_request_queue.send_content(content)
```

### Why This Works

- **258 tokens per image** — same as ~8 seconds of audio. Negligible context cost.
- **No tool round-trip** — Gemini sees the image directly, no function call overhead.
- **Silent pre-loading** — `send_content` without `turn_complete` means no response is generated. The image sits in context waiting for the student's next utterance.
- **Dirty flag** — prevents redundant snapshots from eating context window tokens.

---

## Dependency Graph

```
Step 0: Orchestrator Skeleton
    │
    ├── Step 1: Drawing Client
    │       │
    │       └── Step 2: Canvas State + Cursor
    │               │
    │               ├── Step 3: Math Verification (SymPy)
    │               │
    │               └── Step 4: Shape Renderers
    │                       │
    │                       └── Step 5: Tool Logging Decorator
    │                               │
    │                               └── Step 6: The 5 Tools
    │                                       │
    │                                       └── Step 7: Shape Parser
    │                                               │
    │                                               └── Step 8: ADK Agent
```

Steps 1, 2, and 3 can be built in parallel (no dependencies between them).
Step 4 depends on 1 + 2. Step 5 is standalone. Step 6 depends on 1–5. Steps 7 and 8 are sequential.

---

## Testing Strategy

### Unit Tests (per step)
- **Canvas State:** Cursor flow, line wrapping, panel jumping, clear/reset, TTL cleanup
- **Drawing Client:** Correct JSON payloads (mock httpx), circuit breaker open/half-open/close
- **Math Verify:** Pythagorean check, triangle inequality, linear equation parsing (positive slope, negative slope, no intercept, coefficient on y, constant function), intersection computation
- **Shape Parser:** ~20 natural language inputs → correct type + params
- **Each Renderer:** Correct draw calls with coordinates within allocated bbox (mock DrawingClient)
- **Logging Decorator:** Confirm logger.info called with correct format, latency measured

### Integration Tests (after Step 6)
- Start drawing service + frontend
- Call tool functions programmatically with a mock ToolContext
- Confirm elements appear on the canvas at correct positions
- Confirm cursor advances correctly across multiple tool calls

### End-to-End Test (after Step 8)
- Start all services
- Connect via `adk web` or WebSocket
- Say "Teach me Pythagorean theorem"
- Verify: voice response + equation + triangle appear on canvas
- Verify: content flows left-to-right, doesn't overlap

---

## Production Hardening

These decisions were validated against Google ADK documentation (v1.10+), Gemini Live API behavior, and production voice agent patterns:

| Concern | Decision | Why |
|---------|----------|-----|
| **Dead air** | All tools `async def`, complete in <100ms. ADK auto-parallelizes. | ADK doesn't expose NON_BLOCKING. 50–100ms pause is imperceptible. |
| **Tool response size** | Return only `{"status": "success", "drawn": "..."}` | Large responses bloat context window and add latency. Gemini doesn't need coordinates. |
| **Canvas state** | Cursor-only, no element registry, TTL cleanup (1 hour) | Minimal memory footprint. Prevents stale state and memory leaks. |
| **HTTP timeout** | 500ms with circuit breaker (3 failures → open, 30s → half-open) | Drawing is non-critical. Silent degradation > error messages. Recovery prevents permanent lockout. |
| **Renderer HTTP calls** | `asyncio.gather()` for parallel execution | 3–5 POST calls per renderer. Parallel ≈ 3x faster than sequential. |
| **SymPy parsing** | `@lru_cache` on all parse/verify functions. Proper `sympy.solve()` with `local_dict`. | Cache = ~50ms vs ~200ms. `local_dict` prevents code injection. |
| **User interruption** | Handle `ToolCallCancellation` in WebSocket bridge | Student says "wait" mid-drawing → ADK surfaces cancellation event. Already-sent POSTs complete harmlessly. |
| **Tool count** | 5 tools (well under 10–20 recommended limit) | Fewer tools = faster Gemini selection, less ambiguity. |
| **Tool observability** | `@logged_tool` decorator on every tool function | ADK streaming mode doesn't support agent-level callbacks. In-tool logging is the only reliable approach. |
| **Canvas snapshots** | 384×384 JPEG, `send_content` with `turn_complete=False` | 258 tokens per image. Silent pre-loading hides latency behind student's speech pause. |
| **Model** | `gemini-2.5-flash-native-audio-preview-12-2025` via env var | Current stable Live API model. Env var allows switching without code changes. |
| **Streaming config** | `RunConfig` with `response_modalities=["AUDIO"]` | `generate_content_config` is for non-streaming path only. `RunConfig` is the correct streaming config. |
| **Session state** | `session_id` injected via `create_session(state={...})` | Tools read `tool_context.state["session_id"]`. State must be initialized at session creation. |

---

## What This Plan Does NOT Cover (future phases)

- Gemini Live API WebSocket bridge / audio streaming (`main.py` Phase 2)
- Frontend audio capture/playback (`useAudio.ts`)
- Session service integration (session lifecycle, Firestore persistence)
- Infrastructure / Cloud Run deployment (Terraform)
- Session resumption for >10 minute conversations (`SessionResumptionConfig`)
- Context window compression for long tutoring sessions (`ContextWindowCompressionConfig`)
- Highlight tool (can be added as 6th tool later if needed)
