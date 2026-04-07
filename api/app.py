"""
StrixNote API

Flask API responsible for:

- Uploading audio files
- Managing transcription jobs
- Proxying Meilisearch queries
- Returning transcript status
- Deleting audio/transcript files
- Rebuilding search indexes

Key routes:
POST /api/upload
POST /api/meili/search/<index>
POST /api/delete
POST /api/reindex
GET  /api/status
GET  /api/settings
PUT  /api/settings
"""

import os
import re
import time
import shutil
import json
from pathlib import Path
from datetime import datetime

import subprocess
import requests
from flask import Flask, request, jsonify, Response, send_file

app = Flask(__name__)


DATA_DIR = os.environ.get("DATA_DIR", "/data")
INCOMING_DIR = os.environ.get("INCOMING_DIR", f"{DATA_DIR}/incoming")
PROCESSED_DIR = os.environ.get("PROCESSED_DIR", f"{DATA_DIR}/processed")
STATUS_DIR = os.environ.get("STATUS_DIR", f"{DATA_DIR}/status")

def make_clip_output_path(base_name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", base_name)
    ts = int(time.time())
    return f"/tmp/{safe}_clip_{ts}.wav"

MEILI_URL = os.environ.get("MEILI_URL", "http://meilisearch:7700")
MEILI_MASTER_KEY = os.environ.get("MEILI_MASTER_KEY", "")
INDEX_TRANSCRIPTS = os.environ.get("INDEX_TRANSCRIPTS", "transcripts")
INDEX_SEGMENTS = os.environ.get("INDEX_SEGMENTS", "segments")

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".mp4", ".webm"}

REINDEX_RUNNING = False

MAX_UPLOAD_BYTES = (
    int(os.environ.get("MAX_UPLOAD_GB", "2")) * 1024 * 1024 * 1024
)  # default 2 GiB
MIN_FREE_BYTES = (
    int(os.environ.get("MIN_FREE_GB", "1")) * 1024 * 1024 * 1024
)  # default 1 GiB


def get_free_bytes(path: str) -> int:
    return shutil.disk_usage(path).free


def has_enough_disk(path: str, min_free_bytes: int) -> bool:
    try:
        return get_free_bytes(path) >= int(min_free_bytes)
    except Exception:
        # If we can't determine disk usage, fail closed (reject upload).
        return False


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

def progress_path_for(filename: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    if not safe:
        safe = "file"
    return Path(STATUS_DIR) / f"{safe}.progress.json"


def read_progress(filename: str) -> dict | None:
    try:
        p = progress_path_for(filename)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _meili_request(method: str, path: str, json_body=None, timeout=5):
    url = f"{MEILI_URL}{path}"
    headers = {**meili_headers()}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    r = requests.request(method, url, headers=headers, json=json_body, timeout=timeout)
    return r


def probe_duration_seconds(path: str) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def parse_vtt_segments(vtt_text: str) -> list[dict]:
    lines = (vtt_text or "").replace("\r", "").split("\n")
    segments = []
    i = 0

    def vtt_time_to_ms(ts: str) -> int:
        ts = (ts or "").strip()
        if "." not in ts:
            ts = ts + ".000"
        hhmmss, ms = ts.split(".", 1)
        h, m, s = [int(x) for x in hhmmss.split(":")]
        ms = int((ms + "000")[:3])
        return ((h * 3600 + m * 60 + s) * 1000) + ms

    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line or line == "WEBVTT":
            continue

        if "-->" not in line:
            continue

        start_raw, end_raw = [x.strip() for x in line.split("-->", 1)]
        cue_lines = []

        while i < len(lines) and lines[i].strip() != "":
            cue_lines.append(lines[i].strip())
            i += 1

        text = " ".join(cue_lines).strip()
        if not text:
            continue

        segments.append(
            {
                "start_ms": vtt_time_to_ms(start_raw),
                "end_ms": vtt_time_to_ms(end_raw),
                "text": text,
            }
        )

    return segments

def ms_to_vtt_timestamp(ms: int) -> str:
    total_ms = max(0, int(ms))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    seconds = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def ms_to_srt_timestamp(ms: int) -> str:
    return ms_to_vtt_timestamp(ms).replace(".", ",")


def write_vtt_segments(vtt_path: Path, segments: list[dict]) -> None:
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{ms_to_vtt_timestamp(seg['start_ms'])} --> {ms_to_vtt_timestamp(seg['end_ms'])}\n")
            f.write(f"{(seg.get('text') or '').strip()}\n\n")


def write_srt_segments(srt_path: Path, segments: list[dict]) -> None:
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{ms_to_srt_timestamp(seg['start_ms'])} --> {ms_to_srt_timestamp(seg['end_ms'])}\n")
            f.write(f"{(seg.get('text') or '').strip()}\n\n")


def write_txt_from_segments(txt_path: Path, segments: list[dict]) -> None:
    text = "\n".join((seg.get("text") or "").strip() for seg in segments if (seg.get("text") or "").strip())
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

def sanitize_segment_text(text: str, max_len: int = 300) -> str:
    cleaned = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split()).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned

