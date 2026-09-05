from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://www.nba2kmobile.com"


@dataclass(frozen=True)
class WebConfig:
    base_url: str = DEFAULT_BASE_URL
    runtime_dir: Path = Path("runtime") / "web"
    headless: bool = True
    login_timeout_seconds: float = 180.0
    claim_timeout_seconds: float = 60.0
    post_claim_wait_seconds: float = 3.0

    @property
    def config_path(self) -> Path:
        return self.runtime_dir / "config.json"

    @property
    def state_path(self) -> Path:
        return self.runtime_dir / "state.json"

    @property
    def logs_dir(self) -> Path:
        return self.runtime_dir / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.runtime_dir / "reports"


def load_player_id(config: WebConfig) -> str | None:
    """从环境变量或本地 config.json 读取 Player ID（两者均不进 git）。"""
    env = os.environ.get("NBA2K_PLAYER_ID")
    if env and env.strip():
        return env.strip()
    try:
        data = json.loads(config.config_path.read_text(encoding="utf-8"))
        value = data.get("player_id")
    except (ValueError, OSError):
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def save_player_id(config: WebConfig, player_id: str) -> None:
    """把 Player ID 写入本地 config.json，供后续无头运行使用。"""
    config.config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(config.config_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        data = {}
    data["player_id"] = player_id
    config.config_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
