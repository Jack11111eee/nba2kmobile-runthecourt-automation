from __future__ import annotations

import io
import sys
from collections.abc import Iterable

from PIL import Image

from rtc_bot.model import ScreenState


_EXCEPTION_KEYWORDS = (
    (
        ScreenState.NETWORK_ERROR,
        (
            "network error",
            "connection error",
            "connection lost",
            "unable to connect",
            "网络错误",
            "网络异常",
            "网络连接失败",
            "无法连接",
        ),
    ),
    (
        ScreenState.ENERGY_SHORTAGE,
        (
            "not enough energy",
            "insufficient energy",
            "out of energy",
            "体力不足",
            "能量不足",
        ),
    ),
    (
        ScreenState.INVENTORY_FULL,
        (
            "inventory is full",
            "inventory full",
            "collection is full",
            "collection full",
            "库存已满",
            "背包已满",
            "收藏已满",
        ),
    ),
    (
        ScreenState.MAINTENANCE,
        (
            "under maintenance",
            "server maintenance",
            "scheduled maintenance",
            "服务器维护",
            "系统维护",
        ),
    ),
    (
        ScreenState.EVENT_ENDED,
        (
            "event has ended",
            "event ended",
            "event is over",
            "event expired",
            "活动已结束",
            "活动已过期",
        ),
    ),
)

EXCEPTION_STATES = frozenset(state for state, _ in _EXCEPTION_KEYWORDS)


def classify_exception_text(text: str | Iterable[str]) -> ScreenState | None:
    combined = text if isinstance(text, str) else " ".join(text)
    normalized = " ".join(combined.casefold().split())
    for state, keywords in _EXCEPTION_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return state
    return None


def recognize_text(image: Image.Image) -> tuple[str, ...]:
    if sys.platform != "darwin":
        return ()
    try:
        from Foundation import NSData
        import Vision
    except ImportError:
        return ()

    try:
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        payload = encoded.getvalue()
        data = NSData.dataWithBytes_length_(payload, len(payload))

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(
            Vision.VNRequestTextRecognitionLevelAccurate
        )
        request.setRecognitionLanguages_(["en-US", "zh-Hans", "zh-Hant"])
        request.setUsesLanguageCorrection_(True)

        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
            data, {}
        )
        succeeded, error = handler.performRequests_error_([request], None)
        if not succeeded or error is not None:
            return ()

        texts: list[str] = []
        for observation in request.results() or ():
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            text = str(candidates[0].string()).strip()
            if text:
                texts.append(text)
        return tuple(texts)
    except Exception:
        return ()
