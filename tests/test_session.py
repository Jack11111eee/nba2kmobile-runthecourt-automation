from __future__ import annotations

import unittest

from rtc_bot.model import ActionKind, Detection, PlannedAction, ScreenState
from rtc_bot.session import RunPolicy, RunSession


class MutableClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def detection(state: ScreenState) -> Detection:
    return Detection(
        state=state,
        confidence=0.95,
        frame_signature=0,
    )


def action(
    kind: ActionKind,
    state: ScreenState,
    reason: str = "engine",
) -> PlannedAction:
    return PlannedAction(kind=kind, state=state, reason=reason)


class RunSessionTests(unittest.TestCase):
    def test_tracks_frames_states_and_final_actions(self) -> None:
        clock = MutableClock()
        session = RunSession(RunPolicy(), clock=clock)
        planned = action(ActionKind.WAIT, ScreenState.GAMEPLAY)

        decision = session.observe(detection(ScreenState.GAMEPLAY), planned)

        self.assertFalse(decision.should_stop)
        self.assertIsNone(decision.exit_code)
        self.assertEqual(planned, decision.final_action)
        self.assertEqual("engine", decision.reason)
        self.assertEqual(1, session.frames_seen)
        self.assertEqual(1, session.state_counts[ScreenState.GAMEPLAY])
        self.assertEqual(1, session.action_counts[ActionKind.WAIT])
        self.assertEqual(0, session.click_state_counts[ScreenState.GAMEPLAY])

    def test_counts_each_game_result_once(self) -> None:
        session = RunSession(RunPolicy(), clock=MutableClock())

        session.observe(
            detection(ScreenState.WIN_RESULT),
            action(ActionKind.WAIT, ScreenState.WIN_RESULT),
        )
        session.observe(
            detection(ScreenState.WIN_RESULT),
            action(ActionKind.CLICK, ScreenState.WIN_RESULT),
        )
        session.observe(
            detection(ScreenState.PACK_OPEN),
            action(ActionKind.WAIT, ScreenState.PACK_OPEN),
        )
        session.observe(
            detection(ScreenState.WIN_RESULT),
            action(ActionKind.CLICK, ScreenState.WIN_RESULT),
        )

        self.assertEqual(1, session.wins)
        self.assertEqual(0, session.losses)
        self.assertEqual(1, session.games_completed)

        session.observe(
            detection(ScreenState.GAMEPLAY),
            action(ActionKind.WAIT, ScreenState.GAMEPLAY),
        )
        session.observe(
            detection(ScreenState.LOSS_RESULT),
            action(ActionKind.PAUSE, ScreenState.LOSS_RESULT),
        )

        self.assertEqual(1, session.wins)
        self.assertEqual(1, session.losses)
        self.assertEqual(2, session.games_completed)

    def test_unstable_result_frames_are_not_counted(self) -> None:
        session = RunSession(
            RunPolicy(max_games=1, stop_after_win=True),
            clock=MutableClock(),
        )

        win = session.observe(
            detection(ScreenState.WIN_RESULT),
            action(ActionKind.WAIT, ScreenState.WIN_RESULT),
        )
        loss = session.observe(
            detection(ScreenState.LOSS_RESULT),
            action(ActionKind.WAIT, ScreenState.LOSS_RESULT),
        )

        self.assertFalse(win.should_stop)
        self.assertFalse(loss.should_stop)
        self.assertEqual(0, session.games_completed)

    def test_stops_before_clicking_when_max_games_is_reached(self) -> None:
        session = RunSession(RunPolicy(max_games=1), clock=MutableClock())

        decision = session.observe(
            detection(ScreenState.WIN_RESULT),
            action(ActionKind.CLICK, ScreenState.WIN_RESULT),
        )

        self.assertTrue(decision.should_stop)
        self.assertEqual(0, decision.exit_code)
        self.assertEqual(ActionKind.PAUSE, decision.final_action.kind)
        self.assertEqual(ScreenState.WIN_RESULT, decision.final_action.state)
        self.assertIn("maximum game count reached", decision.reason)
        self.assertEqual(1, session.action_counts[ActionKind.PAUSE])
        self.assertEqual(0, session.action_counts[ActionKind.CLICK])

    def test_stops_at_the_configured_duration_using_an_injected_clock(self) -> None:
        clock = MutableClock(100.0)
        session = RunSession(
            RunPolicy(max_duration_seconds=10.0),
            clock=clock,
        )

        clock.now = 109.9
        before_limit = session.observe(
            detection(ScreenState.GAMEPLAY),
            action(ActionKind.WAIT, ScreenState.GAMEPLAY),
        )
        clock.now = 110.0
        at_limit = session.observe(
            detection(ScreenState.LINEUP),
            action(ActionKind.CLICK, ScreenState.LINEUP),
        )

        self.assertFalse(before_limit.should_stop)
        self.assertTrue(at_limit.should_stop)
        self.assertEqual(0, at_limit.exit_code)
        self.assertEqual(ActionKind.PAUSE, at_limit.final_action.kind)
        self.assertIn("maximum duration reached", at_limit.reason)
        self.assertEqual(10.0, session.elapsed_seconds)

    def test_duration_can_stop_without_observing_another_frame(self) -> None:
        clock = MutableClock(100.0)
        session = RunSession(
            RunPolicy(max_duration_seconds=10.0),
            clock=clock,
        )

        clock.now = 110.0
        decision = session.check_time_limit()

        assert decision is not None
        self.assertTrue(decision.should_stop)
        self.assertEqual(0, decision.exit_code)
        self.assertEqual(ScreenState.UNKNOWN, decision.final_action.state)
        self.assertEqual(0, session.frames_seen)
        self.assertEqual(1, session.action_counts[ActionKind.PAUSE])

    def test_stop_after_win_ends_the_session_normally(self) -> None:
        session = RunSession(RunPolicy(stop_after_win=True), clock=MutableClock())

        decision = session.observe(
            detection(ScreenState.WIN_RESULT),
            action(ActionKind.CLICK, ScreenState.WIN_RESULT),
        )

        self.assertTrue(decision.should_stop)
        self.assertEqual(0, decision.exit_code)
        self.assertEqual(ActionKind.PAUSE, decision.final_action.kind)
        self.assertIn("stop after win", decision.reason)

    def test_loss_pause_policy_latches_a_pause_without_exiting(self) -> None:
        session = RunSession(RunPolicy(on_loss="pause"), clock=MutableClock())

        loss = session.observe(
            detection(ScreenState.LOSS_RESULT),
            action(ActionKind.PAUSE, ScreenState.LOSS_RESULT),
        )
        later = session.observe(
            detection(ScreenState.GAMEPLAY),
            action(ActionKind.CLICK, ScreenState.GAMEPLAY),
        )

        self.assertFalse(loss.should_stop)
        self.assertIsNone(loss.exit_code)
        self.assertEqual(ActionKind.PAUSE, loss.final_action.kind)
        self.assertIn("paused after loss", loss.reason)
        self.assertFalse(later.should_stop)
        self.assertEqual(ActionKind.PAUSE, later.final_action.kind)
        self.assertEqual(loss.reason, later.reason)
        self.assertEqual(2, session.action_counts[ActionKind.PAUSE])
        self.assertEqual(0, session.action_counts[ActionKind.CLICK])

    def test_loss_exit_policy_stops_with_a_distinct_exit_code(self) -> None:
        session = RunSession(RunPolicy(on_loss="exit"), clock=MutableClock())

        decision = session.observe(
            detection(ScreenState.LOSS_RESULT),
            action(ActionKind.PAUSE, ScreenState.LOSS_RESULT),
        )

        self.assertTrue(decision.should_stop)
        self.assertEqual(1, decision.exit_code)
        self.assertEqual(ActionKind.PAUSE, decision.final_action.kind)
        self.assertIn("exit after loss", decision.reason)
        self.assertEqual(1, session.losses)
        self.assertEqual(1, session.action_counts[ActionKind.PAUSE])
        self.assertEqual(0, session.action_counts[ActionKind.CLICK])

    def test_exception_pause_stops_with_a_distinct_exit_code(self) -> None:
        session = RunSession(RunPolicy(), clock=MutableClock())

        decision = session.observe(
            detection(ScreenState.NETWORK_ERROR),
            action(
                ActionKind.PAUSE,
                ScreenState.NETWORK_ERROR,
                "recognized stop state: network_error",
            ),
        )

        self.assertTrue(decision.should_stop)
        self.assertEqual(3, decision.exit_code)
        self.assertEqual(ActionKind.PAUSE, decision.final_action.kind)
        self.assertEqual(
            "recognized stop state: network_error",
            decision.reason,
        )

    def test_policy_rejects_invalid_limits_and_loss_behavior(self) -> None:
        invalid_policies = (
            {"max_games": 0},
            {"max_duration_seconds": 0.0},
            {"on_loss": "ignore"},
        )

        for values in invalid_policies:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    RunPolicy(**values)


if __name__ == "__main__":
    unittest.main()
