import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urljoin

VIDEO_FILE_EXTENSIONS = {".3gp", ".avi", ".m4v", ".mkv", ".mov", ".mp4"}
MEDIA_FILENAME_RE = re.compile(r"[^\\/\r\n\t:]*\.[A-Za-z0-9]+", re.IGNORECASE)
FILENAME_DATETIME_RES = [
    re.compile(
        r"(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})[_-]?(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})"
    ),
    re.compile(
        r"(?P<year>20\d{2})[-_](?P<month>\d{2})[-_](?P<day>\d{2})[ _-](?P<hour>\d{2})[-_](?P<minute>\d{2})[-_](?P<second>\d{2})"
    ),
]
GOOGLE_PHOTOS_ARIA_RE = re.compile(
    r"(?:Photo|Video)\s+-\s+(?P<orientation>Landscape|Portrait|Square)\s+-\s+(?P<datetime>.+)",
    re.IGNORECASE,
)
GOOGLE_PHOTO_ID_RE = re.compile(r"/photo/(?P<id>[^/?#]+)")
GOOGLE_ID_IN_FILENAME_RE = re.compile(
    r"__gp-(?P<id>AF1Qip[A-Za-z0-9_-]+)(?:\.[^.]+)?$", re.IGNORECASE
)


def _extract_media_filenames(value: str) -> set[str]:
    if not value:
        return set()

    filenames = set()
    text = unquote(str(value)).replace("\\", "/")
    possible_values = {text, text.split("?", 1)[0].split("#", 1)[0]}

    for possible_value in possible_values:
        basename = os.path.basename(possible_value).strip().strip("\"'")
        if ":" in basename:
            continue
        if os.path.splitext(basename)[1]:
            filenames.add(basename)

    for match in MEDIA_FILENAME_RE.findall(text):
        basename = os.path.basename(match.strip().strip("\"'"))
        if basename:
            filenames.add(basename)

    return filenames


def _normalize_filename(value: str) -> str:
    value = unquote(value).replace("\\", "/")
    value = os.path.basename(value).strip().strip("\"'")
    value = re.sub(r"\s+", " ", value)
    return value.casefold()


def _datetime_from_filename(filename: str) -> datetime | None:
    for pattern in FILENAME_DATETIME_RES:
        match = pattern.search(filename)
        if not match:
            continue
        try:
            parts = {name: int(value) for name, value in match.groupdict().items()}
            return datetime(
                parts["year"],
                parts["month"],
                parts["day"],
                parts["hour"],
                parts["minute"],
                parts["second"],
            )
        except ValueError:
            continue
    return None


def _jpeg_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as file:
            if file.read(2) != b"\xff\xd8":
                return None
            while True:
                marker_start = file.read(1)
                if not marker_start:
                    return None
                if marker_start != b"\xff":
                    continue
                marker = file.read(1)
                while marker == b"\xff":
                    marker = file.read(1)
                if marker in {b"\xd8", b"\xd9"}:
                    continue
                length_bytes = file.read(2)
                if len(length_bytes) != 2:
                    return None
                length = int.from_bytes(length_bytes, "big")
                if (
                    b"\xc0" <= marker <= b"\xc3"
                    or b"\xc5" <= marker <= b"\xc7"
                    or b"\xc9" <= marker <= b"\xcb"
                    or b"\xcd" <= marker <= b"\xcf"
                ):
                    data = file.read(5)
                    if len(data) != 5:
                        return None
                    height = int.from_bytes(data[1:3], "big")
                    width = int.from_bytes(data[3:5], "big")
                    return width, height
                file.seek(max(length - 2, 0), os.SEEK_CUR)
    except OSError:
        return None


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as file:
            if file.read(8) != b"\x89PNG\r\n\x1a\n":
                return None
            length = int.from_bytes(file.read(4), "big")
            chunk_type = file.read(4)
            if chunk_type != b"IHDR" or length < 8:
                return None
            width = int.from_bytes(file.read(4), "big")
            height = int.from_bytes(file.read(4), "big")
            return width, height
    except OSError:
        return None


def _media_orientation(path: Path) -> str | None:
    dimensions = None
    suffix = path.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        dimensions = _jpeg_dimensions(path)
    elif suffix == ".png":
        dimensions = _png_dimensions(path)

    if not dimensions:
        return None

    width, height = dimensions
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _timestamp_keys(value: datetime, tolerance_seconds: int = 5) -> set[str]:
    return {
        (value + timedelta(seconds=offset)).strftime("%Y%m%d%H%M%S")
        for offset in range(-tolerance_seconds, tolerance_seconds + 1)
    }


def _local_media_descriptors(path: Path) -> set[str]:
    taken_at = _datetime_from_filename(path.name)
    if not taken_at:
        return set()

    orientation = _media_orientation(path)
    descriptors = set()
    for timestamp_key in _timestamp_keys(taken_at):
        if orientation:
            descriptors.add(f"{orientation}|{timestamp_key}")
        else:
            descriptors.add(f"*|{timestamp_key}")
    return descriptors


def _parse_google_photos_datetime(value: str) -> datetime | None:
    normalized = value.replace("\u202f", " ").replace("\xa0", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for date_format in ("%b %d, %Y, %I:%M:%S %p", "%B %d, %Y, %I:%M:%S %p"):
        try:
            return datetime.strptime(normalized, date_format)
        except ValueError:
            continue
    return None


def _google_media_descriptors(value: str) -> set[str]:
    match = GOOGLE_PHOTOS_ARIA_RE.search(str(value))
    if not match:
        return set()

    taken_at = _parse_google_photos_datetime(match.group("datetime"))
    if not taken_at:
        return set()

    orientation = match.group("orientation").casefold()
    timestamp_key = taken_at.strftime("%Y%m%d%H%M%S")
    return {f"{orientation}|{timestamp_key}"}


def _extract_google_photo_ids(value: str) -> set[str]:
    return {match.group("id") for match in GOOGLE_PHOTO_ID_RE.finditer(str(value))}


def _extract_google_id_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    match = GOOGLE_ID_IN_FILENAME_RE.search(stem)
    return match.group("id") if match else None


def _candidate_photo_url(candidates: list[str], base_url: str) -> str | None:
    for candidate in candidates:
        if "/photo/" in str(candidate):
            return urljoin(base_url, str(candidate))
    return None


def _item_looks_like_video(item: dict[str, str]) -> bool:
    identifiers = str(item.get("identifiers", ""))
    if re.search(r"(^|[,\s])Video\s+-", identifiers, re.IGNORECASE):
        return True

    for filename in _extract_media_filenames(identifiers):
        if Path(filename).suffix.casefold() in VIDEO_FILE_EXTENSIONS:
            return True

    return False


def _content_disposition_filename(value: str | None) -> str | None:
    if not value:
        return None

    match = re.search(r"filename\*=UTF-8''([^;]+)", value, re.IGNORECASE)
    if match:
        return os.path.basename(unquote(match.group(1)).strip().strip('"'))

    match = re.search(r'filename="?([^";]+)"?', value, re.IGNORECASE)
    if match:
        return os.path.basename(unquote(match.group(1)).strip().strip('"'))

    return None


def _download_response_filename(response) -> str | None:
    return _content_disposition_filename(response.headers.get("Content-Disposition"))
