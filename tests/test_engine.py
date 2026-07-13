from __future__ import annotations

import unittest

from rtc_bot.config import BotConfig
from rtc_bot.engine import DecisionEngine
from rtc_bot.model import (
    ActionKind,
    Detection,
    NormalizedRect,
    ScreenState,
)


def detection(
    state: ScreenState,
    signature: int,
    *,
    with_button: bool = False,
    confidence: float = 0.95,
) -> Detection:
    return Detection(
        state=state,
        confidence=confidence,
        frame_signature=signature,
        button=NormalizedRect(0.7, 0.8, 0.9, 0.9) if with_button else None,
    )


class DecisionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = BotConfig(
            stable_frames=2,
            post_click_cooldown_seconds=1.5,
            reward_auto_wait_seconds=5.0,
            pack_settle_wait_seconds=4.0,
            pack_fallback_minimum_confidence=0.60,
            frame_change_threshold=2,
        )
        self.engine = DecisionEngine(self.config)

    def test_click_requires_two_stable_frames(self) -> None:
        first = self.engine.observe(
            detection(ScreenState.LINEUP, 0b0000, with_button=True), 0.0
        )
        second = self.engine.observe(
            detection(ScreenState.LINEUP, 0b0000, with_button=True), 0.5
        )
        self.assertEqual(ActionKind.WAIT, first.kind)
        self.assertEqual(ActionKind.CLICK, second.kind)

    def test_same_frame_cannot_be_clicked_twice(self) -> None:
        self.engine.observe(
            detection(ScreenState.VS_READY, 0b0000, with_button=True), 0.0
        )
        click = self.engine.observe(
            detection(ScreenState.VS_READY, 0b0000, with_button=True), 0.5
        )
        blocked = self.engine.observe(
            detection(ScreenState.VS_READY, 0b0000, with_button=True), 3.0
        )
        self.assertEqual(ActionKind.CLICK, click.kind)
        self.assertEqual(ActionKind.WAIT, blocked.kind)
        self.assertIn("waiting to leave", blocked.reason)

    def test_low_confidence_action_never_clicks(self) -> None:
        self.engine.observe(
            detection(
                ScreenState.VS_READY,
                0b0000,
                with_button=True,
                confidence=0.44,
            ),
            0.0,
        )
        action = self.engine.observe(
            detection(
                ScreenState.VS_READY,
                0b0000,
                with_button=True,
                confidence=0.44,
            ),
            0.5,
        )
        self.assertEqual(ActionKind.WAIT, action.kind)
        self.assertIn("confidence below threshold", action.reason)

    def test_changed_frame_unlocks_next_action(self) -> None:
        self.engine.observe(
            detection(ScreenState.STAGE_SELECT, 0b0000, with_button=True), 0.0
        )
        self.engine.observe(
            detection(ScreenState.STAGE_SELECT, 0b0000, with_button=True), 0.5
        )
        self.engine.observe(
            detection(ScreenState.VS_READY, 0b1111, with_button=True), 2.1
        )
        action = self.engine.observe(
            detection(ScreenState.VS_READY, 0b1111, with_button=True), 2.6
        )
        self.assertEqual(ActionKind.CLICK, action.kind)

    def test_reward_waits_then_fallback_clicks(self) -> None:
        self.engine.observe(detection(ScreenState.QUARTER_REWARD, 0b0011), 0.0)
        started = self.engine.observe(
            detection(ScreenState.QUARTER_REWARD, 0b0011), 0.5
        )
        waiting = self.engine.observe(
            detection(ScreenState.QUARTER_REWARD, 0b0011), 5.0
        )
        click = self.engine.observe(
            detection(ScreenState.QUARTER_REWARD, 0b0011), 5.6
        )
        self.assertEqual(ActionKind.WAIT, started.kind)
        self.assertEqual(ActionKind.WAIT, waiting.kind)
        self.assertEqual(ActionKind.CLICK, click.kind)
        self.assertEqual((0.5, 0.52), click.point)

    def test_reward_change_restarts_wait(self) -> None:
        self.engine.observe(detection(ScreenState.QUARTER_REWARD, 0b0000), 0.0)
        self.engine.observe(detection(ScreenState.QUARTER_REWARD, 0b0000), 0.5)
        changed = self.engine.observe(
            detection(ScreenState.QUARTER_REWARD, 0b1111), 5.6
        )
        self.assertEqual(ActionKind.WAIT, changed.kind)
        self.assertIn("reward changed", changed.reason)

    def test_loss_pauses(self) -> None:
        self.engine.observe(detection(ScreenState.LOSS_RESULT, 0b0000), 0.0)
        action = self.engine.observe(
            detection(ScreenState.LOSS_RESULT, 0b0000), 0.5
        )
        again = self.engine.observe(
            detection(ScreenState.GAMEPLAY, 0b1111), 1.0
        )
        self.assertEqual(ActionKind.PAUSE, action.kind)
        self.assertEqual(ActionKind.PAUSE, again.kind)

    def test_exception_states_pause_after_stable_detection(self) -> None:
        for state in (
            ScreenState.NETWORK_ERROR,
            ScreenState.ENERGY_SHORTAGE,
            ScreenState.INVENTORY_FULL,
            ScreenState.MAINTENANCE,
            ScreenState.EVENT_ENDED,
        ):
            with self.subTest(state=state):
                engine = DecisionEngine(self.config)
                first = engine.observe(detection(state, 0b0000), 0.0)
                second = engine.observe(detection(state, 0b0000), 0.5)
                self.assertEqual(ActionKind.WAIT, first.kind)
                self.assertEqual(ActionKind.PAUSE, second.kind)
                self.assertIsNone(second.point)

    def test_gameplay_and_unknown_never_click(self) -> None:
        for state in (
            ScreenState.GAMEPLAY,
            ScreenState.AUTO_SUBSTITUTION,
            ScreenState.UNKNOWN,
        ):
            engine = DecisionEngine(self.config)
            engine.observe(detection(state, 0b0000), 0.0)
            action = engine.observe(detection(state, 0b0000), 0.5)
            self.assertEqual(ActionKind.WAIT, action.kind)

    def test_settled_pack_animation_falls_back_to_continue(self) -> None:
        self.engine.observe(
            detection(ScreenState.PACK_FLIP_ANIMATION, 0b0011), 0.0
        )
        started = self.engine.observe(
            detection(ScreenState.PACK_FLIP_ANIMATION, 0b0011), 0.5
        )
        waiting = self.engine.observe(
            detection(ScreenState.PACK_FLIP_ANIMATION, 0b0011), 4.4
        )
        click = self.engine.observe(
            detection(ScreenState.PACK_FLIP_ANIMATION, 0b0011), 4.6
        )
        self.assertEqual(ActionKind.WAIT, started.kind)
        self.assertEqual(ActionKind.WAIT, waiting.kind)
        self.assertEqual(ActionKind.CLICK, click.kind)
        self.assertEqual((0.765, 0.845), click.point)

    def test_pack_animation_change_restarts_settle_wait(self) -> None:
        self.engine.observe(
            detection(ScreenState.PACK_FLIP_ANIMATION, 0b0011), 0.0
        )
        self.engine.observe(
            detection(ScreenState.PACK_FLIP_ANIMATION, 0b0011), 0.5
        )
        changed = self.engine.observe(
            detection(ScreenState.PACK_FLIP_ANIMATION, 0b0111), 4.0
        )
        waiting = self.engine.observe(
            detection(ScreenState.PACK_FLIP_ANIMATION, 0b0111), 7.9
        )
        self.assertEqual(ActionKind.WAIT, changed.kind)
        self.assertIn("animation changed", changed.reason)
        self.assertEqual(ActionKind.WAIT, waiting.kind)

    def test_low_confidence_pack_animation_never_uses_fallback(self) -> None:
        for now in (0.0, 0.5, 5.0, 10.0):
            action = self.engine.observe(
                detection(
                    ScreenState.PACK_FLIP_ANIMATION,
                    0b0011,
                    confidence=0.59,
                ),
                now,
            )
            self.assertEqual(ActionKind.WAIT, action.kind)
        self.assertIn("pack fallback confidence", action.reason)


if __name__ == "__main__":
    unittest.main()
