import json
import logging
from pathlib import Path

GOOGLE_ID_MANIFEST_FILENAME = ".gp-dl-google-ids.json"


def _manifest_path(album_dir: Path) -> Path:
    return album_dir / GOOGLE_ID_MANIFEST_FILENAME


def _load_google_id_manifest(album_dir: Path) -> dict[str, str]:
    path = _manifest_path(album_dir)
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as manifest_file:
            data = json.load(manifest_file)
    except (OSError, json.JSONDecodeError) as e:
        logging.debug(f"Could not read Google ID manifest {path}: {e}")
        return {}

    entries = data.get("google_ids", data) if isinstance(data, dict) else {}
    if not isinstance(entries, dict):
        return {}

    manifest: dict[str, str] = {}
    for google_id, filename in entries.items():
        google_id_key = str(google_id)
        if isinstance(filename, str):
            manifest[google_id_key] = str(filename)
        elif isinstance(filename, list) and filename:
            manifest[google_id_key] = str(filename[0])
    return manifest


def _save_google_id_manifest(album_dir: Path, manifest: dict[str, str]) -> None:
    path = _manifest_path(album_dir)
    try:
        with open(path, "w", encoding="utf-8") as manifest_file:
            json.dump({"google_ids": manifest}, manifest_file, indent=2, sort_keys=True)
            manifest_file.write("\n")
    except OSError as e:
        logging.debug(f"Could not write Google ID manifest {path}: {e}")
