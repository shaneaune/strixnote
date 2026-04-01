import json
import os
import re
import shutil
import subprocess
import time
import signal
import sys
import contextlib

import requests
from faster_whisper import WhisperModel

IN_DIR = "/data/incoming"
PROCESSING_DIR = "/data/incoming/.processing"
OUT_DIR = "/data/processed"
DONE_DIR = "/data/processed"
FAILED_DIR = "/data/processed/_failed"

MEILI_URL = "http://meilisearch:7700"
MEILI_MASTER_KEY = os.environ.get("MEILI_MASTER_KEY", "")

FILE_INDEX_NAME = "transcripts"
SEG_INDEX_NAME = "segments"

MODEL_NAME = os.environ.get("WHISPER_MODEL", "medium.en")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE", "int8")

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".mp4", ".webm"}

SETTINGS_PATH = "/data/config/settings.json"
STATUS_DIR = "/data/status"

MIN_FREE_BYTES = int(os.environ.get("MIN_FREE_GB", "1")) * 1024 * 1024 * 1024  # default 1 GiB


def get_free_bytes(path: str) -> int:
    # Uses the filesystem backing `path`
    return shutil.disk_usage(path).free


def wait_for_disk_space(path: str, min_free_bytes: int) -> bool:
    """
    Returns True if there is enough free space.
    If not enough space, logs and returns False (caller should pause/continue).
    """
    free_b = get_free_bytes(path)
    if free_b >= min_free_bytes:
        return True

    free_mb = free_b // (1024 * 1024)
    need_mb = min_free_bytes // (1024 * 1024)
    print(
        f"Low disk space: {free_mb} MB free, need at least {need_mb} MB. Pausing new work.",
        flush=True,
    )
    return False

def progress_filename_for(audio_filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", audio_filename).strip("._")
    if not safe:
        safe = "file"
    return f"{safe}.progress.json"


def progress_path_for(audio_filename: str) -> str:
    return os.path.join(STATUS_DIR, progress_filename_for(audio_filename))


def write_progress(
    audio_filename: str,
    state: str,
    progress_pct: int,
    message: str,
    audio_duration_s: float = 0.0,
    processed_until_s: float = 0.0,
    started_at: int | None = None,
    eta_seconds: int | None = None,
    error: str = "",
) -> None:
    os.makedirs(STATUS_DIR, exist_ok=True)

    now = int(time.time())
    payload = {
        "filename": audio_filename,
        "state": state,
        "progress_pct": max(0, min(100, int(progress_pct))),
        "message": message,
        "audio_duration_s": float(audio_duration_s or 0.0),
        "processed_until_s": float(processed_until_s or 0.0),
        "started_at": int(started_at or now),
        "updated_at": now,
        "eta_seconds": int(eta_seconds) if eta_seconds is not None else None,
        "error": error or "",
    }

    tmp_path = progress_path_for(audio_filename) + ".tmp"
    final_path = progress_path_for(audio_filename)

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True)

    os.replace(tmp_path, final_path)


def remove_progress(audio_filename: str) -> None:
    try:
        os.unlink(progress_path_for(audio_filename))
    except FileNotFoundError:
        pass
    except Exception:
        pass

