from __future__ import annotations

import asyncio
import io
import math
import time
from typing import Any

from PIL import Image

from rtc_bot.bridge import BridgeStartResult, CaptureResult, is_nonblank
from rtc_bot.config import BotConfig
from rtc_bot.vision import ContentRect

HID_MAX = 65535

try:
    from pymobiledevice3.remote.core_device.hid_service import (
        TOUCHSCREEN_STATE_CONTACT,
        TOUCHSCREEN_STATE_RELEASE,
        touch_session,
    )
    from pymobiledevice3.remote.core_device.screen_capture_service import (
        ScreenCaptureService,
    )
    from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
except ImportError as exc:
    TOUCHSCREEN_STATE_CONTACT = None
    TOUCHSCREEN_STATE_RELEASE = None
    ScreenCaptureService = None
    UserspaceRsdTunnel = None
    touch_session = None
    _IMPORT_ERROR: ImportError | None = exc
else:
    _IMPORT_ERROR = None


def map_content_point_to_hid(
    image_size: tuple[int, int],
    content_rect: ContentRect,
    point: tuple[float, float],
) -> tuple[int, int]:
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

    pixel_x = content_rect.left + point[0] * content_rect.width
    pixel_y = content_rect.top + point[1] * content_rect.height
    return (
        round(pixel_x * HID_MAX / image_width),
        round(pixel_y * HID_MAX / image_height),
    )


class DirectIOSBridge:
    def __init__(self, config: BotConfig, *, udid: str | None = None) -> None:
        self.config = config
        self.requested_udid = udid
        self.last_error = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tunnel: Any = None
        self._rsd: Any = None
        self._capture_service: Any = None
        self._touch_context: Any = None
        self._touch_service: Any = None
        self._device_id = ""

    @property
    def available(self) -> bool:
        return _IMPORT_ERROR is None

    def _run(self, coroutine: Any) -> Any:
        if self._loop is None:
            raise RuntimeError("iOS bridge is not started")
        asyncio.set_event_loop(self._loop)
        return self._loop.run_until_complete(coroutine)

    async def _start(self, *, require_control: bool) -> tuple[str, str, str]:
        self._tunnel = UserspaceRsdTunnel(serial=self.requested_udid)
        self._rsd = await self._tunnel.aopen()

        properties = (self._rsd.peer_info or {}).get("Properties", {})
        self._device_id = str(
            properties.get("UniqueDeviceID")
            or self.requested_udid
            or self._rsd.service.address[0]
        )
        product = str(properties.get("ProductType", "iPhone"))
        os_version = str(properties.get("OSVersion", "unknown iOS"))

        self._capture_service = ScreenCaptureService(self._rsd)
        await self._capture_service.__aenter__()
        if require_control:
            self._touch_context = touch_session(self._rsd)
            self._touch_service = await self._touch_context.__aenter__()
        return self._device_id, product, os_version

    def start(
        self, *, request_permissions: bool, require_control: bool
    ) -> BridgeStartResult:
        del request_permissions
        if not self.available:
            return BridgeStartResult(
                False,
                (
                    "pymobiledevice3 is not installed.",
                    "Install the iOS USB extra with `python -m pip install -e \".[ios-usb]\"`.",
                ),
            )

        self._loop = asyncio.new_event_loop()
        try:
            device_id, product, os_version = self._run(
                asyncio.wait_for(
                    self._start(require_control=require_control),
                    timeout=self.config.device_operation_timeout_seconds * 3,
                )
            )
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            self.last_error = detail
            self.close()
            return BridgeStartResult(
                False,
                (
                    f"iPhone USB connection: FAILED ({detail})",
                    "Connect and trust the iPhone, enable Developer Mode, then run "
                    "`python -m pymobiledevice3 mounter auto-mount`.",
                ),
            )

        mode = "capture + touch" if require_control else "capture only"
        return BridgeStartResult(
            True,
            (
                f"iPhone USB connection: OK ({product}, {os_version}, {mode})",
                f"device UDID: {device_id}",
            ),
        )

    async def _capture(self) -> bytes:
        response = await self._capture_service.capture_screenshot()
        return bytes(response["image"])

    def capture(self) -> CaptureResult | None:
        if self._capture_service is None:
            self.last_error = "iPhone USB connection is unavailable"
            return None
        try:
            raw = self._run(
                asyncio.wait_for(
                    self._capture(),
                    timeout=self.config.device_operation_timeout_seconds,
                )
            )
            with Image.open(io.BytesIO(raw)) as image:
                converted = image.convert("RGB")
        except Exception as exc:
            self.last_error = f"iPhone screenshot failed: {exc}"
            return None
        if not is_nonblank(converted):
            self.last_error = "iPhone screenshot returned a black frame"
            return None
        self.last_error = ""
        return CaptureResult(
            image=converted,
            backend="ios-coredevice",
            source_id=self._device_id,
        )

    async def _tap(self, x: int, y: int) -> None:
        await self._touch_service.send_touchscreen(
            TOUCHSCREEN_STATE_CONTACT, x, y
        )
        await asyncio.sleep(0.05)
        await self._touch_service.send_touchscreen(
            TOUCHSCREEN_STATE_RELEASE, x, y
        )

    def click(
        self,
        capture: CaptureResult,
        content_rect: ContentRect,
        point: tuple[float, float],
    ) -> bool:
        if (
            self._touch_service is None
            or capture.source_id != self._device_id
        ):
            return False
        try:
            current = self.capture()
            if current is None or current.image.size != capture.image.size:
                return False
            x, y = map_content_point_to_hid(
                current.image.size, content_rect, point
            )
            self._run(
                asyncio.wait_for(
                    self._tap(x, y),
                    timeout=self.config.device_operation_timeout_seconds,
                )
            )
        except Exception as exc:
            self.last_error = f"iPhone touch failed: {exc}"
            return False
        self.last_error = ""
        return True

    def wait(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self._loop is None:
            time.sleep(seconds)
            return
        self._run(asyncio.sleep(seconds))

    async def _close(self) -> None:
        if self._touch_context is not None:
            try:
                await self._touch_context.__aexit__(None, None, None)
            except Exception:
                pass
            finally:
                self._touch_context = None
                self._touch_service = None
        if self._capture_service is not None:
            try:
                await self._capture_service.__aexit__(None, None, None)
            except Exception:
                pass
            finally:
                self._capture_service = None
        if self._tunnel is not None:
            try:
                await self._tunnel.aclose()
            except Exception:
                pass
            finally:
                self._tunnel = None
                self._rsd = None

    def close(self) -> None:
        if self._loop is None:
            return
        try:
            self._run(self._close())
        except Exception:
            pass
        finally:
            self._loop.close()
            self._loop = None
            asyncio.set_event_loop(None)
