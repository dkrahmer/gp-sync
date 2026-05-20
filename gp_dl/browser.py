import logging
import os
from pathlib import Path

from selenium.webdriver import Chrome, ChromeService
from selenium.webdriver.chrome.options import Options

WSL_INSIDE = os.getenv("WSL_INSIDE", False)
CHROME_BINARY = os.getenv("CHROME_BINARY", "")

__driver__ = None
__driver_download_dir__ = None


def get_driver(driver_path=None, profile_dir=None, headless=True, temp_dir=None):
    global __driver__, __driver_download_dir__
    requested_download_dir = temp_dir or os.path.join(os.getcwd(), "gp_temp")
    if __driver__ is None or __driver_download_dir__ != requested_download_dir:
        if __driver__ is not None:
            try:
                __driver__.quit()
            except Exception:
                pass
        logging.info(
            f"Initialize driver with driver {driver_path} and profile ({profile_dir} (headless={headless}))..."
        )
        __driver__ = setup_driver(
            driver_path, profile_dir, headless, requested_download_dir
        )
        __driver_download_dir__ = requested_download_dir
    return __driver__


def reset_driver():
    global __driver__, __driver_download_dir__
    __driver__ = None
    __driver_download_dir__ = None


def setup_driver(driver_path=None, profile_dir=None, headless=True, download_dir=None):
    chrome_options = Options()
    if CHROME_BINARY:
        logging.info(f"Use binary <{CHROME_BINARY}>")
        chrome_options.binary_location = CHROME_BINARY
    if profile_dir:
        chrome_options.add_argument(f"--user-data-dir={profile_dir}")
    if headless:
        if WSL_INSIDE:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
        else:
            chrome_options.add_argument("--headless")

    prefs = {
        "download.prompt_for_download": False,
        "download.default_directory": download_dir
        or os.path.join(os.getcwd(), "gp_temp"),
        "profile.default_content_setting_values.automatic_downloads": 1,
    }

    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    if driver_path:
        service = ChromeService(executable_path=driver_path)
        return Chrome(options=chrome_options, service=service)
    else:
        return Chrome(options=chrome_options)


def find_completed_download_file(temp_dir: str, exclude: set[str] | None = None):
    for file in os.listdir(temp_dir):
        if exclude is not None and file in exclude:
            continue
        if file.endswith((".crdownload", ".tmp")):
            continue
        if (Path(temp_dir) / file).is_file():
            return file


def find_started_download_file(temp_dir: str, exclude: set[str] | None = None):
    for file in os.listdir(temp_dir):
        if exclude is not None and file in exclude:
            continue
        if (Path(temp_dir) / file).is_file():
            return file
