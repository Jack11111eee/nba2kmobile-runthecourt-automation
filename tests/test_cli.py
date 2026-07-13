from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from rtc_bot.cli import build_parser, run_loop, session_summary
from rtc_bot.config import BotConfig
from rtc_bot.model import ActionKind, Detection, PlannedAction, ScreenState
from rtc_bot.session import RunPolicy, RunSession

FIXTURES = Path(__file__).parent / "fixtures"


class FakeBridge:
    available = True

    def __init__(self, image: Image.Image) -> None:
        self.image = image
        self.click_count = 0

    def permissions(self, *, request: bool) -> SimpleNamespace:
        return SimpleNamespace(screen_capture=True, event_posting=True)

    def find_mirror_window(self) -> object:
        return object()

    def capture(self, window: object) -> SimpleNamespace:
        return SimpleNamespace(image=self.image, backend="test")

    def click(self, *args: object) -> bool:
        self.click_count += 1
        return True


class CLITests(unittest.TestCase):
    def test_run_parser_accepts_session_and_capture_limits(self) -> None:
        args = build_parser().parse_args(
            [
                "run",
                "--max-games",
                "3",
                "--max-duration",
                "12.5",
                "--stop-after-win",
                "--on-loss",
                "exit",
                "--capture-limit-mb",
                "128",
            ]
        )

        self.assertEqual(3, args.max_games)
        self.assertEqual(12.5, args.max_duration)
        self.assertTrue(args.stop_after_win)
        self.assertEqual("exit", args.on_loss)
        self.assertEqual(128.0, args.capture_limit_mb)

    def test_run_parser_uses_safe_defaults_and_rejects_zero_limits(self) -> None:
        args = build_parser().parse_args(["run"])

        self.assertIsNone(args.max_games)
        self.assertIsNone(args.max_duration)
        self.assertFalse(args.stop_after_win)
        self.assertEqual("pause", args.on_loss)
        self.assertEqual(256.0, args.capture_limit_mb)

        for option in ("--max-games", "--max-duration", "--capture-limit-mb"):
            with self.subTest(option=option):
                with (
                    redirect_stderr(StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    build_parser().parse_args(["run", option, "0"])

    def test_session_summary_serializes_enum_counters(self) -> None:
        session = RunSession(RunPolicy())
        session.observe(
            Detection(
                state=ScreenState.GAMEPLAY,
                confidence=0.9,
                frame_signature=1,
            ),
            PlannedAction(
                kind=ActionKind.WAIT,
                state=ScreenState.GAMEPLAY,
                reason="gameplay",
            ),
        )
        started_at = datetime(2026, 7, 13, tzinfo=timezone.utc)
        ended_at = datetime(2026, 7, 13, 0, 0, 5, tzinfo=timezone.utc)

        summary = session_summary(
            session,
            started_at=started_at,
            ended_at=ended_at,
            mode="live",
            stop_reason="test",
        )

        self.assertEqual(started_at, summary["started_at"])
        self.assertEqual(ended_at, summary["ended_at"])
        self.assertEqual(5.0, summary["duration_seconds"])
        self.assertEqual({"gameplay": 1}, summary["state_counts"])
        self.assertEqual({"wait": 1}, summary["action_counts"])
        self.assertEqual({}, summary["click_state_counts"])

    def test_max_games_stops_before_live_win_click_and_writes_report(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            Image.open(FIXTURES / "win_result.jpg") as source,
        ):
            bridge = FakeBridge(source.convert("RGB"))
            config = BotConfig(
                runtime_dir=Path(directory),
                capture_interval_seconds=0.001,
                capture_limit_bytes=1024 * 1024,
            )
            with (
                patch("rtc_bot.cli.MacOSBridge", return_value=bridge),
                patch("rtc_bot.cli.SleepInhibitor", return_value=nullcontext()),
                patch("rtc_bot.cli.notify"),
                redirect_stdout(StringIO()),
            ):
                exit_code = run_loop(
                    config,
                    dry_run=False,
                    debug=False,
                    policy=RunPolicy(max_games=1),
                )

            self.assertEqual(0, exit_code)
            self.assertEqual(0, bridge.click_count)
            report_path = next(config.reports_dir.glob("*.json"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(1, report["wins"])
            self.assertEqual(0, report["losses"])
            self.assertIn("maximum game count reached", report["stop_reason"])


if __name__ == "__main__":
    unittest.main()
