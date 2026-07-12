from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from rtc_bot.config import BotConfig
from rtc_bot.engine import DecisionEngine
from rtc_bot.macos import MacOSBridge, is_nonblank
from rtc_bot.model import ActionKind, ScreenState
from rtc_bot.runtime import SessionLogger, SleepInhibitor, notify
from rtc_bot.vision import ScreenDetector, crop_content


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


def run_loop(config: BotConfig, *, dry_run: bool, debug: bool) -> int:
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
    logger = SessionLogger(config)
    last_console_key: tuple[object, ...] | None = None
    last_debug_state: ScreenState | None = None
    last_pack_debug_snapshot_at = float("-inf")
    pause_notified = False
    next_tick = time.monotonic()

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"rtc-bot started in {mode} mode; press Ctrl+C to stop")

    with SleepInhibitor():
        try:
            while True:
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
                action = engine.observe(detection, now)
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

                if debug and detection.state != last_debug_state:
                    logger.save_capture(capture.image, detection.state.value)
                    last_debug_state = detection.state
                    if detection.state == ScreenState.UNKNOWN:
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
            return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = BotConfig(runtime_dir=Path.cwd() / "runtime")
    if args.command == "doctor":
        return run_doctor(config)
    if args.command == "run":
        return run_loop(config, dry_run=args.dry_run, debug=args.debug)
    return 2


if __name__ == "__main__":
    sys.exit(main())
