from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from rtc_bot.config import BotConfig
from rtc_bot.engine import DecisionEngine
from rtc_bot.model import ActionKind
from rtc_bot.vision import ScreenDetector


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--fps", type=float, default=2.0)
    args = parser.parse_args()

    if not args.video.exists():
        parser.error(f"video does not exist: {args.video}")

    config = BotConfig()
    detector = ScreenDetector(config)
    engine = DecisionEngine(config)
    state_counts: dict[str, int] = {}
    actions: list[tuple[float, str, tuple[float, float] | None]] = []
    pauses: list[tuple[float, str]] = []
    pause_recorded = False

    with tempfile.TemporaryDirectory(prefix="rtc-replay-") as directory:
        pattern = Path(directory) / "frame-%06d.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(args.video),
                "-vf",
                f"fps={args.fps}",
                "-q:v",
                "4",
                str(pattern),
            ],
            check=True,
        )
        frames = sorted(Path(directory).glob("frame-*.jpg"))
        for index, path in enumerate(frames):
            timestamp = index / args.fps
            with Image.open(path) as image:
                detection = detector.detect(image.convert("RGB"))
            action = engine.observe(detection, timestamp)
            state_counts[detection.state.value] = (
                state_counts.get(detection.state.value, 0) + 1
            )
            if action.kind == ActionKind.CLICK:
                actions.append((timestamp, action.state.value, action.point))
            elif action.kind == ActionKind.PAUSE and not pause_recorded:
                pauses.append((timestamp, action.reason))
                pause_recorded = True

    print("state counts:")
    for state, count in sorted(state_counts.items()):
        print(f"  {state}: {count}")
    print("planned clicks:")
    for timestamp, state, point in actions:
        print(f"  {timestamp:7.2f}s {state:16s} {point}")
    print("pauses:")
    for timestamp, reason in pauses:
        print(f"  {timestamp:7.2f}s {reason}")
    return 1 if pauses else 0


if __name__ == "__main__":
    raise SystemExit(main())
