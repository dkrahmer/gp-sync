import json
import os
from pathlib import Path

WEB_DRIVER_WAIT = int(os.getenv("WEB_DRIVER_WAIT", "10"))
GOOGLE_LANG = os.getenv("GOOGLE_LANG", "en")


def load_translation(locale):
    file_path = Path(__file__).parent / Path("locales") / f"{locale}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


LABELS = load_translation(GOOGLE_LANG)
