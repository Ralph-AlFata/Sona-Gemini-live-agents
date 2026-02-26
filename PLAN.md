# Sona — Build Plan & Task List

## Project State
**Greenfield.** Only `CLAUDE.md`, `.gitignore`, `.env` (empty), and empty service directories exist. Everything must be built from scratch.

**Deadline:** March 16, 2026 (~19 days)

---

## Build Order (dependency graph)

```
Phase 0 (root scaffolding)
    ├── Phase 1 (session service) ──┐
    └── Phase 2 (drawing service) ──┼──▶ Phase 3 (orchestrator) ──▶ Phase 4 (frontend)
                                    │
Phase 5 (infra, parallel)          ─┘                                        │
                                                                              ▼
                                                               Phase 6 (integration)
                                                                              │
                                                                              ▼
                                                               Phase 7 (deploy + demo)
```

---

## Tasks

### Phase 0 — Root Scaffolding
- [ ] **0.1** Create `docker-compose.yml` — 4 services (session:8003, drawing:8002, orchestrator:8001, frontend:3000), shared `sona-net` network, `env_file: .env`, health checks, `depends_on` chain
- [ ] **0.2** Create `.env.example` — document: GOOGLE_API_KEY, GOOGLE_CLOUD_PROJECT, GOOGLE_GENAI_USE_VERTEXAI, FIRESTORE_DATABASE, GCS_BUCKET, DRAWING_SERVICE_URL, SESSION_SERVICE_URL
- [ ] **0.3** Update `README.md` — setup instructions, architecture diagram embed, env vars table, docker-compose quick start

---

### Phase 1 — Session Service (`services/session/`)
> Simplest service. Pure CRUD. Must work before orchestrator.

- [*] **1.1** Create `pyproject.toml` — deps: `fastapi[standard]`, `uvicorn[standard]`, `pydantic>=2`, `google-cloud-firestore`, `google-cloud-storage`, `python-dotenv`, `httpx`
- [*] **1.2** Create `Dockerfile` — uv-based image, exposes port 8003
- [*] **1.3** Create `models.py` — `Session`, `SessionCreate`, `ConversationTurn`, `CanvasSnapshot` (Pydantic v2, strict types)
- [*] **1.4** Create `firestore.py` — `AsyncClient`; ops: `create_session`, `get_session`, `append_turn`, `update_snapshot_url`; collection: `sessions`, doc ID = `session_id`
- [*] **1.5** Create `storage.py` — upload PNG bytes to GCS bucket `sona-canvases`; path: `snapshots/{session_id}/{timestamp}.png`; return public URL
- [*] **1.6** Create `main.py` — endpoints: `POST /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/turns`, `POST /sessions/{id}/snapshot`, `DELETE /sessions/{id}`, `GET /health`; use `lifespan` context manager

**Checkpoint:** `curl localhost:8003/health` → 200; `POST /sessions` creates Firestore doc

---

### Phase 2 — Drawing Command Service (`services/drawing/`)
> Translates orchestrator tool calls → stroke DSL → WebSocket broadcast to frontend.

- [ ] **2.1** Create `pyproject.toml` — deps: `fastapi[standard]`, `uvicorn[standard]`, `pydantic>=2`, `python-dotenv`, `websockets`, `httpx`, `sympy`
- [ ] **2.2** Create `Dockerfile` — port 8002
- [ ] **2.3** Create `models.py` — `Point` (normalized 0–1), `FreehandPayload`, `ShapePayload`, `TextPayload`, `HighlightPayload`, `DSLMessage`, `DrawRequest`
- [ ] **2.4** Create `dsl.py` — `translate(draw_request: DrawRequest) -> list[DSLMessage]`; freehand chunks points into batches of 5–10 for progressive effect; shapes emit single instant message; text/highlight are direct passthroughs; generate ID with `uuid.uuid4().hex[:8]`
- [ ] **2.5** Create `templates.py` — normalized-coord point sequences: `right_triangle()`, `circle_outline()`, `number_line()`, `cartesian_axes()`
- [ ] **2.6** Create `main.py` — `ConnectionManager` class (`session_id → set[WebSocket]`); `WS /ws/{session_id}`; `POST /draw` → translate → `asyncio.create_task(broadcast)`; `POST /draw/clear`; `GET /health`

**Checkpoint:** `wscat -c ws://localhost:8002/ws/test` in tab 1; `POST /draw` in tab 2 → JSON DSL message appears in tab 1

---

### Phase 3 — Agent Orchestrator (`services/orchestrator/`)
> Core brain — ADK agent, Gemini Live bidi-streaming, tool definitions, WebSocket audio bridge.

