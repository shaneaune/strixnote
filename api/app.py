import os
import re
import time
import shutil
from pathlib import Path

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

DATA_DIR = os.environ.get("DATA_DIR", "/data")
INCOMING_DIR = os.environ.get("INCOMING_DIR", f"{DATA_DIR}/incoming")
PROCESSED_DIR = os.environ.get("PROCESSED_DIR", f"{DATA_DIR}/processed")

MEILI_URL = os.environ.get("MEILI_URL", "http://meilisearch:7700")
MEILI_MASTER_KEY = os.environ.get("MEILI_MASTER_KEY", "")
INDEX_TRANSCRIPTS = os.environ.get("INDEX_TRANSCRIPTS", "transcripts")
INDEX_SEGMENTS = os.environ.get("INDEX_SEGMENTS", "segments")

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".mp4", ".webm"}

def meili_headers():
    return {"Authorization": f"Bearer {MEILI_MASTER_KEY}"} if MEILI_MASTER_KEY else {}

def sanitize_filename(name: str) -> str:
    # Keep original name as much as possible, but remove path separators and control chars.
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name

def safe_id_from_filename(filename: str) -> str:
    # Used only for deleting transcripts index (primary key is `id` = base).
    # Replace anything outside [A-Za-z0-9_-] with underscore.
    base = Path(filename).stem
    return re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_") or "file"

@app.get("/health")
def health():
    return jsonify({"ok": True, "time": int(time.time())})

@app.post("/upload")
def upload():
    os.makedirs(INCOMING_DIR, exist_ok=True)

    if "files" not in request.files:
        return jsonify({"error": "missing files field"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files"}), 400

    saved = []
    rejected = []

    for f in files:
        orig = sanitize_filename(f.filename or "")
        if not orig:
            rejected.append({"filename": "", "reason": "empty filename"})
            continue

        ext = Path(orig).suffix.lower()
        if ext not in AUDIO_EXTS:
            rejected.append({"filename": orig, "reason": f"unsupported extension {ext}"})
            continue

        dest = Path(INCOMING_DIR) / orig

        # Hard rule: do not overwrite existing files
        if dest.exists():
            rejected.append({"filename": orig, "reason": "already exists"})
            continue

        # Stream to disk
        f.save(str(dest))
        saved.append({"filename": orig, "bytes": dest.stat().st_size})

    return jsonify({"saved": saved, "rejected": rejected})

@app.post("/delete")
def delete():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    filename = sanitize_filename(filename)

    if not filename:
        return jsonify({"error": "missing filename"}), 400

    # Delete from disk
    base = Path(filename).stem
    paths = [
        Path(INCOMING_DIR) / filename,
        Path(PROCESSED_DIR) / filename,
        Path(PROCESSED_DIR) / f"{base}.txt",
        Path(PROCESSED_DIR) / f"{base}.srt",
        Path(PROCESSED_DIR) / f"{base}.vtt",
    ]

    deleted_files = []
    for p in paths:
        try:
            if p.exists():
                p.unlink()
                deleted_files.append(str(p))
        except Exception as e:
            return jsonify({"error": f"failed deleting {p}: {e}"}), 500

    # Delete from Meilisearch (best-effort)
    tasks = {}

    if MEILI_MASTER_KEY:
        # segments: delete by filter on filename
        try:
            r = requests.post(
                f"{MEILI_URL}/indexes/{INDEX_SEGMENTS}/documents/delete",
                headers={**meili_headers(), "Content-Type": "application/json"},
                json={"filter": f'filename = "{filename}"'},
                timeout=10,
            )
            r.raise_for_status()
            tasks["segments"] = r.json()
        except Exception as e:
            tasks["segments_error"] = str(e)

        # transcripts: delete by id = safe(base)
        try:
            safe_id = safe_id_from_filename(filename)
            r = requests.delete(
                f"{MEILI_URL}/indexes/{INDEX_TRANSCRIPTS}/documents/{safe_id}",
                headers=meili_headers(),
                timeout=10,
            )
            # delete is idempotent; don't fail hard if not found
            if r.status_code not in (200, 202, 204, 404):
                r.raise_for_status()
            tasks["transcripts"] = {"status": r.status_code, "id": safe_id}
        except Exception as e:
            tasks["transcripts_error"] = str(e)

    return jsonify({
        "ok": True,
        "filename": filename,
        "deleted_files": deleted_files,
        "meili": tasks,
    })
