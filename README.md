# Sona — AI Math Tutor

Sona is a voice-first AI math tutor with a live collaborative whiteboard. Students interact via voice while Sona draws progressively on an HTML5 canvas in real-time, synchronized with speech. Built for the Google Gemini Live Agent Challenge.

## Architecture

| Service | Port | Description |
|---------|------|-------------|
| **Frontend** | 3000 | React + TypeScript + HTML5 Canvas |
| **Orchestrator** | 8001 | Google ADK + Gemini Live API, tool calls, audio bridge |
| **Drawing** | 8002 | Stroke DSL translator, WebSocket broadcast |
| **Session** | 8003 | Session lifecycle, Firestore + Cloud Storage |

All services communicate over a shared Docker network (`sona-net`) via HTTP and WebSocket.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 20+
- Docker + Docker Compose
- A GCP project with Firestore and Cloud Storage enabled
- A Gemini API key

## Quick Start

```bash
# 1. Clone the repo
git clone <repo-url> && cd sona

# 2. Configure environment
cp .env.example .env
# Fill in your GOOGLE_API_KEY, GOOGLE_CLOUD_PROJECT, etc.

# 3. Start all services
docker compose up --build

# 4. Open the app
open http://localhost:3000
```

## Local Development (per service)

Each service has its own virtual environment and dependencies.

```bash
cd services/<name>          # session, drawing, or orchestrator
uv sync --no-install-project
source .venv/bin/activate
uvicorn main:app --reload --port <port>
```

## Running Tests

```bash
cd services/<name>
uv sync --no-install-project
.venv/bin/pytest tests/ -v
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `GOOGLE_API_KEY` | Gemini API key | `AIza...` |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID | `my-project-123` |
| `GOOGLE_GENAI_USE_VERTEXAI` | Use Vertex AI instead of AI Studio | `false` |
| `FIRESTORE_DATABASE` | Firestore database name | `(default)` |
| `GCS_BUCKET` | Cloud Storage bucket for canvas snapshots | `sona-canvases` |
| `DRAWING_SERVICE_URL` | Drawing service internal URL | `http://drawing:8002` |
| `SESSION_SERVICE_URL` | Session service internal URL | `http://session:8003` |
| `FRONTEND_URL` | Frontend origin for CORS | `http://localhost:3000` |

## Deployment

All services deploy to Google Cloud Run. See `infra/` for deployment scripts.
