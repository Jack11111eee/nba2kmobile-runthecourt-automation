from __future__ import annotations

from dataclasses import dataclass

from rtc_bot.config import BotConfig
from rtc_bot.model import ActionKind, Detection, PlannedAction, ScreenState
from rtc_bot.vision import signature_distance


CLICK_STATES = {
    ScreenState.EVENT_HOME,
    ScreenState.STAGE_SELECT,
    ScreenState.VS_READY,
    ScreenState.LINEUP,
    ScreenState.WIN_RESULT,
    ScreenState.PACK_OPEN,
    ScreenState.PACK_REVEAL,
    ScreenState.PACK_SUMMARY,
}

PAUSE_STATES = {
    ScreenState.LOSS_RESULT,
}


@dataclass
class EngineStatus:
    stable_state: ScreenState = ScreenState.UNKNOWN
    stable_count: int = 0
    last_seen_state: ScreenState = ScreenState.UNKNOWN
    last_action_at: float = float("-inf")
    awaiting_change_signature: int | None = None
    awaiting_state_change: ScreenState | None = None
    reward_signature: int | None = None
    reward_seen_at: float | None = None
    pack_idle_signature: int | None = None
    pack_idle_seen_at: float | None = None
    paused: bool = False
    pause_reason: str = ""


class DecisionEngine:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.status = EngineStatus()

    def _update_stability(self, detection: Detection) -> None:
        if detection.state == self.status.last_seen_state:
            self.status.stable_count += 1
        else:
            self.status.last_seen_state = detection.state
            self.status.stable_count = 1
        if self.status.stable_count >= self.config.stable_frames:
            self.status.stable_state = detection.state

    def _frame_changed(self, signature: int) -> bool:
        previous = self.status.awaiting_change_signature
        if previous is None:
            return True
        if signature_distance(previous, signature) >= self.config.frame_change_threshold:
            self.status.awaiting_change_signature = None
            return True
        return False

    def _record_action(
        self, detection: Detection, now: float, *, require_state_change: bool
    ) -> None:
        self.status.last_action_at = now
        self.status.awaiting_change_signature = detection.frame_signature
        if require_state_change:
            self.status.awaiting_state_change = detection.state

    def observe(self, detection: Detection, now: float) -> PlannedAction:
        self._update_stability(detection)

        if self.status.paused:
            return PlannedAction(
                ActionKind.PAUSE,
                self.status.stable_state,
                reason=self.status.pause_reason,
            )

        awaiting_state = self.status.awaiting_state_change
        if awaiting_state is not None:
            if (
                self.status.stable_count >= self.config.stable_frames
                and self.status.stable_state != awaiting_state
            ):
                self.status.awaiting_state_change = None
                self.status.awaiting_change_signature = None
            else:
                return PlannedAction(
                    ActionKind.WAIT,
                    detection.state,
                    reason=f"waiting to leave {awaiting_state.value}",
                )

        if detection.state in PAUSE_STATES and self.status.stable_count >= self.config.stable_frames:
            self.status.paused = True
            self.status.pause_reason = f"recognized stop state: {detection.state.value}"
            return PlannedAction(
                ActionKind.PAUSE,
                detection.state,
                reason=self.status.pause_reason,
            )

        if self.status.stable_count < self.config.stable_frames:
            return PlannedAction(
                ActionKind.WAIT,
                detection.state,
                reason="waiting for stable detection",
            )

        if (
            detection.state in CLICK_STATES
            or detection.state == ScreenState.QUARTER_REWARD
        ) and detection.confidence < self.config.minimum_action_confidence:
            return PlannedAction(
                ActionKind.WAIT,
                detection.state,
                reason=(
                    "action confidence below threshold "
                    f"({detection.confidence:.2f} < "
                    f"{self.config.minimum_action_confidence:.2f})"
                ),
            )

        if (
            detection.state == ScreenState.PACK_FLIP_ANIMATION
            and detection.confidence
            < self.config.pack_fallback_minimum_confidence
        ):
            return PlannedAction(
                ActionKind.WAIT,
                detection.state,
                reason=(
                    "pack fallback confidence below threshold "
                    f"({detection.confidence:.2f} < "
                    f"{self.config.pack_fallback_minimum_confidence:.2f})"
                ),
            )

        if now - self.status.last_action_at < self.config.post_click_cooldown_seconds:
            return PlannedAction(
                ActionKind.WAIT,
                detection.state,
                reason="post-click cooldown",
            )

        if not self._frame_changed(detection.frame_signature):
            return PlannedAction(
                ActionKind.WAIT,
                detection.state,
                reason="waiting for visible frame change",
            )

        if detection.state == ScreenState.QUARTER_REWARD:
            if self.status.reward_signature is None or signature_distance(
                self.status.reward_signature, detection.frame_signature
            ) >= self.config.frame_change_threshold:
                self.status.reward_signature = detection.frame_signature
                self.status.reward_seen_at = now
                return PlannedAction(
                    ActionKind.WAIT,
                    detection.state,
                    reason="reward changed; waiting for auto advance",
                )

            assert self.status.reward_seen_at is not None
            elapsed = now - self.status.reward_seen_at
            if elapsed < self.config.reward_auto_wait_seconds:
                return PlannedAction(
                    ActionKind.WAIT,
                    detection.state,
                    reason=f"reward auto-advance wait {elapsed:.1f}s",
                )

            self._record_action(detection, now, require_state_change=False)
            return PlannedAction(
                ActionKind.CLICK,
                detection.state,
                point=(0.5, 0.52),
                reason="reward did not auto-advance",
            )

        self.status.reward_signature = None
        self.status.reward_seen_at = None

        if detection.state == ScreenState.PACK_FLIP_ANIMATION:
            if self.status.pack_idle_signature != detection.frame_signature:
                self.status.pack_idle_signature = detection.frame_signature
                self.status.pack_idle_seen_at = now
                return PlannedAction(
                    ActionKind.WAIT,
                    detection.state,
                    reason="pack animation changed; waiting for it to settle",
                )

            assert self.status.pack_idle_seen_at is not None
            elapsed = now - self.status.pack_idle_seen_at
            if elapsed < self.config.pack_settle_wait_seconds:
                return PlannedAction(
                    ActionKind.WAIT,
                    detection.state,
                    reason=f"pack settle wait {elapsed:.1f}s",
                )

            self._record_action(detection, now, require_state_change=True)
            return PlannedAction(
                ActionKind.CLICK,
                detection.state,
                point=(0.765, 0.845),
                reason="pack settled; continue-button fallback",
            )

        self.status.pack_idle_signature = None
        self.status.pack_idle_seen_at = None

        if detection.state in CLICK_STATES:
            if detection.button is None:
                return PlannedAction(
                    ActionKind.WAIT,
                    detection.state,
                    reason="safe button not found",
                )
            self._record_action(detection, now, require_state_change=True)
            return PlannedAction(
                ActionKind.CLICK,
                detection.state,
                point=detection.button.center,
                reason="stable allowlisted action",
            )

        return PlannedAction(
            ActionKind.WAIT,
            detection.state,
            reason="state has no automatic action",
        )
