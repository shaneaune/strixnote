#!/usr/bin/env bash
set -euo pipefail

REQUIRED_INDEX_VERSION=1
INDEX_VERSION_FILE="${DATA_DIR:-./data}/status/index_version"

mkdir -p "$(dirname "$INDEX_VERSION_FILE")"

CURRENT_INDEX_VERSION="0"
if [ -f "$INDEX_VERSION_FILE" ]; then
  CURRENT_INDEX_VERSION="$(cat "$INDEX_VERSION_FILE" | tr -d '[:space:]')"
fi

if [ "$CURRENT_INDEX_VERSION" = "$REQUIRED_INDEX_VERSION" ]; then
  echo "Search index version is current: $CURRENT_INDEX_VERSION"
  exit 0
fi

echo "Search index version change detected."
echo "Current index version: $CURRENT_INDEX_VERSION"
echo "Required index version: $REQUIRED_INDEX_VERSION"
echo "Reindex is required."