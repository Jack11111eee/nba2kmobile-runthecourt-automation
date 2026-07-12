from __future__ import annotations

import json
import subprocess
from contextlib import AbstractContextManager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from rtc_bot.config import BotConfig
from rtc_bot.model import Detection, PlannedAction


class SessionLogger:
    def __init__(self, config: BotConfig) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        config.logs_dir.mkdir(parents=True, exist_ok=True)
        config.captures_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.log_path = config.logs_dir / f"run-{stamp}.jsonl"
        self.last_unknown_snapshot_at = float("-inf")

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
        path = self.config.captures_dir / f"{stamp}-{label}.png"
        image.save(path)
        return path


def notify(title: str, message: str) -> None:
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

    def __enter__(self) -> "SleepInhibitor":
        self.process = subprocess.Popen(
            ["/usr/bin/caffeinate", "-dimsu"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self

    def __exit__(self, *args: object) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
