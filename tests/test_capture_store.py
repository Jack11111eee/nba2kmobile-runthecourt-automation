from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from rtc_bot.capture_store import CaptureStore


class CaptureStoreTests(unittest.TestCase):
    def test_save_writes_png_and_returns_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            store = CaptureStore(directory, max_bytes=1024)

            path = store.save(Image.new("RGB", (2, 2), "red"), "frame")

            self.assertEqual(directory / "frame.png", path)
            self.assertTrue(path.is_file())
            with Image.open(path) as saved:
                self.assertEqual("PNG", saved.format)

    def test_save_removes_oldest_png_when_directory_exceeds_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            image = Image.new("RGB", (2, 2), "red")
            oldest = directory / "oldest.png"
            newer = directory / "newer.png"
            image.save(oldest, format="PNG")
            image.save(newer, format="PNG")
            os.utime(oldest, (100, 100))
            os.utime(newer, (200, 200))
            store = CaptureStore(directory, max_bytes=oldest.stat().st_size * 2)

            latest = store.save(image, "latest")

            self.assertFalse(oldest.exists())
            self.assertTrue(newer.exists())
            self.assertTrue(latest.exists())

    def test_save_keeps_latest_png_when_it_alone_exceeds_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            oldest = directory / "oldest.png"
            Image.new("RGB", (2, 2), "red").save(oldest, format="PNG")
            store = CaptureStore(directory, max_bytes=1)

            latest = store.save(Image.new("RGB", (20, 20), "blue"), "latest")

            self.assertFalse(oldest.exists())
            self.assertTrue(latest.exists())
            self.assertGreater(latest.stat().st_size, store.max_bytes)

    def test_statistics_count_session_writes_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = CaptureStore(Path(temporary_directory), max_bytes=1024)
            self.assertEqual(0, store.written_count)
            self.assertEqual(0, store.written_bytes)

            first = store.save(Image.new("RGB", (2, 2), "red"), "first")
            second = store.save(Image.new("RGB", (3, 3), "blue"), "second")

            self.assertEqual(2, store.written_count)
            self.assertEqual(
                first.stat().st_size + second.stat().st_size,
                store.written_bytes,
            )

    def test_max_bytes_must_be_positive(self) -> None:
        for max_bytes in (0, -1):
            with self.subTest(max_bytes=max_bytes):
                with self.assertRaises(ValueError):
                    CaptureStore(Path("captures"), max_bytes=max_bytes)

    def test_cleanup_ignores_file_that_disappeared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            oldest = directory / "oldest.png"
            Image.new("RGB", (2, 2), "red").save(oldest, format="PNG")
            os.utime(oldest, (100, 100))
            store = CaptureStore(directory, max_bytes=1)

            with patch.object(Path, "unlink", side_effect=FileNotFoundError):
                latest = store.save(
                    Image.new("RGB", (2, 2), "blue"),
                    "latest",
                )

            self.assertTrue(latest.exists())

    def test_cleanup_propagates_other_file_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            oldest = directory / "oldest.png"
            Image.new("RGB", (2, 2), "red").save(oldest, format="PNG")
            os.utime(oldest, (100, 100))
            store = CaptureStore(directory, max_bytes=1)

            with patch.object(Path, "unlink", side_effect=PermissionError):
                with self.assertRaises(PermissionError):
                    store.save(Image.new("RGB", (2, 2), "blue"), "latest")


if __name__ == "__main__":
    unittest.main()
