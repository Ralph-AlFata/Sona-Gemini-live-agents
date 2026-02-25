# Sona — AI Math Tutor

Sona is a voice-first AI math tutor with a live collaborative whiteboard. Students interact via voice while Sona draws progressively on an HTML5 canvas in real-time, synchronized with speech. Built for the Google Gemini Live Agent Challenge.

## Architecture

Microservices on Google Cloud Run:
- **Frontend**: React + TypeScript + HTML5 Canvas (Konva.js)
- **Session Service**: FastAPI — session lifecycle, Firestore + Cloud Storage
- **Agent Orchestrator**: FastAPI + Google ADK — Gemini Live API, tool calls, multimodal input
- **Drawing Command Service**: FastAPI — stroke DSL, WebSocket streaming

## Python Environment

Always use `uv` — never `pip` directly.

```bash
# Activate
source .venv/bin/activate        # macOS/Linux

# If you want to add dependencies, add it to the pyproject.toml file and run
uv sync
```

Each microservice has its own `pyproject.toml` and its own `.venv`. Never share virtual environments across services.

## Project Structure

```
sona/
├── frontend/                  # React + TypeScript
├── services/
│   ├── session/               # Session Service
│   ├── orchestrator/          # Agent Orchestrator
│   └── drawing/               # Drawing Command Service
├── infra/                     # IaC (Cloud Run deployment scripts)
└── CLAUDE.md
```

## Coding Guardrails

**General**
- Each service is independently deployable — no cross-service imports
- All inter-service communication via WebSocket or HTTP — never direct function calls across service boundaries
- Environment variables only via `.env` files (never hardcode secrets or API keys)
- All `.env` files are gitignored

**Python**
- Python 3.11+ only
- Type hints required on all function signatures
- Use `async/await` throughout — no blocking calls in FastAPI routes
- One `pyproject.toml` per service, kept in sync after every new install

**Frontend**
- TypeScript strict mode enabled — no `any` types
- Canvas drawing logic lives exclusively in the Drawing module — never in components directly
- WebSocket connection managed in a single service layer, not scattered across components

**Google ADK & Gemini**
- All Gemini tool definitions live in `orchestrator/tools/` — one file per tool
- Never call Gemini directly from the frontend — always proxy through the orchestrator
- Canvas snapshots sent to Gemini must be base64 PNG only

**Math Grounding**
- All mathematical computations must go through SymPy verification before Sona states a result — never let the LLM do raw arithmetic
- Sona is scoped to 6 topics only: linear equations, graphing linear equations, systems of equations, Pythagorean theorem, triangle properties, circles
- If a student asks outside this scope, Sona deflects — do not extend the topic list without explicit team agreement

## Deployment

- All services deploy to Google Cloud Run
- Use `infra/` scripts for deployment — no manual console deploys
- Each service has its own `Dockerfile`
- Cloud Run services communicate via internal URLs only (not public endpoints between services)