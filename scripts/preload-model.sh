#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p ./data/models

MODEL="${WHISPER_MODEL:-medium.en}"
DEVICE="${WHISPER_DEVICE:-cpu}"
COMPUTE="${WHISPER_COMPUTE:-int8}"

echo "Preloading Whisper model: ${MODEL} (device=${DEVICE}, compute=${COMPUTE})"
echo "This may take a few minutes on first run (model download + initialization)..."

DC="./scripts/dc.sh"

$DC run --rm \
  -e WHISPER_MODEL="${MODEL}" \
  -e WHISPER_DEVICE="${DEVICE}" \
  -e WHISPER_COMPUTE="${COMPUTE}" \
  -e HF_HUB_OFFLINE=0 \
  transcribe_worker \
  python - <<'PY'
import os
from faster_whisper import WhisperModel

model_name = os.environ.get("WHISPER_MODEL", "medium.en")
device = os.environ.get("WHISPER_DEVICE", "cpu")
compute = os.environ.get("WHISPER_COMPUTE", "int8")
model_dir = os.environ.get("WHISPER_MODEL_DIR", "/models")

print(f"Downloading/loading model: {model_name}", flush=True)
WhisperModel(
    model_name,
    device=device,
    compute_type=compute,
    download_root=model_dir,
)
print("Model preload complete.", flush=True)
PY
