from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from rtc_bot.reporting import format_console_summary, write_session_report


def session_summary() -> dict[str, object]:
    return {
        "started_at": datetime(2026, 7, 13, 1, 2, 3, tzinfo=timezone.utc),
        "ended_at": datetime(2026, 7, 13, 1, 4, 8, tzinfo=timezone.utc),
        "duration_seconds": 125.0,
        "mode": "dry-run",
        "stop_reason": "max-duration",
        "frames": 250,
        "state_counts": {"gameplay": 240, "win_result": 10},
        "action_counts": {"wait": 248, "click": 2},
        "click_state_counts": {"win_result": 2},
        "wins": 1,
        "losses": 0,
    }


class SessionReportingTests(unittest.TestCase):
    def test_writes_complete_session_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = Path(directory)
            log_path = runtime_dir / "logs" / "run.jsonl"
            summary = session_summary()

            report_path = write_session_report(
                summary,
                reports_dir=runtime_dir / "reports",
                log_path=log_path,
                captures_written=3,
                capture_bytes_written=4096,
            )

            report = json.loads(report_path.read_text(encoding="utf-8"))
            expected_started_at = summary["started_at"].astimezone().isoformat()
            expected_ended_at = summary["ended_at"].astimezone().isoformat()
            self.assertEqual(expected_started_at, report["started_at"])
            self.assertEqual(expected_ended_at, report["ended_at"])
            self.assertEqual(125.0, report["duration_seconds"])
            self.assertEqual("dry-run", report["mode"])
            self.assertEqual("max-duration", report["stop_reason"])
            self.assertEqual(250, report["frames"])
            self.assertEqual(summary["state_counts"], report["state_counts"])
            self.assertEqual(summary["action_counts"], report["action_counts"])
            self.assertEqual(
                summary["click_state_counts"], report["click_state_counts"]
            )
            self.assertEqual(1, report["wins"])
            self.assertEqual(0, report["losses"])
            self.assertEqual(str(log_path), report["log_path"])
            self.assertEqual(3, report["captures_written"])
            self.assertEqual(4096, report["capture_bytes_written"])

    def test_atomically_replaces_report_from_same_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reports_dir = Path(directory) / "reports"

            with patch("os.replace", wraps=os.replace) as replace:
                report_path = write_session_report(
                    session_summary(),
                    reports_dir=reports_dir,
                    log_path=Path(directory) / "run.jsonl",
                    captures_written=0,
                    capture_bytes_written=0,
                )

            replace.assert_called_once()
            temporary_path, destination_path = replace.call_args.args
            self.assertEqual(reports_dir, Path(temporary_path).parent)
            self.assertEqual(report_path, Path(destination_path))
            self.assertFalse(Path(temporary_path).exists())

    def test_formats_short_console_summary(self) -> None:
        report = {
            **session_summary(),
            "captures_written": 3,
            "capture_bytes_written": 4096,
        }

        message = format_console_summary(report)

        self.assertEqual(
            "[session] mode=dry-run stop=max-duration duration=125.0s "
            "frames=250 wins=1 losses=0 clicks=2 captures=3 bytes=4096",
            message,
        )


if __name__ == "__main__":
    unittest.main()
