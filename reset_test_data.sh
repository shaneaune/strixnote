#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="/opt/whisper-stack"
DATA_DIR="/storage/transcribe"
PROCESSED_DIR="${DATA_DIR}/processed"
INCOMING_DIR="${DATA_DIR}/incoming"
MEILI_DATA_DIR="${STACK_DIR}/meili_data"

echo "[1/4] Stopping containers..."
cd "$STACK_DIR"
docker compose down

echo "[2/4] Deleting processed + incoming contents..."
sudo mkdir -p "$PROCESSED_DIR" "$INCOMING_DIR"
sudo rm -f "${PROCESSED_DIR}/"* || true
sudo rm -f "${INCOMING_DIR}/"* || true

echo "[3/4] Removing Meilisearch data directory..."
sudo rm -rf "$MEILI_DATA_DIR"

echo "[4/4] Starting containers..."
docker compose up -d --build

# Initialize Meilisearch index settings (sortable attributes, etc.)
./init_meili.sh


echo "Done."
echo "Processed:  $PROCESSED_DIR"
echo "Incoming:   $INCOMING_DIR"
echo "Meili data: $MEILI_DATA_DIR (recreated on start)"
