import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gp_dl import sync


class FakeDriver:
    def __init__(self):
        self.current_url = "https://photos.google.com/photo/previous"
        self.visited_urls = []

    def get(self, url):
        self.current_url = url
        self.visited_urls.append(url)


class MotionPhotoFallbackTests(unittest.TestCase):
    def test_failed_motion_download_uses_pre_failure_image_url_for_direct_fallback(
        self,
    ):
        driver = FakeDriver()
        item_url = "https://photos.google.com/photo/AF1Qip-current"
        captured_image_url = "https://lh3.googleusercontent.com/current-photo=d"
        fallback_calls = []

        with (
            tempfile.TemporaryDirectory() as output_dir,
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            output_path = Path(output_dir)
            temp_dir_path = Path(temp_dir)

            def fake_download_motion_photo_still(*args, **kwargs):
                fallback_calls.append(kwargs)
                (temp_dir_path / "current.jpg").write_bytes(b"current image")
                return "current.jpg"

            with (
                patch.object(sync, "MOTION_PHOTO_DIRECT_SAVE_ONLY", False),
                patch.object(sync, "_is_motion_photo_page", return_value=True),
                patch.object(
                    sync, "_photo_image_download_url", return_value=captured_image_url
                ),
                patch.object(
                    sync, "_start_download_with_keyboard_shortcut", return_value=True
                ),
                patch.object(
                    sync, "_motion_photo_page_looks_broken", return_value=True
                ),
                patch.object(
                    sync,
                    "_download_motion_photo_still",
                    side_effect=fake_download_motion_photo_still,
                ),
                patch.object(
                    sync, "_local_album_google_id_files", return_value=({}, [])
                ),
                patch.object(
                    sync, "_local_album_files_by_normalized_name", return_value=({}, [])
                ),
                patch.object(sync, "_record_google_id_file"),
            ):
                downloaded, skipped, failed = sync._download_individual_album_items(
                    driver,
                    [
                        {
                            "google_id": "AF1Qip-current",
                            "url": item_url,
                            "identifiers": "current.jpg",
                        }
                    ],
                    "Album",
                    output_path,
                    temp_dir_path,
                )

        self.assertEqual((downloaded, skipped, failed), (1, 0, 0))
        self.assertEqual(len(fallback_calls), 1)
        self.assertEqual(fallback_calls[0]["image_url"], captured_image_url)
        self.assertEqual(fallback_calls[0]["referer_url"], item_url)

    def test_video_items_do_not_enter_motion_photo_fallback(self):
        driver = FakeDriver()
        item_url = "https://photos.google.com/photo/AF1Qip-video"

        with (
            tempfile.TemporaryDirectory() as output_dir,
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            output_path = Path(output_dir)
            temp_dir_path = Path(temp_dir)

            def fake_find_completed_download_with_overwrite_detection(*args, **kwargs):
                (temp_dir_path / "NEW_IMG20260317131345.mp4").write_bytes(b"video")
                return "NEW_IMG20260317131345.mp4"

            with (
                patch.object(sync, "MOTION_PHOTO_DIRECT_SAVE_ONLY", False),
                patch.object(sync, "_is_motion_photo_page", return_value=True),
                patch.object(sync, "_item_looks_like_video", return_value=True),
                patch.object(sync, "_photo_image_download_url") as photo_image_mock,
                patch.object(
                    sync, "_start_download_with_keyboard_shortcut", return_value=True
                ),
                patch.object(
                    sync,
                    "_wait_for_download_start",
                    return_value=True,
                ),
                patch.object(
                    sync,
                    "_find_completed_download_with_overwrite_detection",
                    side_effect=fake_find_completed_download_with_overwrite_detection,
                ),
                patch.object(sync, "_local_album_google_id_files", return_value=({}, [])),
                patch.object(
                    sync, "_local_album_files_by_normalized_name", return_value=({}, [])
                ),
                patch.object(sync, "_record_google_id_file"),
            ):
                downloaded, skipped, failed = sync._download_individual_album_items(
                    driver,
                    [
                        {
                            "google_id": "AF1Qip-video",
                            "url": item_url,
                            "identifiers": "Video - Landscape - NEW_IMG20260317131345.mp4",
                        }
                    ],
                    "Album",
                    output_path,
                    temp_dir_path,
                )

        self.assertEqual((downloaded, skipped, failed), (1, 0, 0))
        photo_image_mock.assert_not_called()

    def test_existing_plain_filename_is_reused_before_download(self):
        driver = FakeDriver()
        item_url = "https://photos.google.com/photo/AF1Qip-current"

        with (
            tempfile.TemporaryDirectory() as output_dir,
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            output_path = Path(output_dir)
            temp_dir_path = Path(temp_dir)
            album_dir = output_path / "Album"
            album_dir.mkdir(parents=True, exist_ok=True)
            existing_file = album_dir / "IMG20260317110022_01.jpg"
            existing_file.write_bytes(b"existing image")

            with (
                patch.object(sync, "MOTION_PHOTO_DIRECT_SAVE_ONLY", False),
                patch.object(sync, "_local_album_google_id_files", return_value=({"af1qip-existing": [existing_file]}, [])),
                patch.object(sync, "_record_google_id_file") as record_mock,
                patch.object(sync, "_start_download_with_keyboard_shortcut", side_effect=AssertionError("download should not start")),
                patch.object(sync, "_download_motion_photo_still", side_effect=AssertionError("fallback should not run")),
            ):
                downloaded, skipped, failed = sync._download_individual_album_items(
                    driver,
                    [
                        {
                            "google_id": "AF1Qip-current",
                            "url": item_url,
                            "identifiers": "IMG20260317110022_01.jpg",
                        }
                    ],
                    "Album",
                    output_path,
                    temp_dir_path,
                )

        self.assertEqual((downloaded, skipped, failed), (0, 1, 0))
        record_mock.assert_called_once()

    def test_motion_photo_fallback_reuses_existing_downloaded_filename(self):
        driver = FakeDriver()
        item_url = "https://photos.google.com/photo/AF1Qip-motion"

        with (
            tempfile.TemporaryDirectory() as output_dir,
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            output_path = Path(output_dir)
            temp_dir_path = Path(temp_dir)
            album_dir = output_path / "Album"
            album_dir.mkdir(parents=True, exist_ok=True)
            existing_file = album_dir / "IMG20260317110022_01.jpg"
            existing_file.write_bytes(b"existing image")

            def fake_download_motion_photo_still(*args, **kwargs):
                (temp_dir_path / "IMG20260317110022_01.jpg").write_bytes(
                    b"duplicate image"
                )
                return "IMG20260317110022_01.jpg"

            with (
                patch.object(sync, "MOTION_PHOTO_DIRECT_SAVE_ONLY", True),
                patch.object(sync, "_is_motion_photo_page", return_value=True),
                patch.object(
                    sync, "_photo_image_download_url", return_value="stale-url"
                ),
                patch.object(
                    sync,
                    "_download_motion_photo_still",
                    side_effect=fake_download_motion_photo_still,
                ),
                patch.object(sync, "_record_google_id_file") as record_mock,
            ):
                downloaded, skipped, failed = sync._download_individual_album_items(
                    driver,
                    [
                        {
                            "google_id": "AF1Qip-motion",
                            "url": item_url,
                            "identifiers": "Motion photo - Landscape - Mar 17, 2026, 1:13:45 PM",
                        }
                    ],
                    "Album",
                    output_path,
                    temp_dir_path,
                )

        self.assertEqual((downloaded, skipped, failed), (0, 1, 0))
        record_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
