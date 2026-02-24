#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
MEILI_MASTER_KEY="${MEILI_MASTER_KEY:-}"

# Read key from .env (prefer repo-local .env, then /opt/whisper-stack/.env)
if [ -z "${MEILI_MASTER_KEY}" ]; then
  for f in "$SCRIPT_DIR/.env" "/opt/whisper-stack/.env"; do
    if [ -f "$f" ]; then
      MEILI_MASTER_KEY="$(sed -n 's/^MEILI_MASTER_KEY=//p' "$f" | tail -n 1)"
      [ -n "${MEILI_MASTER_KEY}" ] && break
    fi
  done
fi

if [ -z "${MEILI_MASTER_KEY}" ]; then
  echo "ERROR: MEILI_MASTER_KEY is not set (and not found in .env)." >&2
  exit 1
fi

# Run a command inside the meilisearch container (no host port publishing required)
meili_sh() {
  docker compose exec -T meilisearch sh -lc "$1"
}

echo "Waiting for Meilisearch (inside container) ..."
i=0
while :; do
  if meili_sh "curl -fsS http://127.0.0.1:7700/health >/dev/null"; then
    break
  fi
  i=$((i+1))
  if [ "$i" -ge 60 ]; then
    echo "ERROR: Meilisearch did not become healthy in time." >&2
    exit 1
  fi
  sleep 1
done

auth="Authorization: Bearer ${MEILI_MASTER_KEY}"

ensure_index() {
  uid="$1"
  pk="$2"

  if meili_sh "curl -fsS -H \"$auth\" http://127.0.0.1:7700/indexes/$uid >/dev/null 2>&1"; then
    return 0
  fi

  echo "Creating index: $uid (primaryKey=$pk)"
  meili_sh "curl -fsS -H \"$auth\" -H \"Content-Type: application/json\" \
    -X POST http://127.0.0.1:7700/indexes \
    --data '{\"uid\":\"$uid\",\"primaryKey\":\"$pk\"}' >/dev/null || true"

  i=0
  while :; do
    if meili_sh "curl -fsS -H \"$auth\" http://127.0.0.1:7700/indexes/$uid >/dev/null 2>&1"; then
      break
    fi
    i=$((i+1))
    if [ "$i" -ge 60 ]; then
      echo "ERROR: index '$uid' did not become available in time." >&2
      exit 1
    fi
    sleep 1
  done
}

ensure_index "transcripts" "id"
ensure_index "segments" "id"

echo "Setting sortable attributes..."
meili_sh "curl -fsS -H \"$auth\" -H \"Content-Type: application/json\" \
  -X PUT http://127.0.0.1:7700/indexes/transcripts/settings/sortable-attributes \
  --data '[\"created_at\"]' >/dev/null"

meili_sh "curl -fsS -H \"$auth\" -H \"Content-Type: application/json\" \
  -X PUT http://127.0.0.1:7700/indexes/segments/settings/sortable-attributes \
  --data '[\"created_at\"]' >/dev/null"

echo "Setting filterable attributes..."
meili_sh "curl -fsS -H \"$auth\" -H \"Content-Type: application/json\" \
  -X PUT http://127.0.0.1:7700/indexes/segments/settings/filterable-attributes \
  --data '[\"filename\"]' >/dev/null"

echo "Done."
