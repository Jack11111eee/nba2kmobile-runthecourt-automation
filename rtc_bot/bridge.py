from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image

from rtc_bot.config import BotConfig
from rtc_bot.vision import ContentRect

BACKEND_AUTO = "auto"
BACKEND_IOS_USB = "ios-usb"
BACKEND_MACOS_MIRRORING = "macos-mirroring"
BACKEND_CHOICES = (
    BACKEND_AUTO,
    BACKEND_MACOS_MIRRORING,
    BACKEND_IOS_USB,
)


@dataclass(frozen=True)
class CaptureResult:
    image: Image.Image
    backend: str
    source_id: str
    context: object | None = None


@dataclass(frozen=True)
class BridgeStartResult:
    ready: bool
    messages: tuple[str, ...]


class AutomationBridge(Protocol):
    last_error: str

    def start(
        self, *, request_permissions: bool, require_control: bool
    ) -> BridgeStartResult: ...

    def capture(self) -> CaptureResult | None: ...

    def click(
        self,
        capture: CaptureResult,
        content_rect: ContentRect,
        point: tuple[float, float],
    ) -> bool: ...

    def wait(self, seconds: float) -> None: ...

    def close(self) -> None: ...


def is_nonblank(image: Image.Image) -> bool:
    sample = np.asarray(image.convert("L").resize((96, 48)), dtype=np.float32)
    return bool(sample.std() >= 4.0 and sample.max() - sample.min() >= 20.0)


def resolve_backend(
    requested: str,
    *,
    platform_name: str | None = None,
) -> str:
    if requested != BACKEND_AUTO:
        return requested

    current_platform = platform_name or sys.platform
    if current_platform == "darwin":
        return BACKEND_MACOS_MIRRORING
    if current_platform == "win32":
        return BACKEND_IOS_USB
    raise ValueError(
        "live automation is supported on macOS and Windows only; "
        "offline recognition tests remain cross-platform"
    )


def create_bridge(
    config: BotConfig,
    *,
    backend: str,
    udid: str | None,
) -> AutomationBridge:
    resolved = resolve_backend(backend)
    if resolved == BACKEND_MACOS_MIRRORING:
        from rtc_bot.macos import MacOSBridge

        return MacOSBridge(config)
    if resolved == BACKEND_IOS_USB:
        from rtc_bot.ios_device import DirectIOSBridge

        return DirectIOSBridge(config, udid=udid)
    raise ValueError(f"unknown backend: {resolved}")
