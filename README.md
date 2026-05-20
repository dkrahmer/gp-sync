# Google Photos Downloader

**A Python-based Google Photos downloader built with Selenium.**

This tool automates syncing photos and videos from Google Photos albums by simulating user interaction with the web interface. It uses Selenium to open album links, discover album items by Google ID, and download only missing items into local album folders.

## Features

* Accepts link-shared Google Photos album URLs
* Accepts your own Google Photos album URLs if you supply the profile directory.
* Syncs missing items by Google ID
* Works without needing any API keys or OAuth setup
* Supports batch syncing multiple album links

## Why not use the Google Photos API?

**The original Google Photos API is deprecated**. While the **Google Picker API** is still available, it comes with several major limitations:

* You must select each photo manually, no "select all" option, meaning it can not be automated.
* Limited to a maximum number of items
* It requires setting up a Google Cloud project and API credentials, which is pretty hard.

## Disclaimer

* Be aware of Google’s Terms of Service before using this tool.
* It simulates human actions, but Google might not be happy about someone using this.
* Selenium auto-downloads the Chrome driver if not found, which can take up space.

## Installation

`pip install gp-dl`

## Run from a fresh clone (Bash)

This is the one setup path for development on Windows.

Open Git Bash in the repo root, the folder that contains `pyproject.toml`, then run:

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -e .
mkdir -p test1
python -m gp_dl.cli --album-urls ALBUM_URL1 ALBUM_URL2 --output-dir test1
```

If you want to use your signed-in Chrome session for private albums, add `--profile-dir` with your Chrome user data folder.

## Usage

### CLI
`python -m gp_dl.cli --album-urls ALBUM_URL ALBUM_URL2 --output-dir test`

By default, the CLI runs headless. Add `--show-browser` to run with a visible browser window.

Optional flags:
- `--profile-dir` for private/non-shared albums using your Chrome profile
- `--propagate-deletes` to remove local ID-tagged files no longer present in the album
- `--temp-dir` to override the temporary download directory

### As a module
```py
from gp_dl import download_albums
successful_albums, failed_albums, album_times, album_item_counts, album_file_counts, album_stats = download_albums(["ALBUM_URL", "ALBUM_URL2"], output_dir="test")
```

`album_stats` includes per-album status, counts, and duration that match CLI summary output.

## Package layout

- `gp_dl/workflow.py` — top-level flows (`download_albums`, `list_albums`, `login`)
- `gp_dl/browser.py` — Selenium driver/session setup and download-file detection helpers
- `gp_dl/config.py` — runtime config and locale label loading
- `gp_dl/parsing.py` — filename/ID/media parsing helpers
- `gp_dl/manifest.py` — Google ID manifest read/write helpers
- `gp_dl/local_state.py` — local filesystem/state helpers
- `gp_dl/google_photos_ui.py` — Google Photos UI automation helpers
- `gp_dl/sync.py` — item download/delete sync helpers
- `gp_dl/core.py` — compatibility import surface for internals
- `gp_dl/lib.py` — public compatibility façade (`download_albums`, `list_albums`, etc.)
