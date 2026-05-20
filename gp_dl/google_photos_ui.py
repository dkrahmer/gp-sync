import logging
import time
from pathlib import Path

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .browser import find_started_download_file
from .config import LABELS, WEB_DRIVER_WAIT
from .local_state import _descriptor_exists, _existing_album_files
from .parsing import (
    _candidate_photo_url,
    _extract_google_photo_ids,
    _extract_media_filenames,
    _google_media_descriptors,
    _normalize_filename,
)

__labels = LABELS
MAX_ALBUM_SCAN_STEPS = 1000

COLLECT_VISIBLE_ALBUM_ITEMS_SCRIPT = """
const scope = document.body;
const seen = new Set();
const roots = [];

function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= 80 && rect.height >= 80 && rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
}

function addCandidate(list, value) {
    if (value === undefined || value === null) return;
    const text = String(value).trim();
    if (text) list.push(text);
}

function collectCandidates(el) {
    const candidates = [];
    const attrs = ['data-filename', 'aria-label', 'title', 'alt', 'download', 'href', 'src'];
    const elements = [el, ...Array.from(el.querySelectorAll('[data-filename], [aria-label], [title], img, a, video, source'))].slice(0, 250);
    for (const item of elements) {
        for (const attr of attrs) addCandidate(candidates, item.getAttribute && item.getAttribute(attr));
        if (item.dataset) {
            for (const value of Object.values(item.dataset)) addCandidate(candidates, value);
        }
    }
    return Array.from(new Set(candidates)).slice(0, 80);
}

function findTile(media) {
    let node = media;
    let best = media;
    for (let depth = 0; node && depth < 10; depth++, node = node.parentElement) {
        const role = node.getAttribute && node.getAttribute('role');
        if (role === 'gridcell' || role === 'listitem' || role === 'button' || role === 'checkbox' || node.tagName === 'A') {
            best = node;
        }
        if (node.getAttribute && (node.getAttribute('aria-selected') !== null || node.getAttribute('aria-checked') !== null)) {
            best = node;
        }
    }
    return best;
}

const mediaSelectors = [
    'img',
    'video',
    'a[aria-label^="Photo -"]',
    'a[aria-label^="Video -"]',
    'div[aria-label^="Photo -"]',
    'div[aria-label^="Video -"]',
    'a.p137Zd'
];
for (const media of Array.from(scope.querySelectorAll(mediaSelectors.join(',')))) {
    if (!isVisible(media)) continue;
    const tile = findTile(media);
    if (!isVisible(tile)) continue;
    const rect = tile.getBoundingClientRect();
    const candidates = collectCandidates(tile);
    const mediaKey = media.currentSrc || media.src || media.getAttribute('src') || media.getAttribute('href') || candidates.join('|');
    const key = mediaKey || [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)].join('|');
    if (seen.has(key)) continue;
    seen.add(key);
    roots.push({ element: tile, candidates, key });
}

return roots;
"""

SCROLL_ALBUM_SCRIPT = """
const minStep = 400;
const pageStep = Math.max(minStep, Math.floor(window.innerHeight * 0.85));
const scrollables = Array.from(document.querySelectorAll('*')).filter((el) => {
    const style = window.getComputedStyle(el);
    return el.scrollHeight > el.clientHeight + 200 && style.overflowY !== 'hidden' && style.display !== 'none';
});
const scroller = scrollables.sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0] || document.scrollingElement || document.documentElement;
const before = scroller.scrollTop;
scroller.scrollTop = Math.min(scroller.scrollTop + pageStep, scroller.scrollHeight);
window.scrollBy(0, pageStep);
const top = Math.max(scroller.scrollTop, window.scrollY || 0);
const height = Math.max(scroller.scrollHeight, document.documentElement.scrollHeight, document.body.scrollHeight);
const client = Math.max(scroller.clientHeight, window.innerHeight);
return { before, top, height, client, atBottom: top + client >= height - 8 };
"""

