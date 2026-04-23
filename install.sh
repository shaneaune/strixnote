#!/usr/bin/env bash
set -euo pipefail

# Prevent recursive sg docker loop
if [[ "${STRIXNOTE_DOCKER_OK:-}" != "1" ]]; then
  export STRIXNOTE_DOCKER_OK=1
else
  echo "Docker group applied."
fi

echo "=== StrixNote Install ==="

# Ensure .env exists
if [ ! -f .env ]; then
  echo "Creating .env from .env.example..."
  cp .env.example .env
fi

# Ensure openssl is available
if ! command -v openssl >/dev/null 2>&1; then
  echo "Installing openssl..."
  sudo apt update
  sudo apt install -y openssl
fi

# Ensure MEILI_MASTER_KEY exists
if ! grep -q "^MEILI_MASTER_KEY=" .env; then
  echo "Generating Meilisearch master key..."
  KEY="$(openssl rand -base64 32 | tr -d '\n')"
  echo "MEILI_MASTER_KEY=$KEY" >> .env
fi

# Ensure required packages are installed
if ! command -v docker >/dev/null 2>&1 || ! command -v docker-compose >/dev/null 2>&1; then
  echo "Installing Docker and required packages..."
  sudo apt update
  sudo apt install -y sudo docker.io docker-compose git
  sudo systemctl enable docker
  sudo systemctl start docker
  sudo usermod -aG sudo "$(whoami)"
  sudo usermod -aG docker "$(whoami)"

  echo "Refreshing docker group for current shell..."
  exec sg docker -c "STRIXNOTE_DOCKER_OK=1 $0 $*"
fi

# Check Docker permissions
./scripts/check-docker.sh "$0" "$@"

# Initialize data folders
./scripts/init-data.sh

# Start containers
./scripts/dc.sh up -d

echo "Waiting for Meilisearch to become ready..."
READY=0
for i in $(seq 1 30); do
  if ./scripts/dc.sh exec -T meilisearch /bin/sh -c "wget -qO- http://127.0.0.1:7700/health >/dev/null 2>&1"; then
    echo "Meilisearch is ready."
    READY=1
    break
  fi
  sleep 2
done

if [ "$READY" -ne 1 ]; then
  echo "ERROR: Meilisearch did not become ready."
  echo "Check logs with: ./scripts/dc.sh logs"
  exit 1
fi

echo "Applying Meilisearch schema..."
./scripts/dc.sh exec -T upload_api python - <<'PY'
from app import ensure_meili_schema
import json
result = ensure_meili_schema()
print(json.dumps(result, indent=2))
if not result.get("ok"):
    raise SystemExit(1)
PY

# Preload model
echo "Preloading Whisper model..."
./scripts/preload-model.sh

echo ""
echo "Container status:"
./scripts/dc.sh ps

echo "+------------------------------------------------------------------------------+"
echo "|      /\___/\        ____  _        _      _   _       _                      |"
echo "|     /  o o  \      / ___|| |_ _ __(_)_  _| \ | | ___ | |_ ___                |"
echo "|    |   \^/   |     \___ \| __| '__| \ \/ /  \| |/ _ \| __/ _ \               |"
echo "|    |  (___)  |      ___) | |_| |  | |>  <| |\  | (_) | ||  __/               |"
echo "|    |  /   \  |     |____/ \__|_|  |_/_/\_\_| \_|\___/ \__\___|               |"
echo "|    |_/|_|_|\_|                                                               |"
echo "+------------------------------------------------------------------------------+"
IP=$(hostname -I | awk '{print $1}')

echo ""
echo "Container status:"
./scripts/dc.sh ps

echo ""
echo "Install complete."

if [ -n "$IP" ]; then
  echo "Open StrixNote at: http://$IP:${STRIXNOTE_WEB_PORT:-8080}"
else
  echo "Open StrixNote at: http://<your-server-ip>:${STRIXNOTE_WEB_PORT:-8080}"
fi

echo ""
echo "The Whisper model has been preloaded."
echo "You can open the page and try your first upload now."
