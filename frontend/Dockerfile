# syntax=docker/dockerfile:1

# ─── Stage 1: builder ────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

# Declare build args — passed via --build-arg in CI or gcloud run deploy
ARG VITE_FIREBASE_API_KEY
ARG VITE_SESSION_HTTP_BASE
ARG VITE_DRAWING_HTTP_BASE
ARG VITE_ORCHESTRATOR_WS_BASE
ARG VITE_DRAWING_WS_BASE

ENV VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY
ENV VITE_SESSION_HTTP_BASE=$VITE_SESSION_HTTP_BASE
ENV VITE_DRAWING_HTTP_BASE=$VITE_DRAWING_HTTP_BASE
ENV VITE_ORCHESTRATOR_WS_BASE=$VITE_ORCHESTRATOR_WS_BASE
ENV VITE_DRAWING_WS_BASE=$VITE_DRAWING_WS_BASE

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
RUN npm run build

# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM nginx:alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