class WhisperProgressCapture:
    def __init__(self, audio_filename: str, audio_duration_s: float, started_at: int):
        self.audio_filename = audio_filename
        self.audio_duration_s = float(audio_duration_s or 0.0)
        self.started_at = int(started_at)
        self._buffer = ""
        self._last_write_ts = 0.0

    def write(self, text: str) -> int:
        if not text:
            return 0

        self._buffer += str(text)

        parts = re.split(r"[\r\n]+", self._buffer)
        self._buffer = parts.pop() if parts else ""

        for part in parts:
            self._handle_line(part)

        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._handle_line(self._buffer)
            self._buffer = ""

    def _handle_line(self, line: str) -> None:
        line = str(line or "").strip()
        if not line:
            return

        m = re.search(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", line)
        if not m:
            return

        try:
            processed_until_s = float(m.group(1))
            total_s = float(m.group(2))
        except Exception:
            return

        duration_s = self.audio_duration_s if self.audio_duration_s > 0 else total_s
        if duration_s <= 0:
            return

        progress_pct = min(99, max(1, int((processed_until_s / duration_s) * 100)))

        now_ts = time.time()
        if now_ts - self._last_write_ts < 0.5:
            return

        eta_seconds = None
        elapsed_s = max(0.001, now_ts - float(self.started_at))
        if processed_until_s > 0 and duration_s > processed_until_s:
            rate = processed_until_s / elapsed_s
            if rate > 0:
                eta_seconds = int((duration_s - processed_until_s) / rate)

        write_progress(
            audio_filename=self.audio_filename,
            state="transcribing",
            progress_pct=progress_pct,
            message=f"Transcribing... {progress_pct}%",
            audio_duration_s=duration_s,
            processed_until_s=processed_until_s,
            started_at=self.started_at,
            eta_seconds=eta_seconds,
        )
        self._last_write_ts = now_ts


def load_runtime_settings() -> dict:
    """
    Load settings written by the Settings page.
    Returns dict with defaults if file missing/bad.
    """
    defaults = {
        "whisper": {"language": "", "beam_size": 5, "vad_filter": False},
        "meili": {"typo_tolerance": True, "synonyms": {}},
    }

    try:
        if not os.path.exists(SETTINGS_PATH):
            return defaults

        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}

        w = data.get("whisper") or {}
        m = data.get("meili") or {}

        # Normalize / clamp
        lang = str(w.get("language") or "").strip()
        try:
            beam = int(w.get("beam_size", 5))
        except Exception:
            beam = 5
        beam = max(1, min(10, beam))

        vad = bool(w.get("vad_filter", False))

        # Keep meili in case we want it later in worker (not used yet)
        tt = bool(m.get("typo_tolerance", True))
        syn = m.get("synonyms") if isinstance(m.get("synonyms"), dict) else {}

        return {
            "whisper": {"language": lang, "beam_size": beam, "vad_filter": vad},
            "meili": {"typo_tolerance": tt, "synonyms": syn},
        }
    except Exception as e:
        print(f"Settings load failed, using defaults: {e}", flush=True)
        return defaults
_LAST_SETTINGS_MTIME = None
_LAST_SETTINGS_LOAD = 0.0
_LAST_WHISPER_SETTINGS = {"language": "", "beam_size": 5, "vad_filter": False}
_SETTINGS_CHECK_INTERVAL_S = 2.0


def get_whisper_settings() -> dict:
    """
    Cached runtime Whisper settings.
    Reloads settings.json only when it changes (mtime), with a small time-based throttle.
    Applies to NEW files only (each file reads the latest cached value).
    """
    global _LAST_SETTINGS_MTIME, _LAST_SETTINGS_LOAD, _LAST_WHISPER_SETTINGS

    now = time.time()
    if now - _LAST_SETTINGS_LOAD < _SETTINGS_CHECK_INTERVAL_S:
        return _LAST_WHISPER_SETTINGS

    _LAST_SETTINGS_LOAD = now

    try:
        mtime = os.stat(SETTINGS_PATH).st_mtime
    except FileNotFoundError:
        _LAST_SETTINGS_MTIME = None
        _LAST_WHISPER_SETTINGS = load_runtime_settings()["whisper"]
        return _LAST_WHISPER_SETTINGS
    except Exception:
        # If stat fails for any reason, fall back to safe defaults loader
        _LAST_WHISPER_SETTINGS = load_runtime_settings()["whisper"]
        return _LAST_WHISPER_SETTINGS

    if _LAST_SETTINGS_MTIME != mtime:
        _LAST_SETTINGS_MTIME = mtime
        _LAST_WHISPER_SETTINGS = load_runtime_settings()["whisper"]

    return _LAST_WHISPER_SETTINGS

def meili_request(method: str, path: str, json_body=None, timeout=10):
    url = f"{MEILI_URL}{path}"
    headers = {**meili_headers()}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    return requests.request(method, url, headers=headers, json=json_body, timeout=timeout)


