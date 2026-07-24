#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_ARGS=()

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

if [ "${STRIXNOTE_GPU:-0}" = "1" ]; then
  COMPOSE_ARGS+=(
    -f "$ROOT_DIR/docker-compose.yml"
    -f "$ROOT_DIR/docker-compose.gpu.yml"
  )
fi

if docker compose version >/dev/null 2>&1; then
  exec docker compose "${COMPOSE_ARGS[@]}" "$@"
elif command -v docker-compose >/dev/null 2>&1; then
  exec docker-compose "${COMPOSE_ARGS[@]}" "$@"
else
  echo "ERROR: Neither 'docker compose' nor 'docker-compose' is available."
  exit 1
fi