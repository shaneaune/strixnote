import os
import time
import shutil
import requests
import re
import json
import subprocess
from faster_whisper import WhisperModel

IN_DIR = "/data/incoming"
PROCESSING_DIR = "/data/incoming/.processing"
OUT_DIR = "/data/processed"
DONE_DIR = "/data/processed"

MEILI_URL = "http://meilisearch:7700"
MEILI_MASTER_KEY = os.environ.get("MEILI_MASTER_KEY", "")

FILE_INDEX_NAME = "transcripts"
SEG_INDEX_NAME = "segments"

MODEL_NAME = os.environ.get("WHISPER_MODEL", "medium.en")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE", "int8")

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".mp4", ".webm"}


def meili_headers():
    return {"Authorization": f"Bearer {MEILI_MASTER_KEY}"} if MEILI_MASTER_KEY else {}


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
        import subprocess
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
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
    text = re.sub(r'(?<!\d)([.!?])(\s+)', r'\1\n', text)
    # Also handle punctuation at end-of-string
    text = re.sub(r'(?<!\d)([.!?])$', r'\1\n', text)
    # Normalize: collapse excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + "\n"

def main():
    os.makedirs(PROCESSING_DIR, exist_ok=True)
    os.makedirs(IN_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(DONE_DIR, exist_ok=True)

    model = WhisperModel(
        MODEL_NAME,
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
        download_root=os.environ.get("WHISPER_MODEL_DIR", "/models"),
    )
    print(f"Watching {IN_DIR} model={MODEL_NAME} device={DEVICE} compute={COMPUTE_TYPE}", flush=True)

    while True:
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

            try:
                processing_path = os.path.join(PROCESSING_DIR, name)
                shutil.move(path, processing_path)
                print(f"Transcribing: {name}", flush=True)
                segments, _info = model.transcribe(processing_path, language="en", beam_size=5)
                seg_list = list(segments)

                full_text = " ".join(s.text.strip() for s in seg_list).strip()

                # Write TXT (human-readable lines)
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(format_txt_for_download(full_text))

                # Write SRT + VTT (VTT is for HTML5 track)
                write_srt(seg_list, srt_path)
                write_vtt(seg_list, vtt_path)

                now = int(time.time())

                audio_bytes = os.path.getsize(processing_path)
                duration_s = probe_duration_seconds(processing_path)

                # ---- FILE-LEVEL DOCUMENT (existing behavior preserved) ----
                file_doc = {
                    "id": safe_base,
                    "filename": name,
                    "text": full_text,
                    "created_at": now,
                    "audio_bytes": audio_bytes,
                    "duration_s": duration_s,
                }

                requests.post(
                    f"{MEILI_URL}/indexes/{FILE_INDEX_NAME}/documents",
                    headers=meili_headers(),
                    json=[file_doc],
                    timeout=30,
                ).raise_for_status()

                # ---- SEGMENT-LEVEL DOCUMENTS (new behavior) ----
                segment_docs = []
                for i, seg in enumerate(seg_list):
                    segment_docs.append({
                        "id": f"{safe_base}_{i:06d}",
                        "filename": name,
                        "start_ms": int(seg.start * 1000),
                        "end_ms": int(seg.end * 1000),
                        "text": seg.text.strip(),
                        "created_at": now,
                        "recorded_at": now  # will upgrade to parsed filename later
                    })

                if segment_docs:
                    requests.post(
                        f"{MEILI_URL}/indexes/{SEG_INDEX_NAME}/documents",
                        headers=meili_headers(),
                        json=segment_docs,
                        timeout=60,
                    ).raise_for_status()


                # Move original audio
                shutil.move(processing_path, os.path.join(DONE_DIR, name))

                print(f"Done: {name}", flush=True)

            except Exception as e:
                print(f"ERROR processing {name}: {e}", flush=True)
                try:
                    shutil.move(processing_path, os.path.join(DONE_DIR, name))
                except Exception:
                    pass

        time.sleep(2)


if __name__ == "__main__":
    main()
