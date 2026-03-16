#!/usr/bin/env bash
# Sona — full deploy script (all 4 services in dependency order)
# Usage: bash infra/deploy.sh
# Run from repo root. Requires gcloud CLI authenticated and PROJECT_ID set.

set -euo pipefail

# ─── Config ───────────────────────────────────────────────────────────────────
PROJECT_ID="${PROJECT_ID:-project-c3019c85-4428-4c46-9c2}"
REGION="${REGION:-us-central1}"
BUCKET="${BUCKET:-sona-canvases-your-suffix}"

SESS_SERVICE="sona-session"
DRAW_SERVICE="sona-drawing"
ORCH_SERVICE="sona-orchestrator"
FRONTEND_SERVICE="sona-frontend"

echo "=== Deploying Sona to project=${PROJECT_ID} region=${REGION} ==="

# ─── 1. Session ───────────────────────────────────────────────────────────────
echo ""
echo ">>> [1/4] Deploying session service..."
gcloud run deploy "$SESS_SERVICE" \
  --source ./services/session \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8003 \
  --service-account "sona-session-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},USE_FIRESTORE=true,FIRESTORE_DATABASE=(default),GCS_BUCKET=${BUCKET},SESSION_AUTH_ENABLED=true,FRONTEND_URL=https://PLACEHOLDER"

SESSION_URL=$(gcloud run services describe "$SESS_SERVICE" --region "$REGION" --format='value(status.url)')
echo "Session URL: $SESSION_URL"

# ─── 2. Drawing ───────────────────────────────────────────────────────────────
echo ""
echo ">>> [2/4] Deploying drawing service..."
gcloud run deploy "$DRAW_SERVICE" \
  --source ./services/drawing \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8002 \
  --timeout 3600 \
  --service-account "sona-drawing-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},USE_FIRESTORE=true,FIRESTORE_DATABASE=(default),DRAWING_AUTH_ENABLED=true,SESSION_SERVICE_URL=${SESSION_URL},FRONTEND_URL=https://PLACEHOLDER"

DRAWING_URL=$(gcloud run services describe "$DRAW_SERVICE" --region "$REGION" --format='value(status.url)')
echo "Drawing URL: $DRAWING_URL"

# ─── 3. Orchestrator ──────────────────────────────────────────────────────────
echo ""
echo ">>> [3/4] Deploying orchestrator service..."
gcloud run deploy "$ORCH_SERVICE" \
  --source ./services/orchestrator \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8001 \
  --timeout 3600 \
  --service-account "sona-orchestrator-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},ORCHESTRATOR_AUTH_ENABLED=true,SESSION_SERVICE_URL=${SESSION_URL},DRAWING_SERVICE_URL=${DRAWING_URL},FRONTEND_URL=https://PLACEHOLDER"

ORCH_URL=$(gcloud run services describe "$ORCH_SERVICE" --region "$REGION" --format='value(status.url)')
echo "Orchestrator URL: $ORCH_URL"

# ─── 4. Frontend ──────────────────────────────────────────────────────────────
gcloud run deploy sona-frontend \
    --source ./frontend \
    --region us-central1 \
    --allow-unauthenticated \
    --port 3000 \
    --set-build-env-vars "^@@^VITE_FIREBASE_API_KEY=AIzaSyAgg587h_-GbUSxzdf1d_ZTBD_zjmD56J0@@VITE_SESSION_HTTP_BASE=https://sona-session-5h3qmaqogq-uc.a.run.app@@VITE_DRAWING_HTTP_BASE=https://sona-drawing-5h3qmaqogq-uc.a.run.app@@VITE_DRAWING_WS_BASE=wss://sona-drawing-5h3qmaqogq-uc.a.run.app@@VITE_ORCHESTRATOR_WS_BASE=wss://sona-orchestrator-5h3qmaqogq-uc.a.run.app" 

# ─── 5. Fix CORS on all backends ──────────────────────────────────────────────
echo ""
echo ">>> [5/5] Updating CORS on all backend services..."
gcloud run services update "$SESS_SERVICE" --region "$REGION" --update-env-vars "FRONTEND_URL=${FRONTEND_URL}"
gcloud run services update "$DRAW_SERVICE" --region "$REGION" --update-env-vars "FRONTEND_URL=${FRONTEND_URL}"
gcloud run services update "$ORCH_SERVICE" --region "$REGION" --update-env-vars "FRONTEND_URL=${FRONTEND_URL}"

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "=== Deploy complete ==="
echo "  Frontend:     $FRONTEND_URL"
echo "  Session:      $SESSION_URL"
echo "  Drawing:      $DRAWING_URL"
echo "  Orchestrator: $ORCH_URL"