def ensure_meili_ready():
    """
    Verify Meili is reachable and required indexes exist.
    Create indexes if missing (id primary key).
    """
    # Health
    r = meili_request("GET", "/health", timeout=5)
    r.raise_for_status()

    # Ensure indexes exist
    for uid in (FILE_INDEX_NAME, SEG_INDEX_NAME):
        r = meili_request("GET", f"/indexes/{uid}", timeout=5)
        if r.status_code == 404:
            cr = meili_request(
                "POST",
                "/indexes",
                json_body={"uid": uid, "primaryKey": "id"},
                timeout=10,
            )
            # 200/202 ok; 409 if racing is fine
            if cr.status_code not in (200, 202, 409):
                cr.raise_for_status()
        else:
            r.raise_for_status()

def meili_headers():
    return {"Authorization": f"Bearer {MEILI_MASTER_KEY}"} if MEILI_MASTER_KEY else {}


def meili_post_with_retry(path: str, json_body, timeout=30, retries=5):
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            r = meili_request("POST", path, json_body=json_body, timeout=timeout)

            # If Meili returns an HTTP error, include status + body snippet for debugging.
            if r.status_code >= 400:
                body_snip = ""
                try:
                    body_snip = (r.text or "").strip().replace("\n", " ")[:300]
                except Exception:
                    body_snip = "<unable to read body>"

                hint = ""
                if r.status_code in (401, 403):
                    hint = " (check MEILI_MASTER_KEY / auth)"

                raise RuntimeError(f"HTTP {r.status_code}{hint}: {body_snip}")

            return

        except Exception as e:
            last_err = e
            print(
                f"Meili POST failed (attempt {attempt}/{retries}) path={path}: {e}",
                flush=True,
            )

            # Exponential backoff, capped (1.0s, 2.0s, 4.0s, 8.0s, 10.0s...)
            sleep_s = min(10.0, 1.0 * (2 ** (attempt - 1)))
            time.sleep(sleep_s)

    # After retries exhausted, raise so caller can handle (worker already catches and continues)
    raise last_err

def safe_id(s: str) -> str:
    # Meilisearch id must be only [A-Za-z0-9_-]
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "doc"


def is_stable(path: str, seconds: int = 5) -> bool:
    s1 = os.path.getsize(path)
    time.sleep(seconds)
    s2 = os.path.getsize(path)
    return s1 == s2


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


