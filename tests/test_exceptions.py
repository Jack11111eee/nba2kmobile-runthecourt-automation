from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from rtc_bot.exceptions import classify_exception_text, recognize_text
from rtc_bot.model import ScreenState


class ExceptionClassificationTests(unittest.TestCase):
    def test_classifies_supported_stop_messages(self) -> None:
        cases = [
            ("Network error. Please try again.", ScreenState.NETWORK_ERROR),
            ("Not enough energy to start this game.", ScreenState.ENERGY_SHORTAGE),
            ("Your inventory is full.", ScreenState.INVENTORY_FULL),
            ("Servers are currently under maintenance.", ScreenState.MAINTENANCE),
            ("This event has ended.", ScreenState.EVENT_ENDED),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(expected, classify_exception_text(text))

    def test_classifies_english_variants_and_chinese_messages(self) -> None:
        cases = [
            ("Unable to connect to the server.", ScreenState.NETWORK_ERROR),
            ("网络连接失败，请重试。", ScreenState.NETWORK_ERROR),
            ("体力不足。", ScreenState.ENERGY_SHORTAGE),
            ("卡牌库存已满。", ScreenState.INVENTORY_FULL),
            ("服务器维护中。", ScreenState.MAINTENANCE),
            ("活动已结束。", ScreenState.EVENT_ENDED),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(expected, classify_exception_text(text))

    def test_ocr_returns_no_text_outside_macos(self) -> None:
        with patch("rtc_bot.exceptions.sys.platform", "linux"):
            self.assertEqual((), recognize_text(Image.new("RGB", (32, 32), "white")))

    def test_ocr_reads_text_with_apple_vision(self) -> None:
        class Candidate:
            def string(self) -> str:
                return "Network error"

        class Observation:
            def topCandidates_(self, count: int) -> list[Candidate]:
                return [Candidate()] if count else []

        class Request:
            @classmethod
            def alloc(cls) -> Request:
                return cls()

            def init(self) -> Request:
                return self

            def setRecognitionLevel_(self, level: int) -> None:
                self.level = level

            def setRecognitionLanguages_(self, languages: list[str]) -> None:
                self.languages = languages

            def setUsesLanguageCorrection_(self, enabled: bool) -> None:
                self.uses_language_correction = enabled

            def results(self) -> list[Observation]:
                return [Observation()]

        class Handler:
            @classmethod
            def alloc(cls) -> Handler:
                return cls()

            def initWithData_options_(self, data: bytes, options: dict) -> Handler:
                return self

            def performRequests_error_(
                self, requests: list[Request], error: None
            ) -> tuple[bool, None]:
                return True, None

        class Data:
            @staticmethod
            def dataWithBytes_length_(data: bytes, length: int) -> bytes:
                return data[:length]

        foundation = SimpleNamespace(NSData=Data)
        vision = SimpleNamespace(
            VNImageRequestHandler=Handler,
            VNRecognizeTextRequest=Request,
            VNRequestTextRecognitionLevelAccurate=1,
        )
        with (
            patch("rtc_bot.exceptions.sys.platform", "darwin"),
            patch.dict(
                "sys.modules",
                {"Foundation": foundation, "Vision": vision},
            ),
        ):
            result = recognize_text(Image.new("RGB", (32, 32), "white"))
        self.assertEqual(("Network error",), result)


if __name__ == "__main__":
    unittest.main()