RESET_ALBUM_SCROLL_SCRIPT = """
const scrollables = Array.from(document.querySelectorAll('*')).filter((el) => el.scrollHeight > el.clientHeight + 200);
for (const el of scrollables) el.scrollTop = 0;
window.scrollTo(0, 0);
"""

COLLECT_ALBUM_PHOTO_LINKS_SCRIPT = r"""
function addCandidate(list, value) {
    if (value === undefined || value === null) return;
    const text = String(value).trim();
    if (text) list.push(text);
}

function collectCandidates(anchor) {
    const candidates = [];
    const attrs = ['data-filename', 'aria-label', 'title', 'alt', 'download', 'href', 'src'];
    const elements = [anchor, ...Array.from(anchor.querySelectorAll('[data-filename], [aria-label], [title], img, a, video, source'))].slice(0, 100);
    for (const item of elements) {
        for (const attr of attrs) addCandidate(candidates, item.getAttribute && item.getAttribute(attr));
        if (item.dataset) {
            for (const value of Object.values(item.dataset)) addCandidate(candidates, value);
        }
    }
    return Array.from(new Set(candidates)).slice(0, 80);
}

return Array.from(document.querySelectorAll('a[href*="/photo/"]')).map((anchor) => {
    const href = anchor.href || anchor.getAttribute('href') || '';
    const idMatch = href.match(/\/photo\/([^/?#]+)/);
    return {
        url: href,
        google_id: idMatch ? idMatch[1] : '',
        aria: anchor.getAttribute('aria-label') || '',
        candidates: collectCandidates(anchor)
    };
}).filter((item) => item.url && item.google_id);
"""


def _download_menu_labels(selected_only: bool = False) -> list[str]:
    labels = []
    if selected_only:
        labels.append(__labels.get("download_selected", "Download"))
    labels.extend(
        [__labels.get("download", "Download all"), "Download", "Download all"]
    )

    unique_labels = []
    for label in labels:
        if label and label not in unique_labels:
            unique_labels.append(label)
    return unique_labels


def _xpath_literal(value: str) -> str:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    return "concat(" + ", '\"', ".join(f'"{part}"' for part in value.split('"')) + ")"


def _click_first_xpath(driver, xpaths: list[str], timeout: int = 2) -> bool:
    for xpath in xpaths:
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            element.click()
            return True
        except TimeoutException:
            pass
        except Exception as e:
            logging.debug(f"Could not click element for xpath {xpath}: {e}")

        try:
            for element in driver.find_elements(By.XPATH, xpath):
                if not element.is_displayed():
                    continue
                element.click()
                return True
        except Exception as e:
            logging.debug(
                f"Could not click visible fallback element for xpath {xpath}: {e}"
            )
    return False


def _open_download_menu(driver) -> bool:
    option_labels = [__labels.get("options", "More options"), "More options"]
    option_xpaths = [
        f"//*[@aria-label={_xpath_literal(label)}]" for label in option_labels if label
    ]
    if _click_first_xpath(driver, option_xpaths, timeout=2):
        return True

    try:
        share_button = WebDriverWait(driver, WEB_DRIVER_WAIT).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    f"//*[@aria-label={_xpath_literal(__labels.get('share', 'Share'))}]",
                )
            )
        )
    except TimeoutException:
        return False

    share_button.send_keys(Keys.TAB)
    menu_button = driver.execute_script("return document.activeElement")
    menu_button.click()
    return True


def _download_label_xpaths(label: str) -> list[str]:
    literal = _xpath_literal(label)
    return [
        f"//*[@aria-label={literal}]",
        f"//*[starts-with(@aria-label, {literal})]",
        f"//*[normalize-space(text())={literal}]",
        f"//*[contains(normalize-space(.), {literal}) and @role='menuitem']",
    ]


