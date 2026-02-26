# Sona Frontend Service — Technical Documentation

## Overview

The Sona frontend is a React 18 + TypeScript single-page application that renders a live collaborative whiteboard synchronized with the Drawing Command Service via WebSocket. Built with Vite 6 for development and deployed as a static site via Nginx. Uses Konva.js (react-konva) for HTML5 Canvas rendering.

**Port:** 3000 (dev and production)
**Session ID:** Hardcoded to `"dev-session"` (will be dynamic later)

---

## File Inventory

```
frontend/
├── package.json              # Dependencies and scripts
├── tsconfig.json             # TypeScript strict config (no `any` types)
├── tsconfig.node.json        # TypeScript config for vite.config.ts
├── vite.config.ts            # Dev server (port 3000) + WebSocket proxy
├── index.html                # Entry HTML with Patrick Hand font preload
├── Dockerfile                # Multi-stage: node:20-alpine → nginx:alpine
├── .dockerignore             # Excludes node_modules/, dist/, .env files
├── nginx.conf                # Port 3000, SPA fallback, static asset caching
├── simulate_stream.py        # Python script — simulates LLM token streaming
└── src/
    ├── main.tsx              # React entry point (no StrictMode — see note below)
    ├── App.tsx               # Root component — WebSocket orchestration + layout
    ├── App.css               # Flexbox layout, header styles, status dot animations
    ├── services/
    │   └── drawingSocket.ts  # Single WebSocket service layer (per CLAUDE.md)
    └── components/
        ├── Whiteboard.tsx    # Konva Stage + Layer, renders text on canvas
        └── MessageLog.tsx    # Debug overlay panel showing raw WS messages
```

---

## Architecture

### Component Hierarchy

```
<App>                         # WebSocket connection, state management
  ├── <header>                # Title "Sona" + connection status dot
  ├── <Whiteboard>            # Konva canvas, renders text items
  └── <MessageLog>            # Fixed overlay, last 50 raw JSON messages
```

### Data Flow

```
Drawing Service (port 8002)
  │  WebSocket: ws://localhost:8002/ws/{session_id}
  │
  ▼
drawingSocket.ts              # Parses JSON, invokes onMessage callback
  │
  ▼
App.tsx                       # Appends to messages[] state array
  │
  ├──▶ Whiteboard.tsx         # Filters type="text", converts [0,1] → pixels, renders <Text>
  └──▶ MessageLog.tsx         # Displays all messages as scrollable JSON
```

---

## WebSocket Service Layer (`src/services/drawingSocket.ts`)

Per CLAUDE.md: *"WebSocket connection managed in a single service layer, not scattered across components."*

### Public API

| Function | Signature | Description |
|----------|-----------|-------------|
| `connect` | `(sessionId: string, onMessage: OnMessage, onStatus: OnStatus) => void` | Opens WebSocket, registers callbacks |
| `disconnect` | `() => void` | Closes socket, clears timers, prevents reconnection |

### Types

```typescript
type ConnectionStatus = "disconnected" | "connecting" | "connected" | "reconnecting";

interface DSLMessageRaw {
  version: string;          // "1.0"
  id: string;               // 8-char unique ID
  session_id: string;
  type: string;             // "text" | "freehand" | "shape" | "highlight" | "clear"
  timestamp: string;        // ISO 8601
  payload: Record<string, unknown>;
}
```

### Connection Lifecycle

1. `connect()` is called from `App.tsx` on mount
2. Constructs URL: `ws://{host}/ws/drawing/{sessionId}` (Vite proxy rewrites to `/ws/{sessionId}`)
3. On open → status = `"connected"`, reset reconnect counter
4. On message → JSON.parse → invoke `onMessage` callback
5. On close (unexpected) → exponential backoff reconnect (1s → 2s → 4s → ... → 30s max)
6. On close (intentional via `disconnect()`) → status = `"disconnected"`, no reconnect

### WebSocket URL Routing (Development)

```
Frontend connects to:    ws://localhost:3000/ws/drawing/dev-session
Vite proxy rewrites to:  ws://localhost:8002/ws/dev-session
```

Configured in `vite.config.ts`:
```typescript
proxy: {
  "/ws/drawing": {
    target: "ws://localhost:8002",
    ws: true,
    rewrite: (path) => path.replace(/^\/ws\/drawing/, "/ws"),
  },
},
```

---

## Canvas Rendering (`src/components/Whiteboard.tsx`)

### Konva Layer Structure

```
<Stage>                       # Full viewport dimensions
  <Layer>                     # Background
    <Rect fill="#ffffff" />   # White background
  </Layer>
  <Layer>                     # Content
    <Text />                  # One per incoming "text" message
    <Text />
    ...
  </Layer>
</Stage>
```

### Coordinate Mapping

The Drawing Service uses **normalized [0, 1] coordinates**. Whiteboard converts them to pixels:

```typescript
pixelX = payload.x * canvasWidth
pixelY = payload.y * canvasHeight
```

**Example:** If canvas is 1200×800px and message has `x: 0.5, y: 0.3`:
- `pixelX = 0.5 × 1200 = 600px`
- `pixelY = 0.3 × 800 = 240px`

Coordinates recalculate on window resize, so text positions scale proportionally.

### Text Rendering

Each DSL message with `type: "text"` is rendered as a Konva `<Text>` node:

```typescript
<Text
  key={msg.id}               // Unique 8-char ID from drawing service
  x={pixelX}                 // Converted from normalized coordinate
  y={pixelY}
  text={payload.text}        // The word/text content
  fontSize={payload.font_size}  // Default: 18
  fill={payload.color}       // Default: "#000"
  fontFamily='"Patrick Hand", "Comic Sans MS", cursive'
/>
```

### Handwriting Font

- **Patrick Hand** loaded from Google Fonts via `<link>` in `index.html`
- Preconnect headers for faster DNS resolution
- `display=swap` shows fallback text immediately, swaps when font loads
- Fallback chain: Patrick Hand → Comic Sans MS → generic cursive

### Responsive Sizing

- Container div has `width: 100%; height: 100%`
- `useEffect` with `window.addEventListener("resize", updateSize)` tracks dimensions
- Konva Stage width/height bind to `dimensions` state
- Only renders when both dimensions > 0

---

## Root Component (`src/App.tsx`)

### State

| State | Type | Purpose |
|-------|------|---------|
| `status` | `ConnectionStatus` | WebSocket connection state (drives status dot color) |
| `messages` | `DSLMessageRaw[]` | Accumulated DSL messages from drawing service |
| `connectedRef` | `Ref<boolean>` | Guards against double-connection (React 18 dev mode) |

### Connection Setup

```typescript
useEffect(() => {
  if (connectedRef.current) return;    // Prevent double-connect
  connectedRef.current = true;
  connect(SESSION_ID, handleMessage, handleStatus);
  return () => { connectedRef.current = false; disconnect(); };
}, [handleMessage, handleStatus]);
```

**Why no StrictMode?** React 18's `<StrictMode>` double-mounts components in dev, which created two WebSocket connections and caused duplicate messages. Removed from `main.tsx` to fix this.

### Layout

```
┌─────────────────────────────────────┐
│ .app-header (44px fixed)            │  Title + status dot + status label
├─────────────────────────────────────┤
│                                     │
│ .app-canvas (flex: 1)               │  <Whiteboard messages={messages} />
│                                     │
└─────────────────────────────────────┘
                    ↑
        MessageLog (fixed, bottom-right overlay, z-index 1000)
```

### Status Dot Colors

| Status | Color | Animation |
|--------|-------|-----------|
| `disconnected` | Gray (`#ccc`) | None |
| `connecting` | Orange (`#f5a623`) | None |
| `connected` | Green (`#4cd964`) | None |
| `reconnecting` | Orange (`#f5a623`) | Pulse (opacity 1 → 0.4 → 1, 1s loop) |

---

## Debug Panel (`src/components/MessageLog.tsx`)

- Fixed-position overlay at bottom-right corner
- Shows last 50 raw WebSocket messages
- Toggle show/hide button
- Dark theme (VSCode-inspired: `#1e1e1e` background, `#d4d4d4` text)
- Auto-scrolls to bottom on new messages
- Each entry shows: message type (blue `#569cd6`), ID, and JSON payload (monospace)
- All styles are inline `React.CSSProperties` (no external CSS)

---

## DSL Message Types

### Currently Rendered on Canvas

| Type | Payload Fields | Description |
|------|---------------|-------------|
| `text` | `text`, `x`, `y`, `font_size`, `color` | Word rendered as Konva Text node |

### Received but Not Yet Rendered

| Type | Payload Fields | Description |
|------|---------------|-------------|
| `freehand` | `points[]`, `color`, `stroke_width`, `delay_ms` | Freehand stroke |
| `shape` | `shape`, `x`, `y`, `width`, `height`, `color`, `fill_color`, `template_variant` | Geometric shape |
| `highlight` | `x`, `y`, `width`, `height`, `color` | Rectangular highlight |
| `clear` | `mode` ("full") | Clear canvas |

All types appear in the MessageLog debug panel. Only `text` is rendered on the Konva canvas.

### Example DSL Message (as received via WebSocket)

```json
{
  "version": "1.0",
  "id": "a1b2c3d4",
  "session_id": "dev-session",
  "type": "text",
  "timestamp": "2026-02-25T10:30:45.123Z",
  "payload": {
    "text": "theorem",
    "x": 0.14,
    "y": 0.1,
    "font_size": 18,
    "color": "#333"
  }
}
```

