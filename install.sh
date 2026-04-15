#!/usr/bin/env bash
set -euo pipefail

echo "=== StrixNote Install ==="

# Check Docker permissions
./scripts/check-docker.sh

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
  echo "Open StrixNote at: http://$IP:8080"
else
  echo "Open StrixNote at: http://<your-server-ip>:8080"
fi

echo ""
echo "The Whisper model has been preloaded."
echo "You can open the page and try your first upload now."
