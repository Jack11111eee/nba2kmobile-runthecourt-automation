from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from rtc_bot.config import BotConfig
from rtc_bot.model import ActionKind, Detection, PlannedAction, ScreenState
from rtc_bot.runtime import SessionLogger


class SessionLoggerTests(unittest.TestCase):
    def test_writes_limited_captures_logs_and_session_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = BotConfig(
                runtime_dir=Path(directory),
                capture_limit_bytes=1024 * 1024,
            )
            logger = SessionLogger(config)
            capture_path = logger.save_capture(
                Image.new("RGB", (16, 16), "blue"),
                "test",
            )
            logger.write(
                timestamp=1.0,
                detection=Detection(
                    state=ScreenState.GAMEPLAY,
                    confidence=0.9,
                    frame_signature=1,
                ),
                action=PlannedAction(
                    kind=ActionKind.WAIT,
                    state=ScreenState.GAMEPLAY,
                    reason="gameplay",
                ),
            )
            started_at = datetime(2026, 7, 13, tzinfo=timezone.utc)
            report_path = logger.write_report(
                {
                    "started_at": started_at,
                    "ended_at": started_at + timedelta(seconds=5),
                    "duration_seconds": 5.0,
                    "mode": "live",
                    "stop_reason": "test",
                    "frames": 1,
                    "state_counts": {"gameplay": 1},
                    "action_counts": {"wait": 1},
                    "click_state_counts": {},
                    "wins": 0,
                    "losses": 0,
                }
            )

            self.assertTrue(capture_path.exists())
            self.assertEqual(1, logger.captures_written)
            self.assertEqual(capture_path.stat().st_size, logger.capture_bytes_written)
            self.assertEqual(1, len(logger.log_path.read_text().splitlines()))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(str(logger.log_path), report["log_path"])
            self.assertEqual(1, report["captures_written"])
            self.assertEqual(
                logger.capture_bytes_written,
                report["capture_bytes_written"],
            )


if __name__ == "__main__":
    unittest.main()
