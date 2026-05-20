import logging
import os
import re
from pathlib import Path

from .manifest import (
    GOOGLE_ID_MANIFEST_FILENAME,
    _load_google_id_manifest,
    _save_google_id_manifest,
)
from .parsing import (
    _extract_google_id_from_filename,
    _local_media_descriptors,
    _normalize_filename,
)


def _sanitize_path_component(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned or value


def _is_path_within(child: Path, parent: Path) -> bool:
    try:
        _ = child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _normalize_album_name(value: str) -> str:
    cleaned = _sanitize_path_component(value).casefold()
    return re.sub(r"\s+", " ", cleaned).strip()


def _album_output_dirs(output_path: Path, album_title: str) -> list[Path]:
    candidates = [output_path / album_title]
    sanitized = _sanitize_path_component(album_title)
    if sanitized != album_title:
        candidates.append(output_path / sanitized)

    normalized_title = _normalize_album_name(album_title)
    if output_path.exists():
        try:
            for child in output_path.iterdir():
                if (
                    child.is_dir()
                    and _normalize_album_name(child.name) == normalized_title
                ):
                    candidates.append(child)
        except OSError:
            pass

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            unique_candidates.append(resolved)
            seen.add(resolved)
    return unique_candidates


def _record_google_id_file(
    album_dir: Path, google_id: str, file_path: Path, output_path: Path
) -> None:
    try:
        resolved_file_path = file_path.resolve()
        if not _is_path_within(resolved_file_path, album_dir) or not _is_path_within(
            resolved_file_path, output_path
        ):
            return
        relative_name = resolved_file_path.relative_to(album_dir.resolve()).as_posix()
    except ValueError:
        return

    manifest = _load_google_id_manifest(album_dir)
    manifest[str(google_id)] = relative_name
    _save_google_id_manifest(album_dir, manifest)


def _descriptor_exists(descriptor: str, existing_descriptors: set[str]) -> bool:
    if descriptor in existing_descriptors:
        return True
    orientation, timestamp_key = descriptor.split("|", 1)
    return f"*|{timestamp_key}" in existing_descriptors or any(
        existing_descriptor.endswith(f"|{timestamp_key}")
        for existing_descriptor in existing_descriptors
        if orientation == "*"
    )


def _local_album_google_id_files(
    output_path: Path, album_title: str
) -> tuple[dict[str, list[Path]], list[Path]]:
    album_dirs = _album_output_dirs(output_path, album_title)
    files_by_google_id: dict[str, list[Path]] = {}
    ids_from_manifest: set[str] = set()

    for album_dir in album_dirs:
        if not album_dir.exists() or not album_dir.is_dir():
            continue

        manifest = _load_google_id_manifest(album_dir)
        for google_id, filename in manifest.items():
            google_id_key = google_id.casefold()
            file_path = (album_dir / filename).resolve()
            if not file_path.exists() or not file_path.is_file():
                continue
            if not _is_path_within(file_path, output_path):
                continue
            ids_from_manifest.add(google_id_key)
            files_by_google_id[google_id_key] = [file_path]

    for album_dir in album_dirs:
        if not album_dir.exists() or not album_dir.is_dir():
            continue

        for root, _, files in os.walk(album_dir):
            for filename in files:
                normalized = _normalize_filename(filename)
                extension = os.path.splitext(normalized)[1]
                if not extension:
                    continue
                google_id = _extract_google_id_from_filename(filename)
                if not google_id:
                    continue
                google_id_key = google_id.casefold()
                if google_id_key in ids_from_manifest:
                    continue
                file_path = Path(root) / filename
                if file_path not in files_by_google_id.setdefault(google_id_key, []):
                    files_by_google_id[google_id_key].append(file_path)

    return files_by_google_id, album_dirs


def _existing_album_files(
    output_path: Path, album_title: str
) -> tuple[set[str], set[str], set[str], set[str], list[Path]]:
    album_dirs = _album_output_dirs(output_path, album_title)
    existing_names = set()
    existing_stems = set()
    existing_descriptors = set()
    existing_google_ids = set()

    for album_dir in album_dirs:
        if not album_dir.exists() or not album_dir.is_dir():
            continue
        for root, _, files in os.walk(album_dir):
            for filename in files:
                normalized = _normalize_filename(filename)
                if not normalized:
                    continue
                extension = os.path.splitext(normalized)[1]
                if not extension:
                    continue
                existing_names.add(normalized)
                existing_stems.add(os.path.splitext(normalized)[0])
                existing_descriptors.update(
                    _local_media_descriptors(Path(root) / filename)
                )
                google_id = _extract_google_id_from_filename(filename)
                if google_id:
                    existing_google_ids.add(google_id.casefold())

    return (
        existing_names,
        existing_stems,
        existing_descriptors,
        existing_google_ids,
        album_dirs,
    )


def _local_album_files_without_google_id(
    output_path: Path, album_title: str
) -> list[Path]:
    files_by_google_id, album_dirs = _local_album_google_id_files(
        output_path, album_title
    )
    files_with_google_id = {
        path.resolve() for paths in files_by_google_id.values() for path in paths
    }
    files_without_google_id: list[Path] = []
    seen_paths = set()

    for album_dir in album_dirs:
        if not album_dir.exists() or not album_dir.is_dir():
            continue
        for root, _, files in os.walk(album_dir):
            for filename in files:
                if filename == GOOGLE_ID_MANIFEST_FILENAME:
                    continue
                normalized = _normalize_filename(filename)
                extension = os.path.splitext(normalized)[1]
                if not extension:
                    continue
                if _extract_google_id_from_filename(filename):
                    continue

                file_path = (Path(root) / filename).resolve()
                if file_path in files_with_google_id:
                    continue
                if file_path not in seen_paths:
                    files_without_google_id.append(file_path)
                    seen_paths.add(file_path)

    return files_without_google_id