def _click_download_menu_item(driver, selected_only: bool = False) -> bool:
    xpaths = []
    for label in _download_menu_labels(selected_only=selected_only):
        xpaths.extend(_download_label_xpaths(label))
    return _click_first_xpath(driver, xpaths, timeout=WEB_DRIVER_WAIT)


def _start_google_photos_download(driver, selected_only: bool = False) -> bool:
    try:
        driver.execute_script(RESET_ALBUM_SCROLL_SCRIPT)
    except Exception:
        pass

    if not _open_download_menu(driver):
        return False

    return _click_download_menu_item(driver, selected_only=selected_only)


def _classify_album_item(
    candidates: list[str],
    existing_names: set[str],
    _existing_stems: set[str],
    existing_descriptors: set[str],
    existing_google_ids: set[str],
) -> tuple[str, set[str]]:
    identifiers = set()
    filenames = set()
    descriptors = set()
    google_ids = set()
    for candidate in candidates:
        filenames.update(_extract_media_filenames(candidate))
        descriptors.update(_google_media_descriptors(candidate))
        google_ids.update(_extract_google_photo_ids(candidate))

    identifiers.update(filenames)
    identifiers.update(descriptors)
    identifiers.update(google_ids)

    if not identifiers:
        return "unknown", identifiers

    for google_id in google_ids:
        if google_id.casefold() in existing_google_ids:
            return "existing", identifiers

    for filename in filenames:
        normalized = _normalize_filename(filename)
        if normalized in existing_names:
            return "existing", identifiers

    for descriptor in descriptors:
        if _descriptor_exists(descriptor, existing_descriptors):
            return "existing", identifiers

    return "missing", identifiers


def _prepare_filtered_album_download(
    driver, output_path: Path, album_title: str
) -> tuple[bool, bool, int, int, int, list[dict[str, str]]]:
    (
        existing_names,
        existing_stems,
        existing_descriptors,
        existing_google_ids,
        album_dirs,
    ) = _existing_album_files(output_path, album_title)
    existing_count_on_disk = len(existing_names)
    if not existing_names:
        logging.debug(
            f"No existing media files found for album [{album_title}] in {[str(path) for path in album_dirs]}; full album download is required."
        )
        return False, False, 0, 0, 0, []

    logging.info(
        f"Scanning Google Photos album before downloading; found {existing_count_on_disk} local media file(s) for album [{album_title}]."
    )

    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    except Exception:
        pass

    try:
        driver.execute_script(RESET_ALBUM_SCROLL_SCRIPT)
    except Exception:
        pass
    time.sleep(1)

    seen_keys = set()
    missing_count = 0
    existing_count = 0
    unknown_count = 0
    recognized_count = 0
    unchanged_steps = 0
    items = []
    missing_items: list[dict[str, str]] = []

    scan_wait_deadline = time.perf_counter() + WEB_DRIVER_WAIT
    while time.perf_counter() < scan_wait_deadline:
        items = driver.execute_script(COLLECT_VISIBLE_ALBUM_ITEMS_SCRIPT) or []
        if items:
            break
        time.sleep(0.25)

    for _ in range(MAX_ALBUM_SCAN_STEPS):
        if not items:
            items = driver.execute_script(COLLECT_VISIBLE_ALBUM_ITEMS_SCRIPT) or []
        new_items_seen = 0

        for item in items:
            candidates = item.get("candidates", [])
            status, filenames = _classify_album_item(
                candidates,
                existing_names,
                existing_stems,
                existing_descriptors,
                existing_google_ids,
            )
            if filenames:
                key = "filenames:" + "|".join(
                    sorted(_normalize_filename(filename) for filename in filenames)
                )
            else:
                key = item.get("key") or "|".join(
                    sorted(str(candidate) for candidate in candidates)
                )
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            new_items_seen += 1

            if filenames:
                recognized_count += 1

            if status == "existing":
                existing_count += 1
                logging.debug(
                    f"Skipping existing album item before download: {sorted(filenames)}"
                )
                continue

            if status == "unknown":
                unknown_count += 1
                logging.debug(
                    "Could not determine a filename for a Google Photos item during pre-download filtering."
                )
                continue

            photo_url = _candidate_photo_url(candidates, driver.current_url)
            google_ids = sorted(
                google_id
                for candidate in candidates
                for google_id in _extract_google_photo_ids(candidate)
            )
            if not photo_url or not google_ids:
                unknown_count += 1
                logging.debug(
                    f"Could not determine a direct photo URL/id for missing album item {sorted(filenames)}."
                )
                continue

            missing_count += 1
            missing_items.append(
                {
                    "url": photo_url,
                    "google_id": google_ids[0],
                    "identifiers": ", ".join(sorted(filenames)),
                }
            )
            logging.debug(
                f"Queued missing album item for individual download: {sorted(filenames)}"
            )

        if new_items_seen == 0:
            unchanged_steps += 1
        else:
            unchanged_steps = 0

        scroll_info = driver.execute_script(SCROLL_ALBUM_SCRIPT) or {}
        items = []
        time.sleep(0.35)
        if scroll_info.get("atBottom") and unchanged_steps >= 2:
            break

    logging.info(
        f"Album scan complete: {recognized_count} identifiable item(s), {existing_count} existing, {missing_count} missing, {unknown_count} unknown."
    )

    if recognized_count == 0:
        logging.info(
            "Could not identify Google Photos album items; individual sync is unavailable."
        )
        return False, False, missing_count, existing_count, unknown_count, []

    if unknown_count:
        logging.info(
            f"Could not identify filenames for {unknown_count} album item(s); individual sync may miss some files."
        )
        return False, False, missing_count, existing_count, unknown_count, []

    if missing_count == 0 and existing_count > 0:
        return True, False, missing_count, existing_count, unknown_count, []

    if missing_count > 0:
        return True, True, missing_count, existing_count, unknown_count, missing_items

    return False, False, missing_count, existing_count, unknown_count, []


