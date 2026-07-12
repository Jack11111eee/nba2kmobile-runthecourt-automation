from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

from rtc_bot.config import BotConfig
from rtc_bot.engine import DecisionEngine
from rtc_bot.model import ActionKind, ScreenState
from rtc_bot.vision import ScreenDetector

FIXTURES = Path(__file__).parent / "fixtures"


class RewardFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = BotConfig(
            stable_frames=2,
            post_click_cooldown_seconds=1.5,
            frame_change_threshold=2,
        )
        self.detector = ScreenDetector(self.config)
        self.engine = DecisionEngine(self.config)

    def observe_stable(self, filename: str, start: float):
        with Image.open(FIXTURES / filename) as source:
            detection = self.detector.detect(source.convert("RGB"))
        self.engine.observe(detection, start)
        return self.engine.observe(detection, start + 0.5)

    def test_complete_reward_flow_click_sequence(self) -> None:
        win = self.observe_stable("win_result.jpg", 0.0)
        self.assertEqual(ActionKind.CLICK, win.kind)
        self.assertEqual(ScreenState.WIN_RESULT, win.state)

        open_pack = self.observe_stable("pack_open_ad.png", 2.5)
        self.assertEqual(ActionKind.CLICK, open_pack.kind)
        self.assertEqual(ScreenState.PACK_OPEN, open_pack.state)
        self.assertEqual((0.5, 0.515), open_pack.point)

        show_all = self.observe_stable("pack_reveal.jpg", 5.0)
        self.assertEqual(ActionKind.CLICK, show_all.kind)
        self.assertEqual(ScreenState.PACK_REVEAL, show_all.state)

        animation = self.observe_stable("pack_flip_animation.jpg", 7.5)
        self.assertEqual(ActionKind.WAIT, animation.kind)
        self.assertEqual(ScreenState.PACK_FLIP_ANIMATION, animation.state)

        show_remaining = self.observe_stable("pack_reveal.jpg", 10.0)
        self.assertEqual(ActionKind.CLICK, show_remaining.kind)
        self.assertEqual(ScreenState.PACK_REVEAL, show_remaining.state)

        self.observe_stable("pack_flip_animation.jpg", 12.5)
        continue_action = self.observe_stable("pack_summary.jpg", 15.0)
        self.assertEqual(ActionKind.CLICK, continue_action.kind)
        self.assertEqual(ScreenState.PACK_SUMMARY, continue_action.state)
        assert continue_action.point is not None
        self.assertGreater(continue_action.point[0], 0.65)

        next_stage = self.observe_stable("stage_select_2.jpg", 17.5)
        self.assertEqual(ActionKind.CLICK, next_stage.kind)
        self.assertEqual(ScreenState.STAGE_SELECT, next_stage.state)


if __name__ == "__main__":
    unittest.main()
