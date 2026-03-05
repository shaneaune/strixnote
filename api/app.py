import os
import re
import time
import shutil
from pathlib import Path

import requests
from flask import Flask, request, jsonify, Response

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


def wait_meili_task(task_uid, timeout_s=3.0, interval_s=0.1):
    """
    Best-effort: poll Meilisearch task status for a short time so the API can
    report failures (e.g., invalid filter) instead of silently enqueuing.
    """
    if task_uid is None:
        return None

    deadline = time.time() + float(timeout_s)
    last = None

    while time.time() < deadline:
        try:
            r = requests.get(
                f"{MEILI_URL}/tasks/{task_uid}",
                headers=meili_headers(),
                timeout=5,
            )
            r.raise_for_status()
            last = r.json()

            status = (last.get("status") or "").lower()
            if status in ("succeeded", "failed", "canceled"):
                return last
        except Exception as e:
            # Don’t fail the delete endpoint due to task polling.
            return {"uid": task_uid, "status": "unknown", "poll_error": str(e)}

        time.sleep(interval_s)

    # Timed out waiting; return last known state (likely enqueued/processing)
    return last or {"uid": task_uid, "status": "unknown", "note": "poll_timeout"}


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


def _meili_request(method: str, path: str, json_body=None, timeout=5):
    url = f"{MEILI_URL}{path}"
    headers = {**meili_headers()}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    r = requests.request(method, url, headers=headers, json=json_body, timeout=timeout)
    return r


def ensure_meili_schema():
    """
    Best-effort verification that required indexes exist and have the settings
    our API relies on (e.g., segments.filename filterable for delete-by-filter).
    Never raises to caller; logs and returns a dict summary.
    """
    summary = {"ok": False, "steps": []}

    if not MEILI_MASTER_KEY:
        summary["steps"].append({"skip": "MEILI_MASTER_KEY not set"})
        return summary

    # Health check
    try:
        r = _meili_request("GET", "/health", timeout=3)
        r.raise_for_status()
        summary["steps"].append({"health": r.json()})
    except Exception as e:
        summary["steps"].append({"health_error": str(e)})
        return summary

    def _ensure_index(uid: str, primary_key: str = "id"):
        # Create index if missing
        try:
            r = _meili_request("GET", f"/indexes/{uid}")
            if r.status_code == 200:
                summary["steps"].append({"index_exists": uid})
                return True
            if r.status_code != 404:
                r.raise_for_status()
        except Exception as e:
            summary["steps"].append({"index_check_error": {uid: str(e)}})
            return False

        try:
            r = _meili_request(
                "POST",
                "/indexes",
                json_body={"uid": uid, "primaryKey": primary_key},
                timeout=10,
            )
            # 200/202 on success; 409 if racing (fine)
            if r.status_code not in (200, 202, 409):
                r.raise_for_status()
            summary["steps"].append({"index_created": uid, "status": r.status_code})
            return True
        except Exception as e:
            summary["steps"].append({"index_create_error": {uid: str(e)}})
            return False

    # Ensure required indexes
    if not _ensure_index(INDEX_TRANSCRIPTS, "id"):
        return summary
    if not _ensure_index(INDEX_SEGMENTS, "id"):
        return summary

    # Ensure filterable attributes needed by the UI/API
    # segments: delete-by-filter + date filtering
    # transcripts: date filtering
    try:
        desired_segments = {"filename", "created_at", "recorded_at"}
        desired_transcripts = {"created_at", "recorded_at"}

        def ensure_filterables(index_uid: str, desired: set[str]):
            r = _meili_request("GET", f"/indexes/{index_uid}/settings/filterable-attributes")
            r.raise_for_status()
            current = set(r.json() or [])
            missing = sorted(desired - current)
            if missing:
                new = sorted(current | desired)
                r2 = _meili_request(
                    "PUT",
                    f"/indexes/{index_uid}/settings/filterable-attributes",
                    json_body=new,
                    timeout=10,
                )
                r2.raise_for_status()
                summary["steps"].append(
                    {"filterable_added": {"index": index_uid, "added": missing}}
                )
            else:
                summary["steps"].append({"filterable_ok": {"index": index_uid}})

        ensure_filterables(INDEX_SEGMENTS, desired_segments)
        ensure_filterables(INDEX_TRANSCRIPTS, desired_transcripts)

    except Exception as e:
        summary["steps"].append({"filterable_error": str(e)})
        return summary

    # Optional: ensure sortable attributes exist (nice-to-have)
    try:
        _meili_request(
            "PUT",
            f"/indexes/{INDEX_TRANSCRIPTS}/settings/sortable-attributes",
            json_body=["created_at"],
            timeout=10,
        )
        _meili_request(
            "PUT",
            f"/indexes/{INDEX_SEGMENTS}/settings/sortable-attributes",
            json_body=["created_at"],
            timeout=10,
        )
        summary["steps"].append({"sortable_set": True})
    except Exception as e:
        summary["steps"].append({"sortable_error": str(e)})

    summary["ok"] = True
    return summary