def build_file_doc(audio_path: Path, txt_path: Path) -> dict:
    filename = audio_path.name
    base = audio_path.stem
    text = txt_path.read_text(encoding="utf-8").strip()
    created_at = int(audio_path.stat().st_mtime)

    return {
        "id": safe_id_from_filename(filename),
        "filename": filename,
        "text": text,
        "created_at": created_at,
        "recorded_at": created_at,
        "audio_bytes": audio_path.stat().st_size,
        "duration_s": probe_duration_seconds(str(audio_path)),
    }


def build_segment_docs(audio_path: Path, vtt_path: Path) -> list[dict]:
    filename = audio_path.name
    base_id = safe_id_from_filename(filename)
    created_at = int(audio_path.stat().st_mtime)
    vtt_text = vtt_path.read_text(encoding="utf-8")
    parsed = parse_vtt_segments(vtt_text)

    docs = []
    for i, seg in enumerate(parsed):
        docs.append(
            {
                "id": f"{base_id}_{i:06d}",
                "filename": filename,
                "start_ms": seg["start_ms"],
                "end_ms": seg["end_ms"],
                "text": seg["text"],
                "created_at": created_at,
                "recorded_at": created_at,
            }
        )
    return docs


def rebuild_meili_from_processed() -> dict:
    processed_dir = Path(PROCESSED_DIR)

    summary = {
        "ok": True,
        "files_scanned": 0,
        "file_docs_indexed": 0,
        "segment_docs_indexed": 0,
        "segment_files_skipped": 0,
        "skipped_files": [],
        "errors": [],
    }

    if not processed_dir.exists():
        return {
            "ok": False,
            "error": f"processed directory not found: {processed_dir}",
        }

    audio_files = sorted(
        p
        for p in processed_dir.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    )

    summary["files_scanned"] = len(audio_files)

    # Clear existing docs first
    try:
        r1 = _meili_request(
            "DELETE", f"/indexes/{INDEX_TRANSCRIPTS}/documents", timeout=30
        )
        if r1.status_code not in (200, 202, 204):
            r1.raise_for_status()

        r2 = _meili_request(
            "DELETE", f"/indexes/{INDEX_SEGMENTS}/documents", timeout=30
        )
        if r2.status_code not in (200, 202, 204):
            r2.raise_for_status()
    except Exception as e:
        return {
            "ok": False,
            "error": f"failed clearing Meili indexes: {e}",
        }

    file_docs = []
    segment_docs = []

    for audio_path in audio_files:
        txt_path = processed_dir / f"{audio_path.stem}.txt"
        vtt_path = processed_dir / f"{audio_path.stem}.vtt"

        if not txt_path.exists():
            summary["skipped_files"].append(
                {
                    "filename": audio_path.name,
                    "reason": "missing txt",
                }
            )
            continue

        try:
            file_docs.append(build_file_doc(audio_path, txt_path))
        except Exception as e:
            summary["errors"].append(
                {
                    "filename": audio_path.name,
                    "stage": "file_doc",
                    "error": str(e),
                }
            )
            continue

        if vtt_path.exists():
            try:
                docs = build_segment_docs(audio_path, vtt_path)
                segment_docs.extend(docs)
            except Exception as e:
                summary["errors"].append(
                    {
                        "filename": audio_path.name,
                        "stage": "segment_docs",
                        "error": str(e),
                    }
                )
        else:
            summary["segment_files_skipped"] += 1

    try:
        if file_docs:
            r = _meili_request(
                "POST",
                f"/indexes/{INDEX_TRANSCRIPTS}/documents",
                json_body=file_docs,
                timeout=60,
            )
            r.raise_for_status()
            summary["file_docs_indexed"] = len(file_docs)

        if segment_docs:
            r = _meili_request(
                "POST",
                f"/indexes/{INDEX_SEGMENTS}/documents",
                json_body=segment_docs,
                timeout=120,
            )
            r.raise_for_status()
            summary["segment_docs_indexed"] = len(segment_docs)

    except Exception as e:
        return {
            "ok": False,
            "error": f"failed indexing rebuilt documents: {e}",
            "partial_summary": summary,
        }

    return summary


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
        desired_transcripts = {"filename", "created_at", "recorded_at"}

        def ensure_filterables(index_uid: str, desired: set[str]):
            r = _meili_request(
                "GET", f"/indexes/{index_uid}/settings/filterable-attributes"
            )
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
            json_body=["created_at", "start_ms"],
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
_REINDEX_LOCK_PATH = "/tmp/strixnote_reindex.lock"

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

    # Disk space safeguard
    if not has_enough_disk(INCOMING_DIR, MIN_FREE_BYTES):
        free_b = get_free_bytes(INCOMING_DIR)
        return (
            jsonify(
                {
                    "error": "server low disk space; upload refused",
                    "free_bytes": free_b,
                    "min_free_bytes": MIN_FREE_BYTES,
                }
            ),
            507,
        )

    # Request-size safeguard (best-effort; relies on client/NGINX sending Content-Length)
    cl = request.content_length
    if cl is not None and cl > MAX_UPLOAD_BYTES:
        return (
            jsonify(
                {
                    "error": "request too large",
                    "content_length": cl,
                    "max_upload_bytes": MAX_UPLOAD_BYTES,
                }
            ),
            413,
        )

    if "files" not in request.files:
        return jsonify({"error": "missing files field"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files"}), 400

    merge_uploads = str(request.form.get("merge_uploads", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    saved = []
    rejected = []

    if merge_uploads:
        temp_paths = []
        list_path = None

        try:
            for i, f in enumerate(files, start=1):
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

                try:
                    f.stream.seek(0, os.SEEK_END)
                    size = f.stream.tell()
                    f.stream.seek(0)
                except Exception:
                    size = None

                if size is not None and size > MAX_UPLOAD_BYTES:
                    rejected.append(
                        {
                            "filename": orig,
                            "reason": f"file too large ({size} bytes > {MAX_UPLOAD_BYTES} bytes)",
                        }
                    )
                    continue

                temp_name = f"merge_src_{int(time.time() * 1000)}_{i:03d}{ext}"
                temp_path = Path("/tmp") / temp_name
                f.save(str(temp_path))

                final_size = temp_path.stat().st_size
                if final_size > MAX_UPLOAD_BYTES:
                    temp_path.unlink(missing_ok=True)
                    rejected.append(
                        {
                            "filename": orig,
                            "reason": f"file too large ({final_size} bytes > {MAX_UPLOAD_BYTES} bytes)",
                        }
                    )
                    continue

                temp_paths.append(temp_path)

            if len(temp_paths) < 2:
                return jsonify(
                    {
                        "saved": [],
                        "rejected": rejected + [{"filename": "", "reason": "need at least two valid files to merge"}],
                    }
                ), 400

            merged_name = f"merged_{int(time.time() * 1000)}.wav"
            dest = Path(INCOMING_DIR) / merged_name

            while dest.exists() or (Path(PROCESSED_DIR) / merged_name).exists():
                merged_name = f"merged_{int(time.time() * 1000)}_{os.getpid()}.wav"
                dest = Path(INCOMING_DIR) / merged_name

            list_path = Path("/tmp") / f"merge_list_{int(time.time() * 1000)}.txt"
            with open(list_path, "w", encoding="utf-8") as lf:
                for p in temp_paths:
                    escaped = str(p).replace("'", "'\\''")
                    lf.write(f"file '{escaped}'\n")

            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(dest),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )

            final_size = dest.stat().st_size
            if final_size > MAX_UPLOAD_BYTES:
                dest.unlink(missing_ok=True)
                return jsonify(
                    {
                        "error": f"merged file too large ({final_size} bytes > {MAX_UPLOAD_BYTES} bytes)"
                    }
                ), 413

            saved.append({"filename": merged_name, "bytes": final_size})
            return jsonify({"saved": saved, "rejected": rejected})

        except subprocess.CalledProcessError as e:
            return jsonify(
                {
                    "error": "merge failed",
                    "details": (e.stderr or str(e))[:800],
                }
            ), 500

        except Exception as e:
            return jsonify({"error": f"merge failed: {str(e)}"}), 500

        finally:
            for p in temp_paths:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

            if list_path is not None:
                try:
                    list_path.unlink(missing_ok=True)
                except Exception:
                    pass

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

        # File size safeguard
        try:
            f.stream.seek(0, os.SEEK_END)
            size = f.stream.tell()
            f.stream.seek(0)
        except Exception:
            size = None

        if size is not None and size > MAX_UPLOAD_BYTES:
            rejected.append(
                {
                    "filename": orig,
                    "reason": f"file too large ({size} bytes > {MAX_UPLOAD_BYTES} bytes)",
                }
            )
            continue

        dest = Path(INCOMING_DIR) / orig

        # Hard rule: do not overwrite existing files
        if dest.exists():
            rejected.append({"filename": orig, "reason": "already exists"})
            continue

        # Stream to disk
        f.save(str(dest))

        # Final size check (protect against missing Content-Length)
        final_size = dest.stat().st_size
        if final_size > MAX_UPLOAD_BYTES:
            dest.unlink(missing_ok=True)
            rejected.append(
                {
                    "filename": orig,
                    "reason": f"file too large ({final_size} bytes > {MAX_UPLOAD_BYTES} bytes)",
                }
            )
            continue

        saved.append({"filename": orig, "bytes": final_size})

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
        resp.headers["Content-Type"] = r.headers.get("Content-Type", "application/json")
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

    progress = read_progress(filename)

    if progress:
        state = progress.get("state", "processing")
    elif processed_audio.exists() and processed_txt.exists():
        state = "done"
    elif processing_path.exists():
        state = "processing"
    elif incoming_path.exists():
        state = "queued"
    else:
        state = "missing"
    # Disk space info (best-effort)
    try:
        incoming_free_b = get_free_bytes(INCOMING_DIR)
    except Exception:
        incoming_free_b = None

    try:
        processed_free_b = get_free_bytes(PROCESSED_DIR)
    except Exception:
        processed_free_b = None

    return jsonify(
        {
            "ok": True,
            "state": state,
            "filename": filename,
            "base": base,
            "progress": progress,
            "disk": {
                "incoming_free_bytes": incoming_free_b,
                "processed_free_bytes": processed_free_b,
                "min_free_bytes": MIN_FREE_BYTES,
            },
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
        Path(INCOMING_DIR) / ".processing" / filename,
        Path(PROCESSED_DIR) / filename,
        Path(PROCESSED_DIR) / f"{base}.txt",
        Path(PROCESSED_DIR) / f"{base}.srt", 
        Path(PROCESSED_DIR) / f"{base}.vtt",
        Path(PROCESSED_DIR) / f"{base}.words.json",
        progress_path_for(filename),
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

@app.post("/edit-segment")
def edit_segment():
    data = request.get_json(silent=True) or {}

    filename = sanitize_filename(data.get("filename", ""))
    start_sec = data.get("startSec")
    new_text = sanitize_segment_text(data.get("text", ""))

    if not filename:
        return jsonify({"error": "missing filename"}), 400

    try:
        start_ms = int(round(float(start_sec) * 1000))
    except Exception:
        return jsonify({"error": "invalid startSec"}), 400

    if not new_text:
        return jsonify({"error": "empty text"}), 400

    base = Path(filename).stem
    audio_path = Path(PROCESSED_DIR) / filename
    vtt_path = Path(PROCESSED_DIR) / f"{base}.vtt"
    srt_path = Path(PROCESSED_DIR) / f"{base}.srt"
    txt_path = Path(PROCESSED_DIR) / f"{base}.txt"

    if not vtt_path.exists():
        return jsonify({"error": f"missing transcript: {vtt_path.name}"}), 404

    try:
        vtt_text = vtt_path.read_text(encoding="utf-8")
        segments = parse_vtt_segments(vtt_text)

        target_idx = None
        for i, seg in enumerate(segments):
            if int(seg.get("start_ms", -1)) == start_ms:
                target_idx = i
                break

        if target_idx is None:
            return jsonify({"error": "segment not found"}), 404

        segments[target_idx]["text"] = new_text

        write_vtt_segments(vtt_path, segments)
        write_srt_segments(srt_path, segments)
        write_txt_from_segments(txt_path, segments)

        meili = {"updated": False}

        if MEILI_MASTER_KEY and audio_path.exists():
            try:
                file_doc = build_file_doc(audio_path, txt_path)
                segment_docs = build_segment_docs(audio_path, vtt_path)

                r1 = requests.post(
                    f"{MEILI_URL}/indexes/{INDEX_TRANSCRIPTS}/documents",
                    headers={**meili_headers(), "Content-Type": "application/json"},
                    json=[file_doc],
                    timeout=10,
                )
                r1.raise_for_status()

                r2 = requests.post(
                    f"{MEILI_URL}/indexes/{INDEX_SEGMENTS}/documents",
                    headers={**meili_headers(), "Content-Type": "application/json"},
                    json=segment_docs,
                    timeout=10,
                )
                r2.raise_for_status()

                meili = {
                    "updated": True,
                    "transcripts": r1.json() if r1.content else {},
                    "segments": r2.json() if r2.content else {},
                }
            except Exception as e:
                meili = {
                    "updated": False,
                    "error": str(e),
                }

        return jsonify({
            "ok": True,
            "filename": filename,
            "startSec": start_ms / 1000.0,
            "text": new_text,
            "meili": meili,
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/clip")
def clip_audio():
    try:
        data = request.get_json(force=True)
        filename = data.get("filename")
        ranges = data.get("ranges") or []
        mode = data.get("mode", "download")

        if not filename or not ranges:
            return jsonify({"ok": False, "error": "Missing filename or ranges"}), 400

        input_path = os.path.join(PROCESSED_DIR, filename)
        if not os.path.exists(input_path):
            return jsonify({"ok": False, "error": "Source file not found"}), 404

        # Build ffmpeg trim filters
        filter_parts = []
        concat_inputs = []
        for i, r in enumerate(ranges):
            start = float(r.get("startSec", 0))
            end = float(r.get("endSec", start + 5))
            filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]")
            concat_inputs.append(f"[a{i}]")

        filter_complex = ";".join(filter_parts)
        filter_complex += f";{''.join(concat_inputs)}concat=n={len(ranges)}:v=0:a=1[out]"

        output_path = make_clip_output_path(filename)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            output_path
        ]

        subprocess.run(cmd, check=True)

        if mode == "download":
            return send_file(output_path, as_attachment=True)
        elif mode == "reimport":
            new_name = f"{Path(filename).stem}_clip_{int(time.time())}.wav"
            incoming_path = os.path.join(INCOMING_DIR, new_name)
            shutil.copy2(output_path, incoming_path)
            return jsonify({"ok": True, "mode": "reimport", "filename": new_name})
        else:
            return jsonify({"ok": False, "error": "Mode not implemented yet"}), 400

    except subprocess.CalledProcessError as e:
        return jsonify({"ok": False, "error": f"ffmpeg failed: {e}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/reindex")
def reindex():
    if not _try_acquire_lock(_REINDEX_LOCK_PATH):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Re-index already in progress.",
                }
            ),
            409,
        )

    try:
        result = rebuild_meili_from_processed()

        if result.get("ok"):
            settings = validate_settings(_deep_merge(DEFAULT_SETTINGS, load_settings()))
            settings.setdefault("meta", {})
            settings["meta"]["last_reindex"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            save_settings(settings)

        status = 200 if result.get("ok") else 500
        return jsonify(result), status
    except Exception as e:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"reindex failed: {e}",
                }
            ),
            500,
        )
    finally:
        try:
            if os.path.exists(_REINDEX_LOCK_PATH):
                os.unlink(_REINDEX_LOCK_PATH)
        except Exception:
            pass

@app.get("/index-health")
def index_health():
    summary = {
        "ok": True,
        "meili": {
            "reachable": False,
        },
        "storage": {
            "processed_audio_files": 0,
        },
        "indexes": {
            "files": {
                "uid": INDEX_TRANSCRIPTS,
                "exists": False,
                "count": None,
            },
            "segments": {
                "uid": INDEX_SEGMENTS,
                "exists": False,
                "count": None,
            },
        },
        "warnings": {
            "files_index_mismatch": False,
        },
        "last_reindex": "",
    }

    try:
        processed_dir = Path(PROCESSED_DIR)
        if processed_dir.exists():
            summary["storage"]["processed_audio_files"] = sum(
                1
                for p in processed_dir.iterdir()
                if p.is_file() and p.suffix.lower() in AUDIO_EXTS
            )

        settings = validate_settings(_deep_merge(DEFAULT_SETTINGS, load_settings()))
        summary["last_reindex"] = settings.get("meta", {}).get("last_reindex", "")
    except Exception as e:
        summary["ok"] = False
        summary["storage"]["error"] = str(e)

    try:
        r = _meili_request("GET", "/health", timeout=5)
        r.raise_for_status()
        summary["meili"]["reachable"] = True
    except Exception as e:
        summary["ok"] = False
        summary["meili"]["error"] = str(e)
        return jsonify(summary), 200

    def inspect_index(uid: str) -> dict:
        info = {
            "uid": uid,
            "exists": False,
            "count": None,
        }

        r = _meili_request("GET", f"/indexes/{uid}", timeout=5)
        if r.status_code == 404:
            return info
        r.raise_for_status()

        info["exists"] = True

        c = _meili_request("GET", f"/indexes/{uid}/stats", timeout=5)
        c.raise_for_status()
        stats = c.json() or {}
        info["count"] = stats.get("numberOfDocuments")

        return info

    try:
        summary["indexes"]["files"] = inspect_index(INDEX_TRANSCRIPTS)
        summary["indexes"]["segments"] = inspect_index(INDEX_SEGMENTS)
        files_count = summary["indexes"]["files"].get("count")
        processed_count = summary["storage"].get("processed_audio_files")

        if files_count is not None and processed_count is not None:
            summary["warnings"]["files_index_mismatch"] = files_count != processed_count
    except Exception as e:
        summary["ok"] = False
        summary["error"] = str(e)

    return jsonify(summary), 200


# -----------------------------
# Settings (persisted JSON)
# -----------------------------

SETTINGS_DIR = os.path.join(DATA_DIR, "config")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

DEFAULT_SETTINGS = {
    "whisper": {
        "language": "",  # "" = auto
        "beam_size": 5,  # int
        "vad_filter": False,  # bool
        "vad_mode": "off",  # off|conservative|balanced|aggressive|noisy
    },
    "meili": {
        "typo_tolerance": True,  # bool
        "synonyms": {},  # dict[str, list[str]]
    },
    "transcript_segmentation_mode": "postprocessed",
    "transcript_postprocess": {
        "punctuation": ".?!",
        "ignore_abbreviations": [
            "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.", "St.", "vs.", "etc."
        ],
        "max_segment_seconds": 30,
        "pause_split_enabled": False,
        "pause_threshold": 0.8,
    },
    "meta": {
        "last_reindex": "",
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

    # whisper.vad_mode: one of the supported preset names
    vad_mode = str(w.get("vad_mode", DEFAULT_SETTINGS["whisper"]["vad_mode"]) or "off").strip().lower()
    if vad_mode not in ("off", "conservative", "balanced", "aggressive", "noisy"):
        vad_mode = "off"
    cleaned["whisper"]["vad_mode"] = vad_mode

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
    seg_mode = raw.get("transcript_segmentation_mode", DEFAULT_SETTINGS["transcript_segmentation_mode"])
    if seg_mode not in ("whisper", "postprocessed"):
        seg_mode = DEFAULT_SETTINGS["transcript_segmentation_mode"]
    cleaned["transcript_segmentation_mode"] = seg_mode

    tp = raw.get("transcript_postprocess") or {}

    punctuation = tp.get("punctuation", DEFAULT_SETTINGS["transcript_postprocess"]["punctuation"])
    if punctuation is None:
        punctuation = DEFAULT_SETTINGS["transcript_postprocess"]["punctuation"]
    if not isinstance(punctuation, str):
        punctuation = str(punctuation)
    punctuation = punctuation.strip()
    cleaned["transcript_postprocess"]["punctuation"] = punctuation

    ignore = tp.get("ignore_abbreviations", DEFAULT_SETTINGS["transcript_postprocess"]["ignore_abbreviations"])
    if isinstance(ignore, str):
        ignore = [x.strip() for x in ignore.split(",")]
    if not isinstance(ignore, (list, tuple)):
        ignore = DEFAULT_SETTINGS["transcript_postprocess"]["ignore_abbreviations"]
    ignore_out = []
    for item in ignore:
        if item is None:
            continue
        s = item if isinstance(item, str) else str(item)
        s = s.strip()
        if s and s not in ignore_out:
            ignore_out.append(s)
    cleaned["transcript_postprocess"]["ignore_abbreviations"] = ignore_out

    max_sec = tp.get("max_segment_seconds", DEFAULT_SETTINGS["transcript_postprocess"]["max_segment_seconds"])
    try:
        max_sec = int(max_sec)
    except Exception:
        max_sec = DEFAULT_SETTINGS["transcript_postprocess"]["max_segment_seconds"]
    if max_sec < 4:
        max_sec = 4
    if max_sec > 60:
        max_sec = 60
    cleaned["transcript_postprocess"]["max_segment_seconds"] = max_sec

    pause_split_enabled = tp.get("pause_split_enabled", DEFAULT_SETTINGS["transcript_postprocess"]["pause_split_enabled"])
    cleaned["transcript_postprocess"]["pause_split_enabled"] = _coerce_bool(
        pause_split_enabled,
        DEFAULT_SETTINGS["transcript_postprocess"]["pause_split_enabled"],
    )

    pause_threshold = tp.get("pause_threshold", DEFAULT_SETTINGS["transcript_postprocess"]["pause_threshold"])
    try:
        pause_threshold = float(pause_threshold)
    except Exception:
        pause_threshold = DEFAULT_SETTINGS["transcript_postprocess"]["pause_threshold"]
    if pause_threshold < 0.2:
        pause_threshold = 0.2
    if pause_threshold > 3.0:
        pause_threshold = 3.0
    cleaned["transcript_postprocess"]["pause_threshold"] = pause_threshold    

    # meta.last_reindex: string timestamp
    meta = raw.get("meta") or {}
    last_reindex = meta.get("last_reindex", DEFAULT_SETTINGS["meta"]["last_reindex"])
    if last_reindex is None:
        last_reindex = ""
    if not isinstance(last_reindex, str):
        last_reindex = str(last_reindex)
    cleaned["meta"]["last_reindex"] = last_reindex.strip()

    return cleaned

def save_settings(settings: dict) -> None:
    import json

    os.makedirs(SETTINGS_DIR, exist_ok=True)
    tmp = SETTINGS_PATH + ".tmp"
    payload = json.dumps(settings, indent=2, sort_keys=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload + "\n")
    os.replace(tmp, SETTINGS_PATH)


def apply_meili_settings(meili_cfg: dict) -> dict:
    """
    Best-effort: apply Meili settings to both indexes.
    Returns a summary dict; does not raise.
    """
    if not MEILI_MASTER_KEY:
        return {"ok": False, "applied": False, "skipped": "MEILI_MASTER_KEY not set"}

    meili_cfg = meili_cfg or {}
    typo_enabled = bool(meili_cfg.get("typo_tolerance", True))
    synonyms = (
        meili_cfg.get("synonyms") if isinstance(meili_cfg.get("synonyms"), dict) else {}
    )

    payload = {
        "typoTolerance": {"enabled": typo_enabled},
        "synonyms": synonyms,
    }

    results = {}
    applied_all = True

    for idx in (INDEX_TRANSCRIPTS, INDEX_SEGMENTS):
        try:
            r = _meili_request(
                "PATCH", f"/indexes/{idx}/settings", json_body=payload, timeout=10
            )
            r.raise_for_status()
            j = r.json() if r.content else {}
            results[idx] = j

            # If we got a task id, try to poll briefly so we can surface failures
            task_uid = None
            if isinstance(j, dict):
                task_uid = j.get("taskUid") or j.get("uid")
            if task_uid is not None:
                results[f"{idx}_task"] = wait_meili_task(task_uid)

        except Exception as e:
            applied_all = False
            results[idx] = {"error": str(e)}

    return {
        "ok": applied_all,
        "applied": applied_all,
        "payload": payload,
        "results": results,
    }

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
    raw = (
        body.get("settings") if isinstance(body, dict) and "settings" in body else body
    )
    if not isinstance(raw, dict):
        return jsonify({"ok": False, "error": "settings must be an object"}), 400

    cleaned = validate_settings(raw)
    try:
        save_settings(cleaned)
    except Exception as e:
        return jsonify({"ok": False, "error": f"failed to save settings: {e}"}), 500

    meili_apply = apply_meili_settings(cleaned.get("meili") or {})

    return jsonify({"ok": True, "settings": cleaned, "meili": meili_apply})
