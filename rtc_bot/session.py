from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from rtc_bot.exceptions import EXCEPTION_STATES
from rtc_bot.model import ActionKind, Detection, PlannedAction, ScreenState


GAME_START_STATES = {
    ScreenState.VS_READY,
    ScreenState.LINEUP,
    ScreenState.GAMEPLAY,
}


@dataclass(frozen=True)
class RunPolicy:
    max_games: int | None = None
    max_duration_seconds: float | None = None
    stop_after_win: bool = False
    on_loss: Literal["pause", "exit"] = "pause"

    def __post_init__(self) -> None:
        if self.max_games is not None and self.max_games <= 0:
            raise ValueError("max_games must be positive")
        if (
            self.max_duration_seconds is not None
            and self.max_duration_seconds <= 0
        ):
            raise ValueError("max_duration_seconds must be positive")
        if self.on_loss not in {"pause", "exit"}:
            raise ValueError("on_loss must be 'pause' or 'exit'")


@dataclass(frozen=True)
class SessionDecision:
    should_stop: bool
    exit_code: int | None
    final_action: PlannedAction
    reason: str


class RunSession:
    def __init__(
        self,
        policy: RunPolicy,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy
        self._clock = clock
        self.started_at = clock()
        self.frames_seen = 0
        self.state_counts: Counter[ScreenState] = Counter()
        self.action_counts: Counter[ActionKind] = Counter()
        self.click_state_counts: Counter[ScreenState] = Counter()
        self.wins = 0
        self.losses = 0
        self._result_recorded = False
        self._paused_reason: str | None = None

    @property
    def games_completed(self) -> int:
        return self.wins + self.losses

    @property
    def elapsed_seconds(self) -> float:
        return self._clock() - self.started_at

    def _pause(
        self,
        state: ScreenState,
        reason: str,
        *,
        should_stop: bool,
        exit_code: int | None,
    ) -> SessionDecision:
        final_action = PlannedAction(
            kind=ActionKind.PAUSE,
            state=state,
            reason=reason,
        )
        return SessionDecision(
            should_stop=should_stop,
            exit_code=exit_code,
            final_action=final_action,
            reason=reason,
        )

    def _time_limit_decision(
        self, state: ScreenState
    ) -> SessionDecision | None:
        if (
            self.policy.max_duration_seconds is None
            or self.elapsed_seconds < self.policy.max_duration_seconds
        ):
            return None
        return self._pause(
            state,
            (
                "maximum duration reached "
                f"({self.policy.max_duration_seconds:.1f}s)"
            ),
            should_stop=True,
            exit_code=0,
        )

    def check_time_limit(
        self, state: ScreenState = ScreenState.UNKNOWN
    ) -> SessionDecision | None:
        decision = self._time_limit_decision(state)
        if decision is not None:
            self.action_counts[decision.final_action.kind] += 1
        return decision

    def observe(
        self,
        detection: Detection,
        action: PlannedAction,
    ) -> SessionDecision:
        self.frames_seen += 1
        self.state_counts[detection.state] += 1
        new_result: ScreenState | None = None
        if detection.state in GAME_START_STATES:
            self._result_recorded = False
        elif not self._result_recorded:
            if (
                detection.state == ScreenState.WIN_RESULT
                and action.kind == ActionKind.CLICK
            ):
                self.wins += 1
                self._result_recorded = True
                new_result = detection.state
            elif (
                detection.state == ScreenState.LOSS_RESULT
                and action.kind == ActionKind.PAUSE
            ):
                self.losses += 1
                self._result_recorded = True
                new_result = detection.state

        if (
            detection.state in EXCEPTION_STATES
            and action.kind == ActionKind.PAUSE
        ):
            decision = self._pause(
                detection.state,
                action.reason,
                should_stop=True,
                exit_code=3,
            )
        else:
            time_limit = self._time_limit_decision(detection.state)
            if time_limit is not None:
                decision = time_limit
            elif (
                self.policy.max_games is not None
                and self.games_completed >= self.policy.max_games
            ):
                decision = self._pause(
                    detection.state,
                    f"maximum game count reached ({self.policy.max_games})",
                    should_stop=True,
                    exit_code=0,
                )
            elif self.policy.stop_after_win and new_result == ScreenState.WIN_RESULT:
                decision = self._pause(
                    detection.state,
                    "stop after win",
                    should_stop=True,
                    exit_code=0,
                )
            elif (
                new_result == ScreenState.LOSS_RESULT
                and self.policy.on_loss == "exit"
            ):
                decision = self._pause(
                    detection.state,
                    "exit after loss",
                    should_stop=True,
                    exit_code=1,
                )
            elif (
                new_result == ScreenState.LOSS_RESULT
                and self.policy.on_loss == "pause"
            ):
                self._paused_reason = "paused after loss"
                decision = self._pause(
                    detection.state,
                    self._paused_reason,
                    should_stop=False,
                    exit_code=None,
                )
            elif self._paused_reason is not None:
                decision = self._pause(
                    detection.state,
                    self._paused_reason,
                    should_stop=False,
                    exit_code=None,
                )
            else:
                decision = SessionDecision(
                    should_stop=False,
                    exit_code=None,
                    final_action=action,
                    reason=action.reason,
                )

        self.action_counts[decision.final_action.kind] += 1
        if decision.final_action.kind == ActionKind.CLICK:
            self.click_state_counts[decision.final_action.state] += 1
        return decision
