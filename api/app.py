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

@app.post("/meili/search/<index>")
def meili_search(index: str):
    # Proxy Meilisearch search so the browser never needs the Meili key.
    # Expects the request body to be the same JSON you would POST to /indexes/<index>/search
    body = request.get_json(silent=True) or {}

    # Basic allowlist to avoid proxying arbitrary indexes
    if index not in (INDEX_TRANSCRIPTS, INDEX_SEGMENTS):
        return jsonify({"error": "invalid index"}), 400

    try:
        r = requests.post(
            f"{MEILI_URL}/indexes/{index}/search",
            headers={**meili_headers(), "Content-Type": "application/json"},
            json=body,
            timeout=15,
        )
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": f"meili proxy failed: {e}"}), 502

@app.get("/status")
def status():
    filename = sanitize_filename(request.args.get("filename", ""))
    if not filename:
        return jsonify({"error": "missing filename"}), 400

    base = Path(filename).stem

    incoming_path = Path(INCOMING_DIR) / filename
    processing_path = Path(INCOMING_DIR) / ".processing" / filename

    processed_audio = Path(PROCESSED_DIR) / filename
    processed_txt = Path(PROCESSED_DIR) / f"{base}.txt"
    processed_srt = Path(PROCESSED_DIR) / f"{base}.srt"
    processed_vtt = Path(PROCESSED_DIR) / f"{base}.vtt"

    if processed_audio.exists() and processed_txt.exists():
        state = "done"
    elif processing_path.exists():
        state = "processing"
    elif incoming_path.exists():
        state = "queued"
    else:
        state = "missing"

    return jsonify({
        "ok": True,
        "state": state,
        "filename": filename,
        "base": base,
        "exists": {
            "incoming": incoming_path.exists(),
            "processing": processing_path.exists(),
            "processed_audio": processed_audio.exists(),
            "processed_txt": processed_txt.exists(),
            "processed_srt": processed_srt.exists(),
            "processed_vtt": processed_vtt.exists(),
        },
    })

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
        # segments: try delete-by-filter; if it fails, fall back to search+delete-batch
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

            # Fallback: search for matching docs, then delete by ids
            try:
                deleted = 0
                offset = 0
                limit = 1000

                while True:
                    sr = requests.post(
                        f"{MEILI_URL}/indexes/{INDEX_SEGMENTS}/search",
                        headers={**meili_headers(), "Content-Type": "application/json"},
                        json={
                            "q": filename,
                            "limit": limit,
                            "offset": offset,
                            "attributesToRetrieve": ["id", "filename"],
                        },
                        timeout=10,
                    )
                    sr.raise_for_status()
                    sj = sr.json()
                    hits = sj.get("hits", []) or []

                    ids = [
                        h["id"]
                        for h in hits
                        if h.get("filename") == filename and h.get("id")
                    ]

                    if not ids:
                        break

                    dr = requests.post(
                        f"{MEILI_URL}/indexes/{INDEX_SEGMENTS}/documents/delete-batch",
                        headers={**meili_headers(), "Content-Type": "application/json"},
                        json=ids,
                        timeout=10,
                    )
                    dr.raise_for_status()

                    deleted += len(ids)
                    offset += limit

                    if len(hits) < limit:
                        break

                tasks["segments_fallback"] = {"deleted": deleted}
            except Exception as e2:
                tasks["segments_fallback_error"] = str(e2)
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
