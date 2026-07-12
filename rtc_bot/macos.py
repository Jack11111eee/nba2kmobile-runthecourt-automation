from __future__ import annotations

import io
import math
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from rtc_bot.config import BotConfig
from rtc_bot.vision import ContentRect

try:
    import AppKit
    import Quartz
except ImportError:  # Offline tests run without macOS bridges.
    AppKit = None
    Quartz = None


@dataclass(frozen=True)
class WindowBounds:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    owner_pid: int
    owner_name: str
    title: str
    bounds: WindowBounds


@dataclass(frozen=True)
class CaptureResult:
    image: Image.Image
    window: WindowInfo
    backend: str


@dataclass(frozen=True)
class PermissionStatus:
    screen_capture: bool
    event_posting: bool


def is_nonblank(image: Image.Image) -> bool:
    sample = np.asarray(image.convert("L").resize((96, 48)), dtype=np.float32)
    return bool(sample.std() >= 4.0 and sample.max() - sample.min() >= 20.0)


def map_normalized_point(
    bounds: WindowBounds,
    image_size: tuple[int, int],
    content_rect: ContentRect,
    point: tuple[float, float],
) -> tuple[float, float]:
    image_width, image_height = image_size
    if (
        image_width <= 0
        or image_height <= 0
        or content_rect.width <= 0
        or content_rect.height <= 0
        or not all(math.isfinite(value) for value in point)
        or not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0)
    ):
        raise ValueError("invalid image geometry or normalized click point")
    local_x = content_rect.left + point[0] * content_rect.width
    local_y = content_rect.top + point[1] * content_rect.height
    return (
        bounds.x + (local_x / image_width) * bounds.width,
        bounds.y + (local_y / image_height) * bounds.height,
    )


class MacOSBridge:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    @property
    def available(self) -> bool:
        return Quartz is not None and AppKit is not None

    def permissions(self, *, request: bool) -> PermissionStatus:
        if not self.available:
            return PermissionStatus(False, False)

        screen_capture = bool(Quartz.CGPreflightScreenCaptureAccess())
        event_posting = bool(Quartz.CGPreflightPostEventAccess())
        if request and not screen_capture:
            screen_capture = bool(Quartz.CGRequestScreenCaptureAccess())
        if request and not event_posting:
            event_posting = bool(Quartz.CGRequestPostEventAccess())
        return PermissionStatus(screen_capture, event_posting)

    def list_windows(self) -> list[WindowInfo]:
        if not self.available:
            return []
        options = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        raw_windows = Quartz.CGWindowListCopyWindowInfo(
            options, Quartz.kCGNullWindowID
        )
        windows: list[WindowInfo] = []
        for raw in raw_windows or []:
            owner_name = str(raw.get(Quartz.kCGWindowOwnerName, ""))
            owner_pid = int(raw.get(Quartz.kCGWindowOwnerPID, -1))
            bundle_id = ""
            running = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
                owner_pid
            )
            if running is not None:
                bundle_id = str(running.bundleIdentifier() or "")
            if (
                owner_name != self.config.mirror_owner_name
                and bundle_id != self.config.mirror_bundle_id
            ):
                continue

            raw_bounds = raw.get(Quartz.kCGWindowBounds, {})
            bounds = WindowBounds(
                x=float(raw_bounds.get("X", 0.0)),
                y=float(raw_bounds.get("Y", 0.0)),
                width=float(raw_bounds.get("Width", 0.0)),
                height=float(raw_bounds.get("Height", 0.0)),
            )
            windows.append(
                WindowInfo(
                    window_id=int(raw.get(Quartz.kCGWindowNumber, -1)),
                    owner_pid=owner_pid,
                    owner_name=owner_name,
                    title=str(raw.get(Quartz.kCGWindowName, "")),
                    bounds=bounds,
                )
            )
        return windows

    def find_mirror_window(self) -> WindowInfo | None:
        candidates = [
            window
            for window in self.list_windows()
            if window.bounds.width >= 400 and window.bounds.height >= 200
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda window: window.bounds.width * window.bounds.height)

    def _capture_quartz(self, window: WindowInfo) -> Image.Image | None:
        if not self.available:
            return None
        options = (
            Quartz.kCGWindowImageBoundsIgnoreFraming
            | Quartz.kCGWindowImageBestResolution
        )
        cg_image = Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull,
            Quartz.kCGWindowListOptionIncludingWindow,
            window.window_id,
            options,
        )
        if cg_image is None:
            return None
        bitmap = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(cg_image)
        data = bitmap.representationUsingType_properties_(
            AppKit.NSBitmapImageFileTypePNG, {}
        )
        if data is None:
            return None
        with Image.open(io.BytesIO(bytes(data))) as image:
            return image.convert("RGB")

    def _capture_screencapture(self, window: WindowInfo) -> Image.Image | None:
        with tempfile.TemporaryDirectory(prefix="rtc-bot-") as directory:
            path = Path(directory) / "window.png"
            result = subprocess.run(
                [
                    "/usr/sbin/screencapture",
                    "-x",
                    "-o",
                    "-l",
                    str(window.window_id),
                    str(path),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0 or not path.exists():
                return None
            with Image.open(path) as image:
                return image.convert("RGB")

    def capture(self, window: WindowInfo) -> CaptureResult | None:
        image = self._capture_quartz(window)
        backend = "quartz"
        if image is None or not is_nonblank(image):
            image = self._capture_screencapture(window)
            backend = "screencapture"
        if image is None or not is_nonblank(image):
            return None
        return CaptureResult(image=image, window=window, backend=backend)

    @staticmethod
    def _same_bounds(left: WindowBounds, right: WindowBounds) -> bool:
        return all(
            abs(a - b) <= 2.0
            for a, b in (
                (left.x, right.x),
                (left.y, right.y),
                (left.width, right.width),
                (left.height, right.height),
            )
        )

    def click(
        self,
        capture: CaptureResult,
        content_rect: ContentRect,
        point: tuple[float, float],
    ) -> bool:
        if not self.available:
            return False
        current = self.find_mirror_window()
        if (
            current is None
            or current.window_id != capture.window.window_id
            or not self._same_bounds(current.bounds, capture.window.bounds)
        ):
            return False
        if (
            not all(math.isfinite(value) for value in point)
            or not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0)
        ):
            return False

        running = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
            current.owner_pid
        )
        if running is not None:
            running.activateWithOptions_(
                AppKit.NSApplicationActivateIgnoringOtherApps
            )
            time.sleep(0.12)

        screen_x, screen_y = map_normalized_point(
            current.bounds, capture.image.size, content_rect, point
        )
        location = Quartz.CGPoint(screen_x, screen_y)

        move = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventMouseMoved, location, Quartz.kCGMouseButtonLeft
        )
        down = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDown, location, Quartz.kCGMouseButtonLeft
        )
        up = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseUp, location, Quartz.kCGMouseButtonLeft
        )
        for event in (move, down, up):
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            time.sleep(0.04)
        return True