# Run Meili schema verification once per container start (avoid running in every gunicorn worker)
# Uses a simple file lock in /tmp shared by all workers in the container.
_LOCK_PATH = "/tmp/strixnote_meili_schema.lock"


def _try_acquire_lock(path: str) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        # If locking fails for any other reason, fall back to running anyway.
        return True


if _try_acquire_lock(_LOCK_PATH):
    try:
        _MEILI_SCHEMA_STATUS = ensure_meili_schema()
        print("Meili schema verification:", _MEILI_SCHEMA_STATUS, flush=True)
    except Exception as e:
        print("Meili schema verification failed:", str(e), flush=True)
else:
    print(
        "Meili schema verification: skipped (another worker already ran it)", flush=True
    )


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
            rejected.append(
                {"filename": orig, "reason": f"unsupported extension {ext}"}
            )
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

@app.route(
    "/meili/<path:subpath>",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
def meili_proxy(subpath: str):
    # Generic Meilisearch reverse-proxy so the browser never needs keys.
    # Nginx routes /api/* -> this Flask app, so /api/meili/... becomes /meili/...
    try:
        url = f"{MEILI_URL}/{subpath}"

        # Forward query string
        if request.query_string:
            url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"

        # Forward body (raw bytes so it works for JSON and non-JSON)
        data = request.get_data()

        # Forward only safe headers; always inject Authorization here
        headers = {}
        ct = request.headers.get("Content-Type")
        if ct:
            headers["Content-Type"] = ct

        accept = request.headers.get("Accept")
        if accept:
            headers["Accept"] = accept

        headers.update(meili_headers())

        r = requests.request(
            request.method,
            url,
            headers=headers,
            data=data if data else None,
            timeout=15,
        )

        # Pass through Meili response (status + content-type + body)
        resp = Response(r.content, status=r.status_code)
        resp.headers["Content-Type"] = r.headers.get(
            "Content-Type", "application/json"
        )
        return resp

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

    return jsonify(
        {
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
        }
    )


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
            if isinstance(tasks["segments"], dict) and "taskUid" in tasks["segments"]:
                tasks["segments_task"] = wait_meili_task(tasks["segments"]["taskUid"])
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

                    dj = dr.json() if dr.content else {}
                    # Keep the last task status (good enough for minimal hardening)
                    if isinstance(dj, dict) and "taskUid" in dj:
                        tasks["segments_fallback_task"] = wait_meili_task(dj["taskUid"])

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

    # If Meili explicitly failed, surface it as a non-ok response.
    # Disk deletion may still have succeeded; this only reflects index cleanup status.
    meili_failed = False
    error_message = None

    for k in ("segments_task", "segments_fallback_task"):
        st = tasks.get(k) or {}
        if isinstance(st, dict) and (st.get("status") or "").lower() == "failed":
            meili_failed = True
            err = st.get("error") or {}
            if isinstance(err, dict):
                error_message = err.get("message") or str(err)
            else:
                error_message = str(err)

    ok = not meili_failed

    response = {
        "ok": ok,
        "filename": filename,
        "deleted_files": deleted_files,
        "meili": tasks,
    }

    if not ok and error_message:
        response["error"] = f"Meilisearch task failed: {error_message}"

    if not ok:
        return jsonify(response), 502

    return jsonify(response), 200
# -----------------------------
# Settings (persisted JSON)
# -----------------------------

SETTINGS_DIR = os.path.join(DATA_DIR, "config")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

DEFAULT_SETTINGS = {
    "whisper": {
        "language": "",       # "" = auto
        "beam_size": 5,       # int
        "vad_filter": False,  # bool
    },
    "meili": {
        "typo_tolerance": True,  # bool
        "synonyms": {},          # dict[str, list[str]]
    },
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base or {})
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = f.read().strip()
            if data:
                import json
                return json.loads(data)
    except Exception as e:
        print("Settings load error:", str(e), flush=True)
    return {}


def _coerce_bool(v, default=False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
    return bool(v) if isinstance(v, (int, float)) else default


def validate_settings(raw: dict) -> dict:
    """
    Returns a cleaned settings dict. Ignores unknown keys.
    """
    cleaned = _deep_merge({}, DEFAULT_SETTINGS)

    raw = raw or {}
    w = raw.get("whisper") or {}
    m = raw.get("meili") or {}

    # whisper.language: "" or "en" etc.
    lang = w.get("language", "")
    if lang is None:
        lang = ""
    if not isinstance(lang, str):
        lang = str(lang)
    lang = lang.strip()
    cleaned["whisper"]["language"] = lang

    # whisper.beam_size: int 1..10 (clamp)
    bs = w.get("beam_size", DEFAULT_SETTINGS["whisper"]["beam_size"])
    try:
        bs = int(bs)
    except Exception:
        bs = DEFAULT_SETTINGS["whisper"]["beam_size"]
    if bs < 1:
        bs = 1
    if bs > 10:
        bs = 10
    cleaned["whisper"]["beam_size"] = bs

    # whisper.vad_filter: bool
    cleaned["whisper"]["vad_filter"] = _coerce_bool(
        w.get("vad_filter", DEFAULT_SETTINGS["whisper"]["vad_filter"]),
        DEFAULT_SETTINGS["whisper"]["vad_filter"],
    )

    # meili.typo_tolerance: bool
    cleaned["meili"]["typo_tolerance"] = _coerce_bool(
        m.get("typo_tolerance", DEFAULT_SETTINGS["meili"]["typo_tolerance"]),
        DEFAULT_SETTINGS["meili"]["typo_tolerance"],
    )

    # meili.synonyms: dict[str, list[str]]
    syn = m.get("synonyms", {})
    if syn is None:
        syn = {}
    if not isinstance(syn, dict):
        syn = {}
    syn_out = {}
    for k, v in syn.items():
        if not isinstance(k, str):
            k = str(k)
        k = k.strip()
        if not k:
            continue
        if isinstance(v, str):
            v = [v]
        if isinstance(v, (list, tuple)):
            vals = []
            for item in v:
                if item is None:
                    continue
                s = item if isinstance(item, str) else str(item)
                s = s.strip()
                if s and s not in vals:
                    vals.append(s)
            if vals:
                syn_out[k] = vals
    cleaned["meili"]["synonyms"] = syn_out

    return cleaned


def save_settings(settings: dict) -> None:
    import json
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    tmp = SETTINGS_PATH + ".tmp"
    payload = json.dumps(settings, indent=2, sort_keys=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload + "\n")
    os.replace(tmp, SETTINGS_PATH)


@app.get("/settings")
def get_settings():
    current = load_settings()
    merged = _deep_merge(DEFAULT_SETTINGS, current)
    merged = validate_settings(merged)
    return jsonify({"ok": True, "settings": merged})


@app.put("/settings")
def put_settings():
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({"ok": False, "error": "invalid JSON"}), 400

    # Accept either {"settings": {...}} or just {...}
    raw = body.get("settings") if isinstance(body, dict) and "settings" in body else body
    if not isinstance(raw, dict):
        return jsonify({"ok": False, "error": "settings must be an object"}), 400

    cleaned = validate_settings(raw)
    try:
        save_settings(cleaned)
    except Exception as e:
        return jsonify({"ok": False, "error": f"failed to save settings: {e}"}), 500

    return jsonify({"ok": True, "settings": cleaned})