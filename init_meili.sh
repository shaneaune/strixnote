#!/usr/bin/env bash
set -euo pipefail

MEILI_URL="${MEILI_URL:-http://127.0.0.1:7700}"
MEILI_MASTER_KEY="${MEILI_MASTER_KEY:-}"

if [[ -z "$MEILI_MASTER_KEY" ]]; then
  if [[ -f /opt/whisper-stack/.env ]]; then
    MEILI_MASTER_KEY="$(sed -n 's/^MEILI_MASTER_KEY=//p' /opt/whisper-stack/.env | tail -n 1)"
  fi
fi

if [[ -z "$MEILI_MASTER_KEY" ]]; then
  echo "ERROR: MEILI_MASTER_KEY is not set (and not found in /opt/whisper-stack/.env)." >&2
  exit 1
fi

hdr=(-H "Authorization: Bearer $MEILI_MASTER_KEY" -H "Content-Type: application/json")

echo "Waiting for Meilisearch at $MEILI_URL/health ..."
for i in {1..60}; do
  if curl -fsS "$MEILI_URL/health" >/dev/null; then
    break
  fi
  sleep 1
done

echo "Setting sortable attributes..."
curl -fsS -X PUT "$MEILI_URL/indexes/transcripts/settings/sortable-attributes" "${hdr[@]}" --data '["created_at"]' >/dev/null
curl -fsS -X PUT "$MEILI_URL/indexes/segments/settings/sortable-attributes"   "${hdr[@]}" --data '["created_at"]' >/dev/null

echo "Done."