---

## Stream Simulator (`simulate_stream.py`)

Python script that simulates LLM-style token streaming to the drawing service.

### What It Does

1. Checks drawing service health at `http://localhost:8002/health`
2. Splits a Pythagorean theorem paragraph into individual words
3. POSTs each word to `http://localhost:8002/draw` with calculated positions
4. Adds variable delays: 300ms after punctuation, 40–150ms otherwise

### Word Positioning

```python
x = 0.05 + (i % 10) * 0.09    # 10 words per row, 9% spacing
y = 0.1 + (i // 10) * 0.08    # New row every 10 words, 8% spacing
```

Row 1 x-values: 0.05, 0.14, 0.23, 0.32, 0.41, 0.50, 0.59, 0.68, 0.77, 0.86
Row 2 starts at y=0.18, Row 3 at y=0.26, etc.

### Usage

```bash
# Requires drawing service venv (has httpx)
source services/drawing/.venv/bin/activate
python frontend/simulate_stream.py
```

---

## Configuration

### TypeScript (`tsconfig.json`)

- `strict: true` — No `any` types (CLAUDE.md requirement)
- `noUncheckedIndexedAccess: true` — Forces null checks on dynamic property access
- `target: ES2022`, `jsx: react-jsx`, `moduleResolution: bundler`
- `noUnusedLocals: true`, `noUnusedParameters: true`

### Vite (`vite.config.ts`)

- React plugin with Fast Refresh
- Dev server on port 3000
- WebSocket proxy: `/ws/drawing/*` → `ws://localhost:8002/ws/*`

### Dependencies

**Runtime:** react `^18.3`, react-dom `^18.3`, konva `^9.3`, react-konva `^18.2`
**Dev:** typescript `^5.6`, vite `^6.0`, @vitejs/plugin-react `^4.3`, @types/react, @types/react-dom

### Build Output

```
dist/index.html                   0.90 kB │ gzip:   0.51 kB
dist/assets/index-*.css           0.64 kB │ gzip:   0.36 kB
dist/assets/index-*.js          446.09 kB │ gzip: 138.53 kB
```

---

## Docker Deployment

### Dockerfile (Multi-Stage)

**Stage 1 — Builder** (`node:20-alpine`):
1. Copy `package.json` + `package-lock.json`
2. `npm install`
3. Copy source files
4. `npm run build` (tsc type-check + vite build)

**Stage 2 — Runtime** (`nginx:alpine`):
1. Copy `/app/dist` → `/usr/share/nginx/html`
2. Copy `nginx.conf` → `/etc/nginx/conf.d/default.conf`
3. Expose port 3000
4. Run nginx in foreground

### Nginx (`nginx.conf`)

- Listens on port 3000
- SPA fallback: `try_files $uri $uri/ /index.html`
- Static asset caching: 1 year expiry with `Cache-Control: public, immutable`

### Docker Compose Integration

```yaml
frontend:
  build:
    context: ./frontend
  ports:
    - "3000:3000"
  depends_on:
    orchestrator:
      condition: service_healthy
```

---

## Development Workflow

### Quick Start

```bash
# Terminal 1: Drawing service
cd services/drawing && source .venv/bin/activate
uvicorn main:app --port 8002

# Terminal 2: Frontend dev server
cd frontend && npm run dev

# Terminal 3: Simulate streaming
source services/drawing/.venv/bin/activate
python frontend/simulate_stream.py
```

### What You'll See

1. Browser at `http://localhost:3000` shows white canvas with green "connected" dot
2. Simulator sends words one at a time to drawing service
3. Drawing service broadcasts each word via WebSocket
4. Words appear on canvas in handwritten "Patrick Hand" font at grid positions
5. MessageLog panel (bottom-right) shows raw JSON for each message

### Port Summary

| Service | Port | Protocol |
|---------|------|----------|
| Frontend (dev + prod) | 3000 | HTTP |
| Drawing Service | 8002 | HTTP + WebSocket |
| Session Service | 8003 | HTTP |
| Orchestrator | 8001 | HTTP |

---

## Known Decisions & Trade-offs

1. **No React StrictMode** — Removed to prevent double WebSocket connections in dev. The `connectedRef` guard is the alternative protection.
2. **Messages accumulate indefinitely** — `messages[]` array grows without limit. Fine for dev; will need windowing or cleanup for production.
3. **Only `text` type rendered** — Freehand, shape, highlight, and clear are received but not yet drawn on canvas. These are next steps.
4. **Hardcoded session ID** — `"dev-session"` is used everywhere. Will become dynamic when session service integration is added.
5. **No canvas interactivity** — Canvas is display-only. Student interaction (drawing, clicking) is a future feature.
6. **Inline styles in MessageLog** — Debug panel uses inline styles since it's a temporary dev tool, not worth a CSS file.
