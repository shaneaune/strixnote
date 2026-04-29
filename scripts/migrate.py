#!/usr/bin/env python3
import json
from pathlib import Path

DATA_DIR = Path("/data")
PROCESSED_DIR = DATA_DIR / "processed"
CURRENT_SCHEMA_VERSION = 1


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

    if not PROCESSED_DIR.exists():
        print("No processed directory found. Nothing to migrate.")
        return

    checked = 0
    migrated = 0

    for path in PROCESSED_DIR.glob("*.words.json"):
        checked += 1
        if migrate_words_json(path):
            migrated += 1

    print(f"Migration complete. Checked {checked} files, migrated {migrated} files.")


if __name__ == "__main__":
    main()