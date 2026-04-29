#!/usr/bin/env python3
import json
from pathlib import Path

DATA_DIR = Path("/data")
PROCESSED_DIR = DATA_DIR / "processed"
STATUS_DIR = DATA_DIR / "status"
MIGRATION_LOG = STATUS_DIR / "migrations.log"
CURRENT_SCHEMA_VERSION = 1

STATUS_DIR.mkdir(parents=True, exist_ok=True)

def log_message(message: str) -> None:
    with MIGRATION_LOG.open("a", encoding="utf-8") as f:
        f.write(message + "\n")

def migrate_words_json(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        changed = False

        if "schema_version" not in data:
            data["schema_version"] = 0
            changed = True

        if data["schema_version"] < 1:
            data.setdefault("media_info", {})
            data["schema_version"] = 1
            changed = True

        if changed:
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=True, indent=2)

        return changed

    except Exception as e:
        print(f"WARNING: Could not migrate {path}: {e}")
        return False


def main() -> None:
    print("Running StrixNote migrations...")
    log_message("=== Migration run start ===")

    if not PROCESSED_DIR.exists():
        print("No processed directory found. Nothing to migrate.")
        return

    checked = 0
    migrated = 0

    for path in PROCESSED_DIR.glob("*.words.json"):
        checked += 1
        if migrate_words_json(path):
            migrated += 1

    summary = f"Migration complete. Checked {checked} files, migrated {migrated} files."
    print(summary)
    log_message(summary)
    log_message("=== Migration run end ===")

if __name__ == "__main__":
    main()