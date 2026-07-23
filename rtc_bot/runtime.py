from __future__ import annotations

import json
import subprocess
import sys
from contextlib import AbstractContextManager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from rtc_bot.capture_store import CaptureStore
from rtc_bot.config import BotConfig
from rtc_bot.model import Detection, PlannedAction
from rtc_bot.reporting import write_session_report


class SessionLogger:
    def __init__(self, config: BotConfig) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        config.logs_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.log_path = config.logs_dir / f"run-{stamp}.jsonl"
        self.last_unknown_snapshot_at = float("-inf")
        self.capture_store = CaptureStore(
            config.captures_dir,
            max_bytes=config.capture_limit_bytes,
        )

    @property
    def captures_written(self) -> int:
        return self.capture_store.written_count

    @property
    def capture_bytes_written(self) -> int:
        return self.capture_store.written_bytes

    def write(
        self,
        *,
        timestamp: float,
        detection: Detection,
        action: PlannedAction,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "timestamp": timestamp,
            "detection": asdict(detection),
            "action": asdict(action),
        }
        if extra:
            payload.update(extra)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def save_capture(self, image: Image.Image, label: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        return self.capture_store.save(image, f"{stamp}-{label}")

    def write_report(self, summary: dict[str, Any]) -> Path:
        return write_session_report(
            summary,
            reports_dir=self.config.reports_dir,
            log_path=self.log_path,
            captures_written=self.captures_written,
            capture_bytes_written=self.capture_bytes_written,
        )


def notify(title: str, message: str) -> None:
    if sys.platform == "win32":
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except (ImportError, RuntimeError):
            pass
        return
    if sys.platform != "darwin":
        return
    escaped_title = title.replace('"', '\\"')
    escaped_message = message.replace('"', '\\"')
    script = f'display notification "{escaped_message}" with title "{escaped_title}"'
    subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class SleepInhibitor(AbstractContextManager["SleepInhibitor"]):
    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self.windows_active = False

    def __enter__(self) -> "SleepInhibitor":
        if sys.platform == "win32":
            import ctypes

            continuous = 0x80000000
            system_required = 0x00000001
            display_required = 0x00000002
            result = ctypes.windll.kernel32.SetThreadExecutionState(
                continuous | system_required | display_required
            )
            self.windows_active = bool(result)
        elif sys.platform == "darwin":
            self.process = subprocess.Popen(
                ["/usr/bin/caffeinate", "-dimsu"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return self

    def __exit__(self, *args: object) -> None:
        if self.windows_active:
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            self.windows_active = False
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