- [ ] **3.1** Create `pyproject.toml` — deps: `fastapi[standard]`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `google-adk>=1.0`, `google-genai`, `python-dotenv`, `websockets`, `httpx`, `sympy`
- [ ] **3.2** Create `Dockerfile` — port 8001
- [ ] **3.3** Create `config.py` — `Settings(BaseSettings)`: GOOGLE_API_KEY, DRAWING_SERVICE_URL, SESSION_SERVICE_URL, `model_name="gemini-2.0-flash-live-001"`
- [ ] **3.4** Create `models.py` — `AudioChunk`, `ControlMessage`, `WSMessage`
- [ ] **3.5** Create `agent/__init__.py`
- [ ] **3.6** Create `agent/tools/__init__.py` — re-exports all tool functions
- [ ] **3.7** Create `agent/tools/draw_freehand.py` — `async def draw_freehand_path(tool_context, points, color, stroke_width, speed)`: reads `session_id` from `tool_context.state`, POSTs to drawing service
- [ ] **3.8** Create `agent/tools/draw_shape.py` — `async def draw_shape(tool_context, shape, x, y, width, height, color, fill_color)`
- [ ] **3.9** Create `agent/tools/write_text.py` — `async def write_text(tool_context, text, x, y, font_size, color)`
- [ ] **3.10** Create `agent/tools/highlight_region.py` — `async def highlight_region(tool_context, x, y, width, height, color)`
- [ ] **3.11** Create `agent/tools/clear_area.py` — `async def clear_area(tool_context, x, y, width, height)` — all coord params optional
- [ ] **3.12** Create `agent/tools/analyze_canvas.py` — fetch snapshot from session service, send to Gemini vision via `tool_context`, return description
- [ ] **3.13** Create `agent/agent.py` — `root_agent = Agent(name="sona", model="gemini-2.0-flash-live-001", instruction=SYSTEM_PROMPT, tools=[...])` with full system prompt: 6-topic scope guard, drawing style (draw as you speak, normalized coords), voice style (short sentences, confirm understanding)
- [ ] **3.14** Create `main.py` — WS `/ws/{session_id}`:
  - On connect: `get_or_create_session()`, set `adk_session.state["session_id"] = session_id`, create `LiveRequestQueue`
  - `upstream_task`: bytes → `live_queue.send_realtime(PCM blob)`; JSON `snapshot` type → send image blob
  - `downstream_task`: `runner.run_live()` audio `inline_data` → `ws.send_bytes()`; `turn_complete` / `interrupted` → send JSON control frames
  - `asyncio.gather(upstream, downstream)` in try/finally with `live_queue.close()`

**Checkpoint:** `wscat` to ws://localhost:8001/ws/test, speak → hear audio back; drawing service logs HTTP POSTs when Sona draws

---

### Phase 4 — Frontend (`frontend/`)
> React 18 + TypeScript + Vite + Fabric.js canvas + two WebSocket connections.

- [ ] **4.1** Create `package.json` — deps: `react@^18`, `react-dom@^18`, `fabric@^6.4`; dev deps: `@types/react`, `@vitejs/plugin-react`, `typescript@^5`, `vite@^5`
- [ ] **4.2** Create `tsconfig.json` — `strict: true`, `target: "ES2022"`, `lib: ["ES2022", "DOM"]`
- [ ] **4.3** Create `vite.config.ts` — dev proxy: `/api/orchestrator` → `http://localhost:8001`, `/api/drawing` → `http://localhost:8002`
- [ ] **4.4** Create `index.html`
- [ ] **4.5** Create `src/types/dsl.ts` — `Point`, `FreehandPayload`, `ShapePayload`, `TextPayload`, `HighlightPayload`, `DSLMessage`, `DSLMessageType` union
- [ ] **4.6** Create `src/types/session.ts` — `SessionState` with status: `'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking'`
- [ ] **4.7** Create `src/hooks/useWebSocket.ts` — manages WS ref, reconnect with exponential backoff (1s → 2s → 4s → max 30s)
- [ ] **4.8** Create `src/hooks/useAudio.ts` — **capture:** `getUserMedia` at 16kHz, `ScriptProcessorNode`, Float32→Int16 PCM → WS bytes; **playback:** receive PCM at 24kHz, schedule via `AudioContext.currentTime`
- [ ] **4.9** Create `src/hooks/useSession.ts` — check localStorage for sessionId; POST to create if missing; sync to URL `?session=<id>`
- [ ] **4.10** Create `src/services/audioProcessor.ts` — `float32ToInt16()`, `int16ToFloat32()` utilities
- [ ] **4.11** Create `src/services/canvasExporter.ts` — `exportCanvas(canvas): string` returns base64 JPEG (no `data:` prefix)
- [ ] **4.12** Create `src/services/drawingRenderer.ts` — `DrawingRenderer` class:
  - `activePaths: Map<string, {path: fabric.Path, points: Point[]}>`
  - `processMessage(msg: DSLMessage)` dispatcher
  - `extendPath()` — accumulate points, rebuild SVG path string, `path.set({path: parsedPath})` + `canvas.renderAll()` + `delay(speed ms)` per batch (progressive animation)
  - `renderShape()`, `renderText()`, `renderHighlight()` — Fabric.js object creation
  - `exportAsJPEG(): string`
