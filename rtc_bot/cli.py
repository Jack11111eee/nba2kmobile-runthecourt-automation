from __future__ import annotations

import argparse
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rtc_bot.config import BotConfig
from rtc_bot.engine import DecisionEngine
from rtc_bot.macos import MacOSBridge, is_nonblank
from rtc_bot.model import ActionKind, ScreenState
from rtc_bot.reporting import format_console_summary
from rtc_bot.runtime import SessionLogger, SleepInhibitor, notify
from rtc_bot.session import RunPolicy, RunSession
from rtc_bot.vision import ScreenDetector, crop_content


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtc-bot",
        description="NBA 2K Mobile Run The Court local automation",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="check permissions and mirror capture")
    run_parser = subparsers.add_parser("run", help="start automation")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="detect and log actions without clicking",
    )
    run_parser.add_argument(
        "--debug",
        action="store_true",
        help="save a capture whenever the detected state changes",
    )
    run_parser.add_argument(
        "--max-games",
        type=positive_int,
        help="stop before continuing after this many completed games",
    )
    run_parser.add_argument(
        "--max-duration",
        type=positive_float,
        help="stop after this many minutes, including capture outages",
    )
    run_parser.add_argument(
        "--stop-after-win",
        action="store_true",
        help="stop on a confirmed win before opening the reward flow",
    )
    run_parser.add_argument(
        "--on-loss",
        choices=("pause", "exit"),
        default="pause",
        help="pause indefinitely or exit after a confirmed loss",
    )
    run_parser.add_argument(
        "--capture-limit-mb",
        type=positive_float,
        default=256.0,
        help="maximum total size of runtime capture PNGs",
    )
    return parser


def print_permissions(screen_capture: bool, event_posting: bool) -> None:
    print(f"screen capture permission: {'OK' if screen_capture else 'MISSING'}")
    print(f"accessibility/event permission: {'OK' if event_posting else 'MISSING'}")


def run_doctor(config: BotConfig) -> int:
    bridge = MacOSBridge(config)
    if not bridge.available:
        print("PyObjC is not installed. Install the project dependencies first.")
        return 2

    permissions = bridge.permissions(request=True)
    print_permissions(permissions.screen_capture, permissions.event_posting)
    if not permissions.screen_capture or not permissions.event_posting:
        print(
            "Permissions were requested. Enable Screen Recording and "
            "Accessibility for the terminal application running the bot, "
            "then re-run doctor."
        )
        return 2

    window = bridge.find_mirror_window()
    if window is None:
        print("iPhone Mirroring window: NOT FOUND")
        print("Open iPhone Mirroring, connect the phone, and keep the window visible.")
        return 2

    print(
        "iPhone Mirroring window: "
        f"id={window.window_id} "
        f"bounds={window.bounds.width:.0f}x{window.bounds.height:.0f}"
        f"+{window.bounds.x:.0f}+{window.bounds.y:.0f}"
    )
    capture = bridge.capture(window)
    if capture is None or not is_nonblank(capture.image):
        print("mirror capture: FAILED or BLACK")
        return 2

    config.doctor_dir.mkdir(parents=True, exist_ok=True)
    path = config.doctor_dir / "mirror-capture.png"
    capture.image.save(path)
    detector = ScreenDetector(config)
    detection = detector.detect(capture.image)
    print(
        f"mirror capture: OK ({capture.backend}, "
        f"{capture.image.width}x{capture.image.height})"
    )
    print(
        f"detected state: {detection.state.value} "
        f"confidence={detection.confidence:.2f}"
    )
    print(f"saved capture: {path.resolve()}")

    return 0


def session_summary(
    session: RunSession,
    *,
    started_at: datetime,
    ended_at: datetime,
    mode: str,
    stop_reason: str,
) -> dict[str, Any]:
    return {
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": max(0.0, (ended_at - started_at).total_seconds()),
        "mode": mode,
        "stop_reason": stop_reason,
        "frames": session.frames_seen,
        "state_counts": {
            state.value: count for state, count in session.state_counts.items()
        },
        "action_counts": {
            action.value: count for action, count in session.action_counts.items()
        },
        "click_state_counts": {
            state.value: count
            for state, count in session.click_state_counts.items()
        },
        "wins": session.wins,
        "losses": session.losses,
    }


