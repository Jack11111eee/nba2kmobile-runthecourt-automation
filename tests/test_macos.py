from __future__ import annotations

import unittest

from PIL import Image

from rtc_bot.macos import WindowBounds, is_nonblank, map_normalized_point
from rtc_bot.vision import ContentRect


class MacOSGeometryTests(unittest.TestCase):
    def test_maps_content_point_through_window_scale_and_chrome(self) -> None:
        bounds = WindowBounds(x=100, y=50, width=480, height=250)
        content = ContentRect(left=0, top=57, right=960, bottom=500)
        screen_x, screen_y = map_normalized_point(
            bounds,
            (960, 500),
            content,
            (0.5, 0.5),
        )
        self.assertAlmostEqual(340.0, screen_x)
        self.assertAlmostEqual(189.25, screen_y)

    def test_black_frame_is_rejected(self) -> None:
        self.assertFalse(is_nonblank(Image.new("RGB", (960, 443), "black")))

    def test_rejects_out_of_range_normalized_point(self) -> None:
        bounds = WindowBounds(x=100, y=50, width=480, height=250)
        content = ContentRect(left=0, top=57, right=960, bottom=500)
        with self.assertRaises(ValueError):
            map_normalized_point(bounds, (960, 500), content, (1.01, 0.5))

    def test_game_frame_is_nonblank(self) -> None:
        image = Image.new("RGB", (960, 443), "black")
        for x in range(200, 760):
            for y in range(100, 340):
                image.putpixel((x, y), (40, 120, 210))
        self.assertTrue(is_nonblank(image))


if __name__ == "__main__":
    unittest.main()