- [ ] **4.13** Create `src/components/StatusIndicator.tsx` — visual states: idle / connecting / listening (green pulse) / thinking (yellow spin) / speaking (blue bars)
- [ ] **4.14** Create `src/components/SessionControls.tsx` — Mute/Unmute, Clear Canvas (`POST /draw/clear`), End Session buttons
- [ ] **4.15** Create `src/components/AudioManager.tsx` — orchestrator WS, `useAudio` hook, updates status on `turn_complete` / `interrupted` / audio bytes
- [ ] **4.16** Create `src/components/Whiteboard.tsx` — Fabric.js canvas, drawing service WS, silence-based snapshot trigger (1.5s inactivity → `exportAsJPEG` → send to orchestrator WS)
- [ ] **4.17** Create `src/App.tsx` — layout: top bar (logo + StatusIndicator + SessionControls) + main Whiteboard
- [ ] **4.18** Create `src/main.tsx` — React entry point
- [ ] **4.19** Create `Dockerfile` — multi-stage: `node:20-alpine` builder → `nginx:alpine`; port 3000
- [ ] **4.20** Create `nginx.conf` — serve `/` → index.html

**Checkpoint:** Open http://localhost:3000, say "explain Pythagorean theorem" → hear voice AND see triangle drawn simultaneously

---

### Phase 5 — Infrastructure (`infra/`)
> Can be done in parallel with Phases 1–4.

- [ ] **5.1** Create `variables.tf` — `project_id`, `region` (default: us-central1), `gcs_bucket_name`
- [ ] **5.2** Create `main.tf` — Cloud Run API enablement, GCS bucket, Firestore DB (native mode), 4× `google_cloud_run_v2_service`, IAM for public access on orchestrator + frontend, Secret Manager for GOOGLE_API_KEY
- [ ] **5.3** Create `outputs.tf` — `frontend_url`, `orchestrator_url`

**Checkpoint:** `terraform plan` runs without errors

---

### Phase 6 — Integration
> Wire everything together and verify end-to-end flows.

- [ ] **6.1** Thread `session_id` through tool context — verify `tool_context.state["session_id"]` works in each tool; fallback: inject as explicit LLM-visible tool argument
- [ ] **6.2** Validate canvas snapshot flow — 1.5s silence → JPEG export → orchestrator WS → `analyze_canvas` tool fires → Sona responds
- [ ] **6.3** Add `CORSMiddleware` to all FastAPI services (allow localhost:3000 + Cloud Run URLs)
- [ ] **6.4** Validate interruption/barge-in — frontend drains PCM buffer on `{"type":"interrupted"}`; Gemini VAD handles the rest
- [ ] **6.5** Run full end-to-end test sequence:
  - "What topics can you help with?" → voice only, no drawing
  - "Teach me Pythagorean theorem" → voice + triangle drawn simultaneously
  - Draw your own triangle → wait 1.5s → Sona comments
  - Interrupt Sona mid-sentence → Sona stops cleanly
  - "Graph y = 2x + 3" → axes + line drawn
  - Ask about calculus → Sona redirects politely

---

### Phase 7 — Deploy + Demo
- [ ] **7.1** Build and push Docker images to GCR for all 4 services
- [ ] **7.2** Run `terraform apply` — deploy all Cloud Run services
- [ ] **7.3** Record 4-minute demo video (canonical sequence: Pythagorean theorem walkthrough)
- [ ] **7.4** Create `docs/architecture.png` — export from Excalidraw
- [ ] **7.5** Finalize `README.md` — add Cloud Run URLs, architecture diagram, hackathon compliance table

---

## Key Risks

| Risk | Mitigation |
|------|-----------|
| `gemini-2.0-flash-live-001` model issues | Test immediately after Phase 3 orchestrator skeleton. Switch model name if needed. |
| ADK `ToolContext` / session_id threading | Test in Phase 3 before building frontend. Fallback: pass session_id as explicit tool arg. |
| Fabric.js path extension performance | Cap strokes at 500 points; start new segment if exceeded. |
| PCM sample rate mismatch | Test 16kHz capture → Gemini → 24kHz playback in isolation before canvas integration. |
| WS reconnect loops | Exponential backoff with 30s ceiling in `useWebSocket.ts`. |

---

## Critical Files (highest complexity / highest risk)
- `services/orchestrator/main.py` — ADK streaming loop, LiveRequestQueue, event routing
- `services/orchestrator/agent/agent.py` — model name + tool registration
- `services/drawing/main.py` — ConnectionManager broadcast logic
- `frontend/src/services/drawingRenderer.ts` — Fabric.js progressive path extension
- `frontend/src/hooks/useAudio.ts` — PCM capture at 16kHz + playback at 24kHz

---

## Python Environment Reminder
- Always `uv sync`, never `pip install`
- Each service has its own `pyproject.toml` + `.venv`
- Activate per service: `source services/<name>/.venv/bin/activate`
