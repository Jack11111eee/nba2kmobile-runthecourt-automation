from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from rtc_bot.config import BotConfig
from rtc_bot.model import ScreenState
from rtc_bot.vision import ScreenDetector, find_content_rect

FIXTURES = Path(__file__).parent / "fixtures"


class ScreenDetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.detector = ScreenDetector(BotConfig())

    def assert_fixture(
        self,
        filename: str,
        expected_state: ScreenState,
        *,
        expects_button: bool,
    ) -> None:
        with Image.open(FIXTURES / filename) as image:
            detection = self.detector.detect(image.convert("RGB"))
        self.assertEqual(expected_state, detection.state, detection.reason)
        if expects_button:
            self.assertIsNotNone(detection.button, detection.reason)
            assert detection.button is not None
            x, y = detection.button.center
            self.assertGreaterEqual(x, 0.1)
            self.assertLessEqual(x, 0.95)
            self.assertGreaterEqual(y, 0.75)
            self.assertLessEqual(y, 0.95)
        else:
            self.assertIsNone(detection.button)

    def test_known_action_screens(self) -> None:
        cases = [
            ("event_home.jpg", ScreenState.EVENT_HOME),
            ("stage_select.jpg", ScreenState.STAGE_SELECT),
            ("stage_select_2.jpg", ScreenState.STAGE_SELECT),
            ("vs_ready.jpg", ScreenState.VS_READY),
            ("vs_ready_2.jpg", ScreenState.VS_READY),
            ("lineup.jpg", ScreenState.LINEUP),
            ("lineup_2.jpg", ScreenState.LINEUP),
            ("lineup_3.jpg", ScreenState.LINEUP),
            ("win_result.jpg", ScreenState.WIN_RESULT),
            ("pack_reveal.jpg", ScreenState.PACK_REVEAL),
            ("pack_summary.jpg", ScreenState.PACK_SUMMARY),
        ]
        for filename, state in cases:
            with self.subTest(filename=filename):
                self.assert_fixture(filename, state, expects_button=True)

    def test_non_action_screens(self) -> None:
        cases = [
            ("gameplay.jpg", ScreenState.GAMEPLAY),
            ("quarter_reward.jpg", ScreenState.QUARTER_REWARD),
            ("quarter_reward_2.jpg", ScreenState.QUARTER_REWARD),
            ("quarter_reward_3.jpg", ScreenState.QUARTER_REWARD),
        ]
        for filename, state in cases:
            with self.subTest(filename=filename):
                self.assert_fixture(filename, state, expects_button=False)

    def test_win_layout_without_win_marker_is_treated_as_loss(self) -> None:
        with Image.open(FIXTURES / "win_result.jpg") as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        width, height = image.size
        draw.rectangle(
            (
                round(width * 0.34),
                round(height * 0.24),
                round(width * 0.66),
                round(height * 0.66),
            ),
            fill=(20, 25, 35),
        )
        detection = self.detector.detect(image)
        self.assertEqual(ScreenState.LOSS_RESULT, detection.state, detection.reason)
        self.assertIsNone(detection.button)

    def test_win_anchor_overrides_team_dependent_page_match(self) -> None:
        vs_reference = next(
            reference
            for reference in self.detector.library.references
            if reference.state == ScreenState.VS_READY
        )
        with Image.open(FIXTURES / "win_result.jpg") as source:
            image = source.convert("RGB")
        with patch.object(
            self.detector.library,
            "nearest",
            return_value=(vs_reference, 0.12),
        ):
            detection = self.detector.detect(image)
        self.assertEqual(ScreenState.WIN_RESULT, detection.state, detection.reason)
        self.assertIsNotNone(detection.button, detection.reason)

    def test_tight_win_anchor_ignores_vs_like_surroundings(self) -> None:
        vs_reference = next(
            reference
            for reference in self.detector.library.references
            if reference.state == ScreenState.VS_READY
        )
        with Image.open(FIXTURES / "vs_ready.jpg") as vs_source:
            image = vs_source.convert("RGB")
        with Image.open(FIXTURES / "win_result.jpg") as win_source:
            win_image = win_source.convert("RGB")

        width, height = image.size
        anchor_box = (
            round(width * 0.40),
            round(height * 0.34),
            round(width * 0.60),
            round(height * 0.60),
        )
        image.paste(win_image.crop(anchor_box), anchor_box[:2])

        with patch.object(
            self.detector.library,
            "nearest",
            return_value=(vs_reference, 0.08),
        ):
            detection = self.detector.detect(image)
        self.assertEqual(ScreenState.WIN_RESULT, detection.state, detection.reason)
        self.assertIsNotNone(detection.button, detection.reason)

    def test_lineup_cannot_become_reward_fallback_click(self) -> None:
        reward_reference = next(
            reference
            for reference in self.detector.library.references
            if reference.state == ScreenState.QUARTER_REWARD
        )
        with Image.open(FIXTURES / "lineup.jpg") as source:
            image = source.convert("RGB")
        with patch.object(
            self.detector.library,
            "nearest",
            return_value=(reward_reference, 0.12),
        ):
            detection = self.detector.detect(image)
        self.assertEqual(
            ScreenState.AUTO_SUBSTITUTION, detection.state, detection.reason
        )
        self.assertIsNone(detection.button)

    def test_content_rect_bottom_aligns_window_chrome(self) -> None:
        image = Image.new("RGB", (960, 500))
        rect = find_content_rect(image)
        self.assertEqual(960, rect.width)
        self.assertEqual(443, rect.height)
        self.assertEqual(57, rect.top)
        self.assertEqual(500, rect.bottom)

    def test_blue_gameplay_frames_never_expose_action_buttons(self) -> None:
        for filename in ("gameplay_transition.png", "gameplay_blue.png"):
            with self.subTest(filename=filename):
                with Image.open(FIXTURES / filename) as image:
                    detection = self.detector.detect(image.convert("RGB"))
                self.assertIsNone(detection.button, detection.reason)

    def test_pack_animation_waits_until_show_all_button_appears(self) -> None:
        with Image.open(FIXTURES / "pack_reveal_animation.png") as image:
            detection = self.detector.detect(image.convert("RGB"))
        self.assertEqual(
            ScreenState.PACK_FLIP_ANIMATION,
            detection.state,
            detection.reason,
        )
        self.assertIsNone(detection.button, detection.reason)

    def test_pack_open_prompt_clicks_pack_center(self) -> None:
        with Image.open(FIXTURES / "pack_open.jpg") as image:
            detection = self.detector.detect(image.convert("RGB"))
        self.assertEqual(ScreenState.PACK_OPEN, detection.state, detection.reason)
        self.assertIsNotNone(detection.button, detection.reason)
        assert detection.button is not None
        x, y = detection.button.center
        self.assertAlmostEqual(0.5, x, places=2)
        self.assertAlmostEqual(0.515, y, places=2)

    def test_non_red_pack_open_prompt_clicks_pack_center(self) -> None:
        with Image.open(FIXTURES / "pack_open_ad.png") as image:
            detection = self.detector.detect(image.convert("RGB"))
        self.assertEqual(ScreenState.PACK_OPEN, detection.state, detection.reason)
        self.assertGreaterEqual(detection.confidence, 0.45, detection.reason)
        self.assertIsNotNone(detection.button, detection.reason)
        assert detection.button is not None
        self.assertEqual((0.5, 0.515), detection.button.center)

    def test_game_transitions_cannot_expose_pack_open_click(self) -> None:
        for filename in (
            "pack_false_positive_overlay.png",
            "pack_false_positive_transition.png",
        ):
            with self.subTest(filename=filename):
                with Image.open(FIXTURES / filename) as image:
                    detection = self.detector.detect(image.convert("RGB"))
                self.assertIsNone(detection.button, detection.reason)

    def test_right_continue_button_overrides_pack_reveal_page_match(self) -> None:
        reveal_reference = next(
            reference
            for reference in self.detector.library.references
            if reference.state == ScreenState.PACK_REVEAL
        )
        with Image.open(FIXTURES / "pack_summary.jpg") as source:
            image = source.convert("RGB")
        with patch.object(
            self.detector.library,
            "nearest",
            return_value=(reveal_reference, 0.08),
        ):
            detection = self.detector.detect(image)
        self.assertEqual(ScreenState.PACK_SUMMARY, detection.state, detection.reason)
        self.assertIsNotNone(detection.button, detection.reason)
        assert detection.button is not None
        self.assertGreater(detection.button.center[0], 0.65)

    def test_scaled_frame_with_window_chrome_keeps_state_and_button(self) -> None:
        with Image.open(FIXTURES / "stage_select.jpg") as source:
            scaled = source.convert("RGB").resize((960, 443))
        window = Image.new("RGB", (960, 500), (38, 38, 40))
        window.paste(scaled, (0, 57))
        detection = self.detector.detect(window)
        self.assertEqual(ScreenState.STAGE_SELECT, detection.state, detection.reason)
        self.assertIsNotNone(detection.button, detection.reason)
        assert detection.button is not None
        self.assertAlmostEqual(0.319, detection.button.center[0], places=2)


if __name__ == "__main__":
    unittest.main()