def write_srt(segments, out_path):
    def ts(t):
        h = int(t // 3600)
        t -= h * 3600
        m = int(t // 60)
        t -= m * 60
        s = int(t)
        ms = int(round((t - s) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(out_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n{ts(seg.start)} --> {ts(seg.end)}\n{seg.text.strip()}\n\n")


def write_vtt(segments, out_path):
    def ts(t):
        h = int(t // 3600)
        t -= h * 3600
        m = int(t // 60)
        t -= m * 60
        s = int(t)
        ms = int(round((t - s) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{ts(seg.start)} --> {ts(seg.end)}\n{seg.text.strip()}\n\n")


def format_txt_for_download(text: str) -> str:
    # Insert a newline after sentence-ending punctuation.
    # Avoid breaking decimal numbers like 3.14 by requiring a following space/end.
    text = re.sub(r"(?<!\d)([.!?])(\s+)", r"\1\n", text)
    # Also handle punctuation at end-of-string
    text = re.sub(r"(?<!\d)([.!?])$", r"\1\n", text)
    # Normalize: collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"

_shutdown_requested = False


def _handle_shutdown(signum, frame):
    global _shutdown_requested
    print("Shutdown signal received. Finishing current work...", flush=True)
    _shutdown_requested = True


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)

def main():
    os.makedirs(PROCESSING_DIR, exist_ok=True)
    os.makedirs(IN_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(DONE_DIR, exist_ok=True)
    os.makedirs(FAILED_DIR, exist_ok=True)

    model = WhisperModel(
        MODEL_NAME,
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
        download_root=os.environ.get("WHISPER_MODEL_DIR", "/models"),
    )

    try:
        ensure_meili_ready()
        print("Meili ready.", flush=True)
    except Exception as e:
        print(f"Meili not ready; refusing to start: {e}", flush=True)
        return

    print(
        f"Watching {IN_DIR} model={MODEL_NAME} device={DEVICE} compute={COMPUTE_TYPE}",
        flush=True,
    )

    while not _shutdown_requested:
        for name in sorted(os.listdir(IN_DIR)):
            path = os.path.join(IN_DIR, name)

            if not os.path.isfile(path) or name.startswith("."):
                continue

            base, ext = os.path.splitext(name)
            if ext.lower() not in AUDIO_EXTS:
                continue

            safe_base = safe_id(base)

            txt_path = os.path.join(OUT_DIR, base + ".txt")
            srt_path = os.path.join(OUT_DIR, base + ".srt")
            vtt_path = os.path.join(OUT_DIR, base + ".vtt")

            if os.path.exists(txt_path) and os.path.exists(srt_path) and os.path.exists(vtt_path):
                # already processed
                continue

            try:
                if not is_stable(path, seconds=5):
                    continue
            except FileNotFoundError:
                continue

            processing_path = None
            try:
                # Disk space safeguard
                if not wait_for_disk_space(OUT_DIR, MIN_FREE_BYTES):
                    time.sleep(5)
                    continue
                processing_path = os.path.join(PROCESSING_DIR, name)
                shutil.move(path, processing_path)
                print(f"Transcribing: {name}", flush=True)

                started_at = int(time.time())
                audio_duration_s = probe_duration_seconds(processing_path)

                write_progress(
                    audio_filename=name,
                    state="transcribing",
                    progress_pct=0,
                    message="Starting transcription...",
                    audio_duration_s=audio_duration_s,
                    processed_until_s=0.0,
                    started_at=started_at,
                )

                ws = get_whisper_settings()
                lang = ws["language"]
                beam = ws["beam_size"]
                vad = ws["vad_filter"]
                vad_mode = ws.get("vad_mode", "off")
                print(
                    f"Whisper settings: language={(lang or 'auto')} beam_size={beam} vad_filter={vad}",
                    flush=True,
                )

                transcribe_kwargs = {"beam_size": beam}
                if lang:
                    transcribe_kwargs["language"] = lang

                progress_capture = WhisperProgressCapture(
                    audio_filename=name,
                    audio_duration_s=audio_duration_s,
                    started_at=started_at,
                )

                vad_params = None

                if vad:
                    if vad_mode == "conservative":
                        vad_params = {"min_silence_duration_ms": 800}
                    elif vad_mode == "balanced":
                        vad_params = {"min_silence_duration_ms": 500}
                    elif vad_mode == "aggressive":
                        vad_params = {"min_silence_duration_ms": 250}
                    elif vad_mode == "noisy":
                        vad_params = {
                            "min_silence_duration_ms": 700,
                            "min_speech_duration_ms": 300,
                        }

                # Some faster-whisper builds support vad_filter; if not, retry without it.
                try:
                    with contextlib.redirect_stderr(progress_capture):
                        if vad_params:
                            segments, _info = model.transcribe(
                                processing_path,
                                vad_filter=vad,
                                vad_parameters=vad_params,
                                log_progress=True,
                                **transcribe_kwargs,
                            )
                        else:
                            segments, _info = model.transcribe(
                                processing_path,
                                vad_filter=vad,
                                log_progress=True,
                                **transcribe_kwargs,
                            )
                except TypeError:
                    with contextlib.redirect_stderr(progress_capture):
                        segments, _info = model.transcribe(
                            processing_path,
                            log_progress=True,
                            **transcribe_kwargs,
                        )

                seg_list = []
                next_progress_write = 0.0
                last_processed_s = 0.0

                for seg in segments:
                    seg_list.append(seg)

                    last_processed_s = float(getattr(seg, "end", 0.0) or 0.0)

                    now_ts = time.time()
                    if now_ts >= next_progress_write:
                        elapsed_s = max(0.001, now_ts - float(started_at))

                        if last_processed_s > 0:
                            rate = last_processed_s / elapsed_s
                            estimated_processed = min(
                                audio_duration_s,
                                last_processed_s + rate * 0.5,
                            )
                        else:
                            estimated_processed = 0.0

                        if audio_duration_s > 0:
                            progress_pct = min(
                                99,
                                max(1, int((estimated_processed / audio_duration_s) * 100))
                            )
                        else:
                            progress_pct = 0

                        eta_seconds = None
                        if last_processed_s > 0 and audio_duration_s > last_processed_s:
                            rate = last_processed_s / elapsed_s
                            if rate > 0:
                                eta_seconds = int((audio_duration_s - last_processed_s) / rate)

                        write_progress(
                            audio_filename=name,
                            state="transcribing",
                            progress_pct=progress_pct,
                            message="Transcribing...",
                            audio_duration_s=audio_duration_s,
                            processed_until_s=estimated_processed,
                            started_at=started_at,
                            eta_seconds=eta_seconds,
                        )

                        next_progress_write = now_ts + 0.5

                full_text = " ".join(s.text.strip() for s in seg_list).strip()

                # Write TXT (human-readable lines)
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(format_txt_for_download(full_text))

                # Write SRT + VTT (VTT is for HTML5 track)
                write_srt(seg_list, srt_path)
                write_vtt(seg_list, vtt_path)

                now = int(time.time())
                write_progress(
                    audio_filename=name,
                    state="indexing",
                    progress_pct=99,
                    message="Indexing transcript...",
                    audio_duration_s=audio_duration_s,
                    processed_until_s=audio_duration_s,
                    started_at=started_at,
                )
                audio_bytes = os.path.getsize(processing_path)
                duration_s = probe_duration_seconds(processing_path)

                # ---- FILE-LEVEL DOCUMENT (existing behavior preserved) ----
                file_doc = {
                    "id": safe_base,
                    "filename": name,
                    "text": full_text,
                    "created_at": now,
                    "recorded_at": now,  # TODO: replace with real media/filename timestamp when available
                    "audio_bytes": audio_bytes,
                    "duration_s": duration_s,
                }

                meili_ok = True

                try:
                    meili_post_with_retry(
                        f"/indexes/{FILE_INDEX_NAME}/documents",
                        [file_doc],
                        timeout=30,
                    )
                except Exception as e:
                    meili_ok = False
                    print(f"WARNING: Meili indexing failed (file doc). Continuing: {e}", flush=True)

                # ---- SEGMENT-LEVEL DOCUMENTS (new behavior) ----
                segment_docs = []
                for i, seg in enumerate(seg_list):
                    segment_docs.append(
                        {
                            "id": f"{safe_base}_{i:06d}",
                            "filename": name,
                            "start_ms": int(seg.start * 1000),
                            "end_ms": int(seg.end * 1000),
                            "text": seg.text.strip(),
                            "created_at": now,
                            "recorded_at": now,  # will upgrade to parsed filename later
                        }
                    )

                if segment_docs and meili_ok:
                    try:
                        meili_post_with_retry(
                            f"/indexes/{SEG_INDEX_NAME}/documents",
                            segment_docs,
                            timeout=60,
                        )
                    except Exception as e:
                        print(
                            f"WARNING: Meili indexing failed (segment docs). Continuing: {e}",
                            flush=True,
                        )
                # Move original audio
                shutil.move(processing_path, os.path.join(DONE_DIR, name))
                processing_path = None

                write_progress(
                    audio_filename=name,
                    state="done",
                    progress_pct=100,
                    message="Processing complete.",
                    audio_duration_s=audio_duration_s,
                    processed_until_s=audio_duration_s,
                    started_at=started_at,
                )

                print(f"Done: {name}", flush=True)

            except Exception as e:
                print(f"ERROR processing {name}: {e}", flush=True)
                try:
                    if processing_path and os.path.exists(processing_path):
                        failed_path = os.path.join(FAILED_DIR, name)

                        if os.path.exists(failed_path):
                            base, ext = os.path.splitext(name)
                            failed_path = os.path.join(
                                FAILED_DIR,
                                f"{base}_{int(time.time())}{ext}"
                            )

                        shutil.move(processing_path, failed_path)

                        error_info_path = failed_path + ".error.json"
                        with open(error_info_path, "w", encoding="utf-8") as f:
                            json.dump(
                                {
                                    "filename": name,
                                    "failed_path": failed_path,
                                    "error": str(e),
                                    "failed_at": int(time.time()),
                                },
                                f,
                                ensure_ascii=True,
                                indent=2,
                            )
                except Exception:
                    pass

        time.sleep(2)

print("Worker exiting cleanly.", flush=True)
if __name__ == "__main__":
    main()