from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ScreenState(StrEnum):
    EVENT_HOME = "event_home"
    STAGE_SELECT = "stage_select"
    VS_READY = "vs_ready"
    LINEUP = "lineup"
    GAMEPLAY = "gameplay"
    AUTO_SUBSTITUTION = "auto_substitution"
    QUARTER_REWARD = "quarter_reward"
    WIN_RESULT = "win_result"
    LOSS_RESULT = "loss_result"
    PACK_OPEN = "pack_open"
    PACK_REVEAL = "pack_reveal"
    PACK_FLIP_ANIMATION = "pack_flip_animation"
    PACK_SUMMARY = "pack_summary"
    NETWORK_ERROR = "network_error"
    ENERGY_SHORTAGE = "energy_shortage"
    INVENTORY_FULL = "inventory_full"
    MAINTENANCE = "maintenance"
    EVENT_ENDED = "event_ended"
    UNKNOWN = "unknown"


class ActionKind(StrEnum):
    CLICK = "click"
    WAIT = "wait"
    PAUSE = "pause"


@dataclass(frozen=True)
class NormalizedRect:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)


@dataclass(frozen=True)
class Detection:
    state: ScreenState
    confidence: float
    frame_signature: int
    button: NormalizedRect | None = None
    reason: str = ""


@dataclass(frozen=True)
class PlannedAction:
    kind: ActionKind
    state: ScreenState
    point: tuple[float, float] | None = None
    reason: str = ""
