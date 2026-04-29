#!/usr/bin/env bash
set -euo pipefail

echo "=== StrixNote Upgrade ==="

cd "$(dirname "$0")"

echo "Checking for local changes..."
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: Local changes detected."
  echo "Commit, stash, or discard changes before upgrading."
  exit 1
fi

echo "Ensuring .env exists..."
if [ ! -f .env ]; then
  echo "ERROR: .env file missing. Aborting."
  exit 1
fi

echo "Pulling latest code..."
git pull --ff-only

echo "Rebuilding and restarting containers..."
./scripts/dc.sh down
./scripts/dc.sh up -d --build

echo "Running data migrations..."
./scripts/dc.sh exec -T upload_api python /app_host/scripts/migrate.py || true

echo
echo "Container status:"
./scripts/dc.sh ps

echo
echo "Upgrade complete."
echo "Open StrixNote in your browser and verify functionality."