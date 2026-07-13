from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BotConfig:
    capture_interval_seconds: float = 0.5
    stable_frames: int = 2
    post_click_cooldown_seconds: float = 1.5
    reward_auto_wait_seconds: float = 5.0
    pack_settle_wait_seconds: float = 4.0
    pack_debug_snapshot_interval_seconds: float = 5.0
    unknown_snapshot_interval_seconds: float = 60.0
    frame_change_threshold: int = 8
    state_distance_threshold: float = 0.24
    minimum_action_confidence: float = 0.45
    pack_fallback_minimum_confidence: float = 0.60
    capture_limit_bytes: int = 256 * 1024 * 1024
    mirror_bundle_id: str = "com.apple.ScreenContinuity"
    mirror_owner_name: str = "iPhone Mirroring"
    runtime_dir: Path = Path("runtime")

    @property
    def logs_dir(self) -> Path:
        return self.runtime_dir / "logs"

    @property
    def captures_dir(self) -> Path:
        return self.runtime_dir / "captures"

    @property
    def doctor_dir(self) -> Path:
        return self.runtime_dir / "doctor"

    @property
    def reports_dir(self) -> Path:
        return self.runtime_dir / "reports"