def _start_download_with_keyboard_shortcut(driver) -> bool:
    try:
        body = WebDriverWait(driver, max(1, min(WEB_DRIVER_WAIT, 5))).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        body.send_keys(Keys.SHIFT, "d")
        return True
    except Exception as first_error:
        logging.debug(f"Primary keyboard shortcut attempt failed: {first_error}")

    try:
        active = driver.execute_script("return document.activeElement")
        if active is not None:
            active.send_keys(Keys.SHIFT, "d")
            return True
    except Exception as second_error:
        logging.debug(
            f"Active-element keyboard shortcut attempt failed: {second_error}"
        )

    try:
        dispatched = driver.execute_script(
            """
            const target = document.activeElement || document.body || document.documentElement;
            if (!target) return false;
            const event = new KeyboardEvent('keydown', {
                key: 'D',
                code: 'KeyD',
                shiftKey: true,
                bubbles: true,
                cancelable: true,
                composed: true,
            });
            target.dispatchEvent(event);
            if (document.body && document.body !== target) {
                document.body.dispatchEvent(event);
            }
            return true;
            """
        )
        if dispatched:
            return True
    except Exception as third_error:
        logging.debug(f"DOM keyboard event dispatch failed: {third_error}")

    return False


def _wait_for_download_start(
    temp_dir_path: Path, existing_download_files: set[str], timeout: float = 4.0
) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if find_started_download_file(str(temp_dir_path), existing_download_files):
            return True
        time.sleep(0.1)
    return False


def _is_motion_photo_page(driver, timeout: float = 0.0) -> bool:
    deadline = time.perf_counter() + timeout
    while True:
        try:
            controls = driver.find_elements(
                By.XPATH,
                '//*[@aria-label="Turn on motion" or @aria-label="Turn off motion"]',
            )
            for control in controls:
                try:
                    if not control.is_displayed():
                        continue
                    if control.rect.get("width", 0) <= 0 or control.rect.get("height", 0) <= 0:
                        continue
                    return True
                except Exception:
                    continue
        except Exception:
            return False

        if time.perf_counter() >= deadline:
            return False
        time.sleep(0.2)


