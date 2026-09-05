from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from nba2k_web.config import WebConfig


class ClaimLogger:
    def __init__(self, config: WebConfig) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        config.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = config.logs_dir / f"claim-{stamp}.jsonl"

    def write(self, entry: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_report(config: WebConfig, summary: dict[str, Any]) -> Path:
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone()
    report_path = config.reports_dir / f"claim-{stamp:%Y%m%d-%H%M%S-%f}.json"
    payload = {
        "started_at": summary["started_at"],
        "ended_at": summary["ended_at"],
        "claimed": summary["claimed"],
        "failed": summary["failed"],
        "outcomes": summary["outcomes"],
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=config.reports_dir,
        prefix=f".{report_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary_path = Path(handle.name)
    os.replace(temporary_path, report_path)
    return report_path
