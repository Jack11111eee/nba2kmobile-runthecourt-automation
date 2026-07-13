from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from rtc_bot.bridge import BACKEND_CHOICES, create_bridge, is_nonblank
from rtc_bot.config import BotConfig
from rtc_bot.engine import DecisionEngine
from rtc_bot.model import ActionKind, ScreenState
from rtc_bot.runtime import SessionLogger, SleepInhibitor, notify
from rtc_bot.vision import ScreenDetector, crop_content


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtc-bot",
        description="NBA 2K Mobile Run The Court local automation",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser(
        "doctor", help="check permissions and device capture"
    )
    run_parser = subparsers.add_parser("run", help="start automation")
    for command_parser in (doctor_parser, run_parser):
        command_parser.add_argument(
            "--backend",
            choices=BACKEND_CHOICES,
            default="auto",
            help="capture/control backend (default: platform-specific auto)",
        )
        command_parser.add_argument(
            "--udid",
            help="target iPhone UDID for the ios-usb backend",
        )
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


def run_doctor(
    config: BotConfig,
    *,
    backend: str = "auto",
    udid: str | None = None,
) -> int:
    try:
        bridge = create_bridge(config, backend=backend, udid=udid)
    except ValueError as exc:
        print(exc)
        return 2

    start = bridge.start(request_permissions=True, require_control=True)
    for message in start.messages:
        print(message)
    if not start.ready:
        return 2

    try:
        capture = bridge.capture()
        if capture is None or not is_nonblank(capture.image):
            print(f"device capture: FAILED ({bridge.last_error})")
            return 2

        config.doctor_dir.mkdir(parents=True, exist_ok=True)
        path = config.doctor_dir / "device-capture.png"
        capture.image.save(path)
        detector = ScreenDetector(config)
        detection = detector.detect(capture.image)
        print(
            f"device capture: OK ({capture.backend}, "
            f"{capture.image.width}x{capture.image.height})"
        )
        print(
            f"detected state: {detection.state.value} "
            f"confidence={detection.confidence:.2f}"
        )
        print(f"saved capture: {path.resolve()}")
    finally:
        bridge.close()

    return 0


def run_loop(
    config: BotConfig,
    *,
    dry_run: bool,
    debug: bool,
    backend: str = "auto",
    udid: str | None = None,
) -> int:
    try:
        bridge = create_bridge(config, backend=backend, udid=udid)
    except ValueError as exc:
        print(exc)
        return 2

    start = bridge.start(
        request_permissions=False,
        require_control=not dry_run,
    )
    if not start.ready:
        for message in start.messages:
            print(message)
        print("Run `python -m rtc_bot doctor` after fixing the reported issue.")
        return 2
    for message in start.messages:
        print(message)

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
                capture = bridge.capture()
                if capture is None:
                    reason = bridge.last_error or "device capture failed"
                    key = ("capture-failed", reason)
                    if key != last_console_key:
                        print(f"[wait] {reason}")
                        notify("RTC Bot waiting", reason)
                        last_console_key = key
                    next_tick = time.monotonic()
                    bridge.wait(config.capture_interval_seconds)
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
                            print(
                                "[wait] click cancelled because the capture "
                                "source changed or rejected the touch"
                            )

                next_tick += config.capture_interval_seconds
                bridge.wait(max(0.0, next_tick - time.monotonic()))
        except KeyboardInterrupt:
            print("\nrtc-bot stopped by user")
            return 0
        finally:
            bridge.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = BotConfig(runtime_dir=Path.cwd() / "runtime")
    if args.command == "doctor":
        return run_doctor(config, backend=args.backend, udid=args.udid)
    if args.command == "run":
        return run_loop(
            config,
            dry_run=args.dry_run,
            debug=args.debug,
            backend=args.backend,
            udid=args.udid,
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
