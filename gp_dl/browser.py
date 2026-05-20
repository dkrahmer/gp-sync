import logging
import os
import platform
from pathlib import Path

from selenium.webdriver import Chrome, ChromeService
from selenium.webdriver.chrome.options import Options

WSL_INSIDE = os.getenv("WSL_INSIDE", False)
CHROME_BINARY = os.getenv("CHROME_BINARY", "")
RUNNING_ON_LINUX = platform.system().lower() == "linux"

__driver__ = None
__driver_download_dir__ = None
__driver_params__: dict = {}


def get_driver(driver_path=None, profile_dir=None, headless=True, temp_dir=None):
    global __driver__, __driver_download_dir__, __driver_params__
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
        __driver_params__ = {
            "driver_path": driver_path,
            "profile_dir": profile_dir,
            "headless": headless,
        }
    return __driver__


def reset_driver():
    global __driver__, __driver_download_dir__
    __driver__ = None
    __driver_download_dir__ = None


def restart_driver():
    """Quit the current driver (if any) and start a fresh one with the same parameters."""
    global __driver__, __driver_download_dir__, __driver_params__
    if __driver__ is not None:
        try:
            __driver__.quit()
        except Exception:
            pass
        __driver__ = None
    params = dict(__driver_params__)
    params["temp_dir"] = __driver_download_dir__
    return get_driver(**params)


def _apply_download_behavior(driver, download_dir: str) -> None:
    try:
        Path(download_dir).mkdir(parents=True, exist_ok=True)
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(Path(download_dir).resolve())},
        )
    except Exception as e:
        logging.debug(f"Could not apply CDP download behavior to {download_dir}: {e}")


def setup_driver(driver_path=None, profile_dir=None, headless=True, download_dir=None):
    chrome_options = Options()
    if CHROME_BINARY:
        logging.info(f"Use binary <{CHROME_BINARY}>")
        chrome_options.binary_location = CHROME_BINARY
    if profile_dir:
        chrome_options.add_argument(f"--user-data-dir={profile_dir}")
    if headless:
        if WSL_INSIDE or RUNNING_ON_LINUX:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
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
    chrome_options.set_capability(
        "goog:loggingPrefs", {"browser": "ALL", "performance": "ALL"}
    )

    resolved_download_dir = str(
        Path(download_dir or os.path.join(os.getcwd(), "gp_temp")).resolve()
    )
    Path(resolved_download_dir).mkdir(parents=True, exist_ok=True)

    if driver_path:
        service = ChromeService(executable_path=driver_path)
        driver = Chrome(options=chrome_options, service=service)
    else:
        driver = Chrome(options=chrome_options)

    _apply_download_behavior(driver, resolved_download_dir)
    return driver


def find_completed_download_file(temp_dir: str, exclude: set[str] | None = None):
    temp_dir_path = Path(temp_dir)
    try:
        files = os.listdir(temp_dir)
    except FileNotFoundError:
        logging.debug(
            f"Download directory does not exist yet while waiting for completed download: {temp_dir_path}"
        )
        temp_dir_path.mkdir(parents=True, exist_ok=True)
        return None
    except OSError as e:
        logging.debug(
            f"Could not read download directory while waiting for completed download {temp_dir_path}: {e}"
        )
        return None

    for file in files:
        if exclude is not None and file in exclude:
            continue
        if file.endswith((".crdownload", ".tmp")):
            continue
        if (temp_dir_path / file).is_file():
            return file


def find_started_download_file(temp_dir: str, exclude: set[str] | None = None):
    temp_dir_path = Path(temp_dir)
    try:
        files = os.listdir(temp_dir)
    except FileNotFoundError:
        logging.debug(
            f"Download directory does not exist yet while waiting for download start: {temp_dir_path}"
        )
        temp_dir_path.mkdir(parents=True, exist_ok=True)
        return None
    except OSError as e:
        logging.debug(
            f"Could not read download directory while waiting for download start {temp_dir_path}: {e}"
        )
        return None

    for file in files:
        if exclude is not None and file in exclude:
            continue
        if (temp_dir_path / file).is_file():
            return file
