#!/usr/bin/env bash
set -euo pipefail

echo "=== StrixNote Install ==="

# Check Docker permissions
./scripts/check-docker.sh

# Initialize data folders
./scripts/init-data.sh

# Start containers
./scripts/dc.sh up -d

echo "Waiting for services to start..."
sleep 5

# Preload model
./scripts/preload-model.sh

echo ""
echo "Install complete."
echo "Open: http://<your-server-ip>:8080"
