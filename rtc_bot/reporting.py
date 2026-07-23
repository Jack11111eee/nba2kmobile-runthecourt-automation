from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


def _local_iso(value: datetime) -> str:
    return value.astimezone().isoformat()


def write_session_report(
    summary: dict[str, Any],
    *,
    reports_dir: Path,
    log_path: Path,
    captures_written: int,
    capture_bytes_written: int,
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    started_at = summary["started_at"]
    report_path = reports_dir / (
        f"session-{started_at.astimezone():%Y%m%d-%H%M%S-%f}.json"
    )
    report = {
        "started_at": _local_iso(started_at),
        "ended_at": _local_iso(summary["ended_at"]),
        "duration_seconds": summary["duration_seconds"],
        "mode": summary["mode"],
        "stop_reason": summary["stop_reason"],
        "frames": summary["frames"],
        "state_counts": summary["state_counts"],
        "action_counts": summary["action_counts"],
        "click_state_counts": summary["click_state_counts"],
        "wins": summary["wins"],
        "losses": summary["losses"],
        "log_path": str(log_path),
        "captures_written": captures_written,
        "capture_bytes_written": capture_bytes_written,
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=reports_dir,
        prefix=f".{report_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary_path = Path(handle.name)
    os.replace(temporary_path, report_path)
    return report_path


def format_console_summary(report: dict[str, Any]) -> str:
    clicks = report["action_counts"].get("click", 0)
    return (
        f"[session] mode={report['mode']} stop={report['stop_reason']} "
        f"duration={report['duration_seconds']:.1f}s frames={report['frames']} "
        f"wins={report['wins']} losses={report['losses']} clicks={clicks} "
        f"captures={report['captures_written']} "
        f"bytes={report['capture_bytes_written']}"
    )
