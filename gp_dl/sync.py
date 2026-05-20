import logging
import shutil
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .browser import find_completed_download_file
from .config import WEB_DRIVER_WAIT
from .google_photos_ui import (
    _collect_album_photo_items,
    _is_motion_photo_page,
    _photo_image_download_url,
    _start_download_with_keyboard_shortcut,
    _start_google_photos_download,
    _wait_for_download_start,
)
from .local_state import (
    _album_output_dirs,
    _is_path_within,
    _local_album_files_without_google_id,
    _local_album_google_id_files,
    _record_google_id_file,
    _sanitize_path_component,
)
from .parsing import _download_response_filename, _item_looks_like_video


def _download_motion_photo_still(
    driver, google_id: str, target_album_dir: Path, output_path: Path
) -> Path | None:
    download_url = _photo_image_download_url(driver)
    if not download_url:
        return None

    try:
        cookie_header = "; ".join(
            f"{cookie['name']}={cookie['value']}" for cookie in driver.get_cookies()
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        if cookie_header:
            headers["Cookie"] = cookie_header
        request = Request(download_url, headers=headers)
        with urlopen(request, timeout=max(WEB_DRIVER_WAIT, 10) * 3) as response:
            filename = _download_response_filename(response)
            if not filename:
                logging.debug(
                    f"Could not determine Google-provided filename for motion photo item {google_id}; refusing to infer a filename or extension from the rendered image URL."
                )
                return None

            target_name = filename
            resolved_target = (target_album_dir / target_name).resolve()
            if not _is_path_within(resolved_target, output_path):
                logging.error(
                    f"Skipping direct still download with unsafe path: {target_name}"
                )
                return None

            temp_target = resolved_target.with_suffix(f"{resolved_target.suffix}.tmp")
            with open(temp_target, "wb") as target_file:
                shutil.copyfileobj(response, target_file)
            if resolved_target.exists():
                resolved_target.unlink()
            temp_target.replace(resolved_target)
            _record_google_id_file(
                target_album_dir, google_id, resolved_target, output_path
            )
            logging.info(f"Saved motion photo still to {resolved_target}")
            return resolved_target
    except Exception as e:
        logging.debug(
            f"Direct still download failed for Google Photos item {google_id}: {e}"
        )
        return None


def _download_individual_album_items(
    driver,
    items: list[dict[str, str]],
    album_title: str,
    output_path: Path,
    temp_dir_path: Path,
) -> tuple[int, int, int]:
    album_dirs = _album_output_dirs(output_path, album_title)
    target_album_dir = next(
        (path for path in album_dirs if path.exists() and path.is_dir()),
        output_path / _sanitize_path_component(album_title),
    )
    target_album_dir.mkdir(parents=True, exist_ok=True)

    downloaded_count = 0
    skipped_count = 0
    failed_count = 0

    for item in items:
        google_id = item["google_id"]
        existing_download_files = (
            set(temp_dir_path.iterdir()) if temp_dir_path.is_dir() else set()
        )

        files_by_google_id, _ = _local_album_google_id_files(output_path, album_title)
        existing_with_id = files_by_google_id.get(google_id.casefold(), [])
        if existing_with_id:
            logging.debug(
                f"Skipping Google Photos item {google_id}; already saved as {existing_with_id[0]}"
            )
            skipped_count += 1
            continue

        logging.info(f"Downloading missing Google Photos item {google_id}")
        driver.get(item["url"])

        if _is_motion_photo_page(driver, timeout=min(WEB_DRIVER_WAIT, 3)):
            if _item_looks_like_video(item):
                logging.debug(
                    f"Google Photos item {google_id} is a video; skipping still-image fallback so the downloaded file extension is preserved."
                )
            else:
                still_path = _download_motion_photo_still(
                    driver, google_id, target_album_dir, output_path
                )
                if still_path:
                    downloaded_count += 1
                    continue
                logging.debug(
                    f"Direct still download did not work for motion photo item {google_id}; falling back to Google Photos download controls."
                )

        download_started = _start_download_with_keyboard_shortcut(
            driver
        ) and _wait_for_download_start(
            temp_dir_path, {p.name for p in existing_download_files}
        )

        if not download_started:
            logging.debug(
                f"Keyboard shortcut did not start download for Google Photos item {google_id}; falling back to menu."
            )
            download_started = _start_google_photos_download(
                driver, selected_only=True
            ) and _wait_for_download_start(
                temp_dir_path, {p.name for p in existing_download_files}
            )
            if not download_started:
                logging.error(
                    f"Could not start individual download for Google Photos item {google_id}"
                )
                failed_count += 1
                continue

        downloaded_file = None
        deadline = time.perf_counter() + max(WEB_DRIVER_WAIT, 10) * 12
        while time.perf_counter() < deadline and not downloaded_file:
            downloaded_file = find_completed_download_file(
                str(temp_dir_path), {p.name for p in existing_download_files}
            )
            time.sleep(0.1)

        if not downloaded_file:
            logging.error(
                f"Timed out waiting for individual download for Google Photos item {google_id}"
            )
            failed_count += 1
            continue

        downloaded_path = temp_dir_path / downloaded_file
        downloaded_name = downloaded_path.name
        target_name = downloaded_name
        resolved_target = (target_album_dir / target_name).resolve()

        if not _is_path_within(resolved_target, output_path):
            logging.error(f"Skipping downloaded file with unsafe path: {target_name}")
            failed_count += 1
            continue

        if downloaded_path.suffix.casefold() == ".zip":
            logging.error(
                f"Refusing ZIP download for Google Photos item {google_id}; ZIP downloads are disabled."
            )
            failed_count += 1
            if downloaded_path.exists():
                downloaded_path.unlink()
            continue

        if resolved_target.exists():
            logging.debug(f"Skipping existing file {resolved_target}")
            skipped_count += 1
            if (
                downloaded_path.resolve() != resolved_target
                and downloaded_path.exists()
            ):
                downloaded_path.unlink()
            continue

        if downloaded_path.resolve() != resolved_target:
            if resolved_target.exists():
                resolved_target.unlink()
            _ = shutil.move(str(downloaded_path), str(resolved_target))

        final_name = resolved_target.name
        _record_google_id_file(
            target_album_dir, google_id, resolved_target, output_path
        )
        if final_name != downloaded_name:
            logging.info(
                f"Saved individual download as {final_name} (renamed from {downloaded_name})"
            )
        else:
            logging.info(f"Saved individual download as {final_name}")
        downloaded_count += 1

    return downloaded_count, skipped_count, failed_count


def _delete_local_album_file(path: Path, output_path: Path, reason: str) -> bool:
    try:
        if not path.exists():
            return False
        if not _is_path_within(path, output_path):
            logging.error(f"Skipping delete for unsafe path: {path}")
            return False
        path.unlink()
        logging.info(f"Deleted local file {reason}: {path}")
        return True
    except OSError as e:
        logging.error(f"Could not delete local file {path}: {e}")
        return False


def _propagate_album_deletes(
    output_path: Path, album_title: str, album_google_ids: set[str]
) -> int:
    files_by_google_id, _ = _local_album_google_id_files(output_path, album_title)
    deleted_count = 0

    for google_id, paths in files_by_google_id.items():
        if google_id in album_google_ids:
            continue
        for path in paths:
            if _delete_local_album_file(path, output_path, "missing from album"):
                deleted_count += 1

    for path in _local_album_files_without_google_id(output_path, album_title):
        if _delete_local_album_file(path, output_path, "without Google ID"):
            deleted_count += 1

    result = (
        f"deleted {deleted_count} local file(s)."
        if deleted_count
        else "nothing to delete."
    )
    logging.info(f"Propagated album deletes for {album_title}: {result}")
    return deleted_count


def _download_missing_album_items_by_google_id(
    driver,
    album_title: str,
    output_path: Path,
    temp_dir_path: Path,
    propagate_deletes: bool,
) -> tuple[bool, int, int, int, int, int]:
    files_by_google_id, _ = _local_album_google_id_files(output_path, album_title)
    existing_google_ids = set(files_by_google_id)
    album_items = _collect_album_photo_items(driver)
    if not album_items:
        logging.info(
            "Could not collect individual Google Photos item links; individual sync cannot proceed."
        )
        return False, 0, 0, 0, 0, 0

    album_google_ids = {item["google_id"].casefold() for item in album_items}
    deleted_count = (
        _propagate_album_deletes(output_path, album_title, album_google_ids)
        if propagate_deletes
        else 0
    )

    missing_items = [
        item
        for item in album_items
        if item["google_id"].casefold() not in existing_google_ids
    ]
    existing_count = len(album_items) - len(missing_items)

    logging.info(
        f"Album [{album_title}] contains {len(album_items)} Google Photos item(s): {existing_count} already saved by Google ID, {len(missing_items)} missing."
    )

    if not missing_items:
        return True, 0, existing_count, 0, len(album_items), deleted_count

    downloaded_count, skipped_count, failed_count = _download_individual_album_items(
        driver, missing_items, album_title, output_path, temp_dir_path
    )
    return (
        True,
        downloaded_count,
        existing_count + skipped_count,
        failed_count,
        len(album_items),
        deleted_count,
    )
