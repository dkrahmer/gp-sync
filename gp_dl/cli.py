import argparse
import logging
import sys
import time
from statistics import median

try:
    from .workflow import download_albums, list_albums
except ImportError:
    # Allow running cli.py directly (as a script) for development.
    from workflow import download_albums, list_albums

BANNER = """
██████   ██████         ██████  ██
██       ██   ██        ██   ██ ██
██   ███ ██████   █████ ██   ██ ██
██    ██ ██             ██   ██ ██
██████   ██             ██████  ███████

gp-dl — Google Photos Downloader
Sync download full-resolution albums from Google Photos using Selenium

Author: dkrahmer  |  GitHub: https://github.com/dkrahmer
Original author: csd4ni3l  |  GitHub: https://github.com/csd4ni3l
"""

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "ERROR": logging.ERROR,
    "FATAL": logging.FATAL,
    "QUIET": 999999999,
}


def parse_cli_args():
    parser = argparse.ArgumentParser(
        description="Sync download full-resolution images from a Google Photos album using Selenium."
    )
    parser.add_argument("--album-urls", nargs="+", help="Google Photos album URL(s)")
    parser.add_argument(
        "--output-dir",
        default=None,
        required=True,
        help="The directory to save downloaded albums",
    )
    parser.add_argument("--driver-path", default=None, help="Custom Chrome driver path")
    parser.add_argument(
        "--profile-dir",
        default=None,
        help="A Chrome user data directory for sessions, set this if you want to open non-shared links.",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Show the browser window (default is headless)",
    )
    parser.add_argument(
        "--user", default=None, help="Google user login (ie. email address)"
    )
    parser.add_argument("--password", default=None, help="Google user password")
    parser.add_argument(
        "--propagate-deletes",
        action="store_true",
        help="Delete local ID-tagged media files for this album when their Google Photos item is no longer in the album",
    )
    parser.add_argument(
        "--temp-dir",
        default=None,
        help="Directory to store temporary downloads before they are moved into album folders; defaults to output-dir",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Specifies what to include in log output. Available levels: debug, info, error, fatal",
    )
    return parser.parse_args()


def configure_logging(log_level: str):
    if log_level.upper() not in LOG_LEVELS:
        print(f"Invalid logging level: {log_level}")
        sys.exit(1)

    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s",
        level=LOG_LEVELS[log_level.upper()],
    )
    for logger_to_disable in ["selenium", "urllib3"]:
        logging.getLogger(logger_to_disable).propagate = False
        logging.getLogger(logger_to_disable).disabled = True


def run_cli():
    args = parse_cli_args()

    if args.log_level.upper() != "QUIET":
        print(BANNER)

    configure_logging(args.log_level)

    all_start = time.perf_counter()
    headless = not args.show_browser
    album_urls = args.album_urls
    if not args.album_urls:
        album_urls = list_albums(
            driver_path=args.driver_path,
            profile_dir=args.profile_dir,
            headless=headless,
            user=args.user,
            password=args.password,
        )
    if not album_urls:
        logging.error("No albums to process.")
        return

    (
        successful_albums,
        failed_albums,
        album_times,
        album_item_counts,
        album_file_counts,
        album_stats,
    ) = download_albums(
        album_urls=album_urls,
        output_dir=args.output_dir,
        driver_path=args.driver_path,
        profile_dir=args.profile_dir,
        headless=headless,
        temp_dir=args.temp_dir,
        propagate_deletes=args.propagate_deletes,
    )

    logging.info("")
    logging.info("===== DOWNLOAD STATISTICS =====")
    logging.info("Per album")
    if not album_stats:
        logging.info("- None")
    else:
        for stat in album_stats:
            logging.info(
                f"- {stat['album']}: status={stat['status']}, items={stat['items_found']}, downloaded={stat['downloaded']}, deleted={stat['deleted']}, "
                f"failed_items={stat['failed_items']}, time={float(stat['duration_seconds']):.2f}s"
            )

    logging.info("Combined")
    logging.info(f"- Total albums: {len(album_urls)}")
    logging.info(f"- Successful albums: {len(successful_albums)}")
    logging.info(f"- Failed albums: {len(failed_albums)}")
    logging.info(f"- Total files found in albums: {sum(album_item_counts or [0])}")
    logging.info(f"- Total files downloaded: {sum(album_file_counts or [0])}")
    logging.info(
        f"- Median time taken per album: {median(album_times or [0]):.2f} seconds"
    )
    logging.info(
        f"- Average time taken per album: {sum(album_times or [0]) / len(album_times or [0]):.2f} seconds"
    )
    logging.info(f"- Total time taken: {time.perf_counter() - all_start:.2f} seconds")

    logging.info("================================")


if __name__ == "__main__":
    run_cli()
