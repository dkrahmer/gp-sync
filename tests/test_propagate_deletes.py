import json
import tempfile
import unittest
from pathlib import Path

from gp_sync import sync
from gp_sync.manifest import GOOGLE_ID_MANIFEST_FILENAME, _load_google_id_manifest


class PropagateDeletesTests(unittest.TestCase):
    def test_deletes_manifest_mapped_file_missing_from_album(self):
        google_id = "AF1QipDeleted"
        with tempfile.TemporaryDirectory() as output_dir:
            output_path = Path(output_dir)
            album_dir = output_path / "Vacation"
            album_dir.mkdir()
            local_file = album_dir / "photo.jpg"
            local_file.write_bytes(b"deleted photo")
            manifest_path = album_dir / GOOGLE_ID_MANIFEST_FILENAME
            manifest_path.write_text(
                json.dumps({"google_ids": {google_id: "photo.jpg"}}),
                encoding="utf-8",
            )

            deleted_count = sync._propagate_album_deletes(
                output_path,
                "Vacation",
                album_google_ids=set(),
            )

            self.assertEqual(deleted_count, 1)
            self.assertFalse(local_file.exists())
            self.assertEqual(_load_google_id_manifest(album_dir), {})

    def test_keeps_manifest_mapped_file_still_in_album(self):
        google_id = "AF1QipKept"
        with tempfile.TemporaryDirectory() as output_dir:
            output_path = Path(output_dir)
            album_dir = output_path / "Vacation"
            album_dir.mkdir()
            local_file = album_dir / "photo.jpg"
            local_file.write_bytes(b"kept photo")
            manifest_path = album_dir / GOOGLE_ID_MANIFEST_FILENAME
            manifest_path.write_text(
                json.dumps({"google_ids": {google_id: "photo.jpg"}}),
                encoding="utf-8",
            )

            deleted_count = sync._propagate_album_deletes(
                output_path,
                "Vacation",
                album_google_ids={google_id.casefold()},
            )

            self.assertEqual(deleted_count, 0)
            self.assertTrue(local_file.exists())
            self.assertEqual(
                _load_google_id_manifest(album_dir),
                {google_id: "photo.jpg"},
            )

    def test_prunes_stale_manifest_entry_when_file_already_gone(self):
        google_id = "AF1QipStale"
        with tempfile.TemporaryDirectory() as output_dir:
            output_path = Path(output_dir)
            album_dir = output_path / "Vacation"
            album_dir.mkdir()
            manifest_path = album_dir / GOOGLE_ID_MANIFEST_FILENAME
            manifest_path.write_text(
                json.dumps({"google_ids": {google_id: "missing.jpg"}}),
                encoding="utf-8",
            )

            deleted_count = sync._propagate_album_deletes(
                output_path,
                "Vacation",
                album_google_ids=set(),
            )

            self.assertEqual(deleted_count, 0)
            self.assertEqual(_load_google_id_manifest(album_dir), {})


if __name__ == "__main__":
    unittest.main()
