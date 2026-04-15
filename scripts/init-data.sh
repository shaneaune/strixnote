#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Initializing data directories..."

mkdir -p ./data/incoming
mkdir -p ./data/processed
mkdir -p ./data/status
mkdir -p ./data/config
mkdir -p ./data/models
mkdir -p ./data/meili

echo "Data directories ready."