def run_loop(
    config: BotConfig,
    *,
    dry_run: bool,
    debug: bool,
    policy: RunPolicy,
) -> int:
    bridge = MacOSBridge(config)
    if not bridge.available:
        print("PyObjC is not installed. Install the project dependencies first.")
        return 2

    permissions = bridge.permissions(request=False)
    if not permissions.screen_capture or (not dry_run and not permissions.event_posting):
        print_permissions(permissions.screen_capture, permissions.event_posting)
        print("Run `python3 -m rtc_bot doctor` and grant the requested permissions.")
        return 2

    detector = ScreenDetector(config)
    engine = DecisionEngine(config)
    session = RunSession(policy)
    logger = SessionLogger(config)
    last_console_key: tuple[object, ...] | None = None
    last_debug_state: ScreenState | None = None
    last_pack_debug_snapshot_at = float("-inf")
    pause_notified = False
    next_tick = time.monotonic()
    started_at = datetime.now().astimezone()
    stop_reason = "user interrupt"
    exit_code = 0

    mode = "dry-run" if dry_run else "live"
    print(f"rtc-bot started in {mode.upper()} mode; press Ctrl+C to stop")

    with SleepInhibitor():
        try:
            while True:
                time_decision = session.check_time_limit()
                if time_decision is not None:
                    stop_reason = time_decision.reason
                    exit_code = time_decision.exit_code or 0
                    notify("RTC Bot stopped", stop_reason)
                    print(f"automation stopped; reason={stop_reason}")
                    break

                now = time.monotonic()
                window = bridge.find_mirror_window()
                if window is None:
                    key = ("window-missing",)
                    if key != last_console_key:
                        print("[wait] iPhone Mirroring window is unavailable")
                        notify("RTC Bot waiting", "iPhone Mirroring window is unavailable")
                        last_console_key = key
                    next_tick = time.monotonic()
                    time.sleep(config.capture_interval_seconds)
                    continue

                capture = bridge.capture(window)
                if capture is None:
                    key = ("capture-failed",)
                    if key != last_console_key:
                        print("[wait] mirror capture failed or returned a black frame")
                        notify("RTC Bot waiting", "Mirror capture failed or returned black")
                        last_console_key = key
                    next_tick = time.monotonic()
                    time.sleep(config.capture_interval_seconds)
                    continue

                detection = detector.detect(capture.image)
                engine_action = engine.observe(detection, now)
                session_decision = session.observe(detection, engine_action)
                action = session_decision.final_action
                logger.write(
                    timestamp=time.time(),
                    detection=detection,
                    action=action,
                    extra={"capture_backend": capture.backend, "dry_run": dry_run},
                )

                console_key = (
                    detection.state,
                    round(detection.confidence, 2),
                    action.kind,
                    action.reason,
                )
                if console_key != last_console_key:
                    print(
                        f"[{action.kind.value}] state={detection.state.value} "
                        f"confidence={detection.confidence:.2f} "
                        f"reason={action.reason}"
                    )
                    last_console_key = console_key

                stable_state = engine.status.stable_state
                if (
                    debug
                    and engine.status.stable_count >= config.stable_frames
                    and stable_state != last_debug_state
                ):
                    logger.save_capture(capture.image, stable_state.value)
                    last_debug_state = stable_state
                    if stable_state == ScreenState.UNKNOWN:
                        logger.last_unknown_snapshot_at = now

                if (
                    debug
                    and detection.state == ScreenState.PACK_FLIP_ANIMATION
                    and now - last_pack_debug_snapshot_at
                    >= config.pack_debug_snapshot_interval_seconds
                ):
                    logger.save_capture(capture.image, "pack-flip-wait")
                    last_pack_debug_snapshot_at = now

                if detection.state == ScreenState.UNKNOWN:
                    if (
                        now - logger.last_unknown_snapshot_at
                        >= config.unknown_snapshot_interval_seconds
                    ):
                        logger.save_capture(capture.image, "unknown")
                        logger.last_unknown_snapshot_at = now

                if action.kind == ActionKind.PAUSE and not pause_notified:
                    path = logger.save_capture(capture.image, "paused")
                    notify("RTC Bot paused", action.reason)
                    print(f"automation paused; capture saved to {path.resolve()}")
                    pause_notified = True

                if session_decision.should_stop:
                    stop_reason = session_decision.reason
                    exit_code = session_decision.exit_code or 0
                    break

                if action.kind == ActionKind.CLICK:
                    logger.save_capture(
                        capture.image, f"planned-click-{detection.state.value}"
                    )
                    if dry_run:
                        print(f"[dry-run] would click normalized point {action.point}")
                    else:
                        assert action.point is not None
                        _, content_rect = crop_content(capture.image)
                        if not bridge.click(capture, content_rect, action.point):
                            logger.save_capture(capture.image, "click-cancelled")
                            print("[wait] click cancelled because the window changed")

                next_tick += config.capture_interval_seconds
                time.sleep(max(0.0, next_tick - time.monotonic()))
        except KeyboardInterrupt:
            print("\nrtc-bot stopped by user")
            stop_reason = "user interrupt"

    ended_at = datetime.now().astimezone()
    summary = session_summary(
        session,
        started_at=started_at,
        ended_at=ended_at,
        mode=mode,
        stop_reason=stop_reason,
    )
    report_path = logger.write_report(summary)
    print(
        format_console_summary(
            {
                **summary,
                "captures_written": logger.captures_written,
                "capture_bytes_written": logger.capture_bytes_written,
            }
        )
    )
    print(f"session report: {report_path.resolve()}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        config = BotConfig(runtime_dir=Path.cwd() / "runtime")
        return run_doctor(config)
    if args.command == "run":
        config = BotConfig(
            runtime_dir=Path.cwd() / "runtime",
            capture_limit_bytes=round(args.capture_limit_mb * 1024 * 1024),
        )
        policy = RunPolicy(
            max_games=args.max_games,
            max_duration_seconds=(
                args.max_duration * 60 if args.max_duration is not None else None
            ),
            stop_after_win=args.stop_after_win,
            on_loss=args.on_loss,
        )
        return run_loop(
            config,
            dry_run=args.dry_run,
            debug=args.debug,
            policy=policy,
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