def _photo_image_download_url(driver, timeout: float | None = None) -> str | None:
    deadline = time.perf_counter() + (
        timeout if timeout is not None else WEB_DRIVER_WAIT
    )
    src = None

    while time.perf_counter() < deadline:
        try:
            src = driver.execute_script(
                """
                function isVisible(img) {
                    if (!img) return false;
                    const rect = img.getBoundingClientRect();
                    if (rect.width <= 1 || rect.height <= 1) return false;
                    const style = window.getComputedStyle(img);
                    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
                    if (Number(style.opacity || '1') === 0) return false;
                    return true;
                }

                const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
                const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;

                const images = Array.from(document.querySelectorAll('img'))
                    .filter((img) => img.naturalWidth > 200 && img.naturalHeight > 200 && isVisible(img))
                    .map((img) => {
                        const rect = img.getBoundingClientRect();
                        const inViewport = rect.bottom > 0 && rect.right > 0 && rect.top < viewportHeight && rect.left < viewportWidth;
                        const area = rect.width * rect.height;
                        const naturalArea = img.naturalWidth * img.naturalHeight;
                        // Prefer currently visible/in-viewport content over hidden stale images.
                        const score = (inViewport ? 10_000_000_000 : 0) + (area * 1000) + naturalArea;
                        return { img, score };
                    })
                    .sort((a, b) => b.score - a.score);

                const selected = images[0] ? images[0].img : null;
                return selected ? (selected.currentSrc || selected.src || selected.getAttribute('src')) : null;
                """
            )
        except Exception as e:
            logging.debug(f"Could not read displayed photo image URL: {e}")
            return None

        if src:
            break
        time.sleep(0.2)

    if not src:
        return None

    src = str(src)
    if "=" in src and "/" not in src.split("=")[-1]:
        return src.rsplit("=", 1)[0] + "=d"
    return f"{src}=d"


def _collect_album_photo_items(
    driver,
    max_items: int | None = None,
    exclude_google_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    collected: dict[str, dict[str, str]] = {}
    unchanged_steps = 0
    excluded = {value.casefold() for value in (exclude_google_ids or set())}

    deadline = time.perf_counter() + WEB_DRIVER_WAIT
    while time.perf_counter() < deadline:
        items = driver.execute_script(COLLECT_ALBUM_PHOTO_LINKS_SCRIPT) or []
        if items:
            break
        time.sleep(0.25)
    else:
        items = []

    for _ in range(MAX_ALBUM_SCAN_STEPS):
        new_items = 0
        for item in items:
            google_id = str(item.get("google_id", "")).strip()
            url = str(item.get("url", "")).strip()
            if (
                not google_id
                or not url
                or google_id in collected
                or google_id.casefold() in excluded
            ):
                continue
            candidate_values = [
                str(value) for value in (item.get("candidates") or []) if value
            ]
            filenames = set()
            for value in candidate_values:
                filenames.update(_extract_media_filenames(value))

            identifiers = [str(item.get("aria", "") or "").strip(), *sorted(filenames)]
            identifiers = ", ".join(value for value in identifiers if value)

            collected[google_id] = {
                "url": url,
                "google_id": google_id,
                "identifiers": identifiers or google_id,
            }
            new_items += 1
            if max_items is not None and len(collected) >= max_items:
                return list(collected.values())

        unchanged_steps = unchanged_steps + 1 if new_items == 0 else 0
        scroll_info = driver.execute_script(SCROLL_ALBUM_SCRIPT) or {}
        time.sleep(0.35)
        if scroll_info.get("atBottom") and unchanged_steps >= 2:
            break
        items = driver.execute_script(COLLECT_ALBUM_PHOTO_LINKS_SCRIPT) or []

    return list(collected.values())
