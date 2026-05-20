import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gp_dl import sync
from gp_dl.manifest import GOOGLE_ID_MANIFEST_FILENAME


class ChunkedAlbumSyncTests(unittest.TestCase):
    def test_missing_items_are_processed_in_100_item_chunks(self):
        with tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(output_dir)
            temp_dir_path = Path(temp_dir)
            album_title = "Album"
            album_dir = output_path / album_title
            album_dir.mkdir(parents=True, exist_ok=True)
            (album_dir / GOOGLE_ID_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")

            batch1 = [
                {
                    "google_id": f"id-{index}",
                    "url": f"https://photos.google.com/photo/id-{index}",
                    "identifiers": f"file-{index}.jpg",
                }
                for index in range(100)
            ]
            batch2 = [
                {
                    "google_id": f"id-{index}",
                    "url": f"https://photos.google.com/photo/id-{index}",
                    "identifiers": f"file-{index}.jpg",
                }
                for index in range(100, 200)
            ]
            batch3 = [
                {
                    "google_id": f"id-{index}",
                    "url": f"https://photos.google.com/photo/id-{index}",
                    "identifiers": f"file-{index}.jpg",
                }
                for index in range(200, 205)
            ]

            collected_items = [*batch1, *batch2, *batch3]
            download_calls: list[int] = []

            def fake_download_items(*args, **kwargs):
                items = args[1]
                download_calls.append(len(items))
                return (len(items), 0, 0)

            with (
                patch.object(
                    sync,
                    "_collect_album_photo_items",
                    side_effect=[batch1, batch2, batch3],
                ),
                patch.object(sync, "_album_output_dirs", return_value=[album_dir]),
                patch.object(sync, "_ensure_album_manifest_mappings"),
                patch.object(sync, "_local_album_google_id_files", return_value=({}, [album_dir])),
                patch.object(sync, "_propagate_album_deletes", return_value=0),
                patch.object(sync, "_rewrite_full_album_manifest"),
                patch.object(sync, "_cleanup_bootstrap_plain_duplicates"),
                patch.object(sync, "_download_individual_album_items", side_effect=fake_download_items),
            ):
                handled, downloaded, skipped, failed, item_count, deleted = (
                    sync._download_missing_album_items_by_google_id(
                        driver=object(),
                        album_title=album_title,
                        output_path=output_path,
                        temp_dir_path=temp_dir_path,
                        propagate_deletes=False,
                    )
                )

            self.assertTrue(handled)
            self.assertEqual(download_calls, [100, 100, 5])
            self.assertEqual(downloaded, len(collected_items))
            self.assertEqual(skipped, 0)
            self.assertEqual(failed, 0)
            self.assertEqual(item_count, len(collected_items))
            self.assertEqual(deleted, 0)


if __name__ == "__main__":
    unittest.main()
