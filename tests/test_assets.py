from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
ASSET_DIRS = (
    ROOT / "rtc_bot" / "assets" / "reference",
    ROOT / "tests" / "fixtures",
)


class PublicAssetTests(unittest.TestCase):
    def test_public_images_have_no_embedded_metadata(self) -> None:
        for directory in ASSET_DIRS:
            for path in sorted(directory.iterdir()):
                if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                    continue
                with self.subTest(path=path.relative_to(ROOT)):
                    with Image.open(path) as image:
                        self.assertFalse(image.getexif())
                        self.assertNotIn("comment", image.info)
                        self.assertNotIn("exif", image.info)
                        self.assertNotIn("photoshop", image.info)


if __name__ == "__main__":
    unittest.main()
