from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

from rtc_bot.bridge import (
    BACKEND_IOS_USB,
    BACKEND_MACOS_MIRRORING,
    CaptureResult,
    resolve_backend,
)
from rtc_bot.config import BotConfig
from rtc_bot.ios_device import DirectIOSBridge, HID_MAX, map_content_point_to_hid
from rtc_bot.vision import ContentRect


class BackendSelectionTests(unittest.TestCase):
    def test_auto_selects_macos_mirroring_on_darwin(self) -> None:
        self.assertEqual(
            BACKEND_MACOS_MIRRORING,
            resolve_backend("auto", platform_name="darwin"),
        )

    def test_auto_selects_ios_usb_on_windows(self) -> None:
        self.assertEqual(
            BACKEND_IOS_USB,
            resolve_backend("auto", platform_name="win32"),
        )

    def test_auto_rejects_unsupported_live_platform(self) -> None:
        with self.assertRaises(ValueError):
            resolve_backend("auto", platform_name="linux")


class IOSDeviceGeometryTests(unittest.TestCase):
    def test_maps_full_screen_center_to_hid_center(self) -> None:
        point = map_content_point_to_hid(
            (1920, 886),
            ContentRect(0, 0, 1920, 886),
            (0.5, 0.5),
        )
        self.assertEqual((32768, 32768), point)

    def test_maps_content_point_through_capture_chrome(self) -> None:
        point = map_content_point_to_hid(
            (960, 500),
            ContentRect(0, 57, 960, 500),
            (0.5, 0.5),
        )
        self.assertEqual((32768, 36503), point)

    def test_maps_bottom_right_to_hid_maximum(self) -> None:
        point = map_content_point_to_hid(
            (1920, 886),
            ContentRect(0, 0, 1920, 886),
            (1.0, 1.0),
        )
        self.assertEqual((HID_MAX, HID_MAX), point)

    def test_rejects_out_of_range_point(self) -> None:
        with self.assertRaises(ValueError):
            map_content_point_to_hid(
                (1920, 886),
                ContentRect(0, 0, 1920, 886),
                (-0.01, 0.5),
            )


class FakeTunnel:
    def __init__(self, serial: str | None) -> None:
        self.serial = serial
        self.closed = False

    async def aopen(self) -> SimpleNamespace:
        return SimpleNamespace(
            peer_info={
                "Properties": {
                    "UniqueDeviceID": self.serial or "test-udid",
                    "ProductType": "iPhone16,1",
                    "OSVersion": "18.6.2",
                }
            },
            service=SimpleNamespace(address=("fd00::1", 58783)),
        )

    async def aclose(self) -> None:
        self.closed = True


class FailingTunnel(FakeTunnel):
    async def aopen(self) -> SimpleNamespace:
        raise RuntimeError()


class FakeCaptureService:
    image_size = (1920, 886)

    def __init__(self, rsd: object) -> None:
        self.rsd = rsd
        self.closed = False

    async def __aenter__(self) -> "FakeCaptureService":
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True

    async def capture_screenshot(self) -> dict[str, bytes]:
        image = Image.new("RGB", self.image_size, "black")
        width, height = self.image_size
        ImageDraw.Draw(image).rectangle(
            (width // 6, height // 8, width * 5 // 6, height * 7 // 8),
            fill="blue",
        )
        data = io.BytesIO()
        image.save(data, format="PNG")
        return {"image": data.getvalue()}


class FakeTouchService:
    def __init__(self) -> None:
        self.events: list[tuple[int, int, int]] = []

    async def send_touchscreen(self, state: int, x: int, y: int) -> None:
        self.events.append((state, x, y))


class FakeTouchContext:
    def __init__(self, service: FakeTouchService) -> None:
        self.service = service
        self.closed = False

    async def __aenter__(self) -> FakeTouchService:
        return self.service

    async def __aexit__(self, *args: object) -> None:
        self.closed = True


class DirectIOSBridgeTests(unittest.TestCase):
    def test_capture_and_click_use_one_device_session(self) -> None:
        touch_service = FakeTouchService()
        touch_context = FakeTouchContext(touch_service)

        with (
            patch("rtc_bot.ios_device._IMPORT_ERROR", None),
            patch("rtc_bot.ios_device.UserspaceRsdTunnel", FakeTunnel),
            patch("rtc_bot.ios_device.ScreenCaptureService", FakeCaptureService),
            patch(
                "rtc_bot.ios_device.touch_session",
                return_value=touch_context,
            ),
            patch("rtc_bot.ios_device.TOUCHSCREEN_STATE_CONTACT", 1),
            patch("rtc_bot.ios_device.TOUCHSCREEN_STATE_RELEASE", 2),
        ):
            bridge = DirectIOSBridge(BotConfig(), udid="chosen-udid")
            start = bridge.start(
                request_permissions=False,
                require_control=True,
            )
            self.assertTrue(start.ready)

            capture = bridge.capture()
            self.assertIsInstance(capture, CaptureResult)
            assert capture is not None
            self.assertEqual("chosen-udid", capture.source_id)
            self.assertTrue(
                bridge.click(
                    capture,
                    ContentRect(0, 0, 1920, 886),
                    (0.5, 0.5),
                )
            )
            self.assertEqual(
                [(1, 32768, 32768), (2, 32768, 32768)],
                touch_service.events,
            )

            tunnel = bridge._tunnel
            capture_service = bridge._capture_service
            bridge.close()
            self.assertTrue(touch_context.closed)
            self.assertTrue(capture_service.closed)
            self.assertTrue(tunnel.closed)

    def test_click_is_cancelled_if_orientation_changes(self) -> None:
        touch_service = FakeTouchService()
        touch_context = FakeTouchContext(touch_service)

        with (
            patch("rtc_bot.ios_device._IMPORT_ERROR", None),
            patch("rtc_bot.ios_device.UserspaceRsdTunnel", FakeTunnel),
            patch("rtc_bot.ios_device.ScreenCaptureService", FakeCaptureService),
            patch(
                "rtc_bot.ios_device.touch_session",
                return_value=touch_context,
            ),
        ):
            bridge = DirectIOSBridge(BotConfig())
            self.assertTrue(
                bridge.start(
                    request_permissions=False,
                    require_control=True,
                ).ready
            )
            capture = bridge.capture()
            assert capture is not None
            bridge._capture_service.image_size = (886, 1920)
            self.assertFalse(
                bridge.click(
                    capture,
                    ContentRect(0, 0, 1920, 886),
                    (0.5, 0.5),
                )
            )
            self.assertEqual([], touch_service.events)
            bridge.close()

    def test_empty_connection_error_reports_exception_type(self) -> None:
        with (
            patch("rtc_bot.ios_device._IMPORT_ERROR", None),
            patch("rtc_bot.ios_device.UserspaceRsdTunnel", FailingTunnel),
        ):
            bridge = DirectIOSBridge(BotConfig())
            start = bridge.start(
                request_permissions=False,
                require_control=False,
            )
        self.assertFalse(start.ready)
        self.assertIn("RuntimeError", start.messages[0])


if __name__ == "__main__":
    unittest.main()
