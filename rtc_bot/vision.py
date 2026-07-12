from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

from rtc_bot.config import BotConfig
from rtc_bot.model import Detection, NormalizedRect, ScreenState

GAME_ASPECT = 1920 / 886
FEATURE_SIZE = (64, 30)
RESULT_ANCHOR_MAX_DISTANCE = 0.14
RESULT_ANCHOR_MARGIN = 0.03
REWARD_FOCUS_MIN_RATIO = 1.8
PACK_OPEN_STRUCTURE_MIN_RATIO = 4.0
PACK_OPEN_TITLE_MIN_SCORE = 1.0


@dataclass(frozen=True)
class ContentRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class Reference:
    state: ScreenState
    name: str
    feature: np.ndarray
    result_anchor_feature: np.ndarray


def find_content_rect(image: Image.Image) -> ContentRect:
    width, height = image.size
    aspect = width / max(height, 1)
    if abs(aspect - GAME_ASPECT) / GAME_ASPECT < 0.025:
        return ContentRect(0, 0, width, height)

    target_height = round(width / GAME_ASPECT)
    if target_height <= height:
        # iPhone Mirroring adds chrome above the phone image. Bottom alignment
        # preserves the home indicator and lower action buttons.
        return ContentRect(0, height - target_height, width, height)

    target_width = round(height * GAME_ASPECT)
    left = max(0, (width - target_width) // 2)
    return ContentRect(left, 0, min(width, left + target_width), height)


def crop_content(image: Image.Image) -> tuple[Image.Image, ContentRect]:
    rect = find_content_rect(image)
    return image.crop((rect.left, rect.top, rect.right, rect.bottom)), rect


def frame_signature(image: Image.Image) -> int:
    gray = image.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
    pixels = np.asarray(gray, dtype=np.int16)
    bits = pixels[:, 1:] > pixels[:, :-1]
    signature = 0
    for bit in bits.flatten():
        signature = (signature << 1) | int(bit)
    return signature


def signature_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def coarse_feature(image: Image.Image) -> np.ndarray:
    content, _ = crop_content(image)
    preview = content.convert("RGB").resize((256, 118), Image.Resampling.BILINEAR)
    blurred = preview.filter(ImageFilter.GaussianBlur(radius=3))
    resized = blurred.resize(FEATURE_SIZE, Image.Resampling.BILINEAR)
    feature = np.asarray(resized, dtype=np.float32) / 255.0
    return feature


def result_anchor_feature(image: Image.Image) -> np.ndarray:
    content, _ = crop_content(image)
    width, height = content.size
    region = content.crop(
        (
            round(width * 0.40),
            round(height * 0.34),
            round(width * 0.60),
            round(height * 0.60),
        )
    )
    preview = region.convert("RGB").resize((96, 63), Image.Resampling.BILINEAR)
    blurred = preview.filter(ImageFilter.GaussianBlur(radius=2))
    resized = blurred.resize((32, 20), Image.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.float32) / 255.0


def feature_distance(left: np.ndarray, right: np.ndarray) -> float:
    # A small contrast normalization makes the metric less sensitive to the
    # brightness difference between native recordings and mirrored capture.
    left_centered = left - left.mean(axis=(0, 1), keepdims=True)
    right_centered = right - right.mean(axis=(0, 1), keepdims=True)
    numerator = np.mean(np.abs(left_centered - right_centered))
    color_delta = np.mean(np.abs(left.mean(axis=(0, 1)) - right.mean(axis=(0, 1))))
    return float(numerator + color_delta * 0.35)


def _component_rectangles(mask: np.ndarray) -> list[NormalizedRect]:
    labels, count = ndimage.label(mask)
    if count == 0:
        return []

    height, width = mask.shape
    rectangles: list[NormalizedRect] = []
    for item in ndimage.find_objects(labels):
        if item is None:
            continue
        y_slice, x_slice = item
        pixel_width = x_slice.stop - x_slice.start
        pixel_height = y_slice.stop - y_slice.start
        area = pixel_width * pixel_height
        aspect = pixel_width / max(pixel_height, 1)
        if area < width * height * 0.0012:
            continue
        if pixel_height < height * 0.035 or aspect < 2.2:
            continue
        rectangles.append(
            NormalizedRect(
                x_slice.start / width,
                y_slice.start / height,
                x_slice.stop / width,
                y_slice.stop / height,
            )
        )
    return rectangles


def find_green_buttons(image: Image.Image) -> list[NormalizedRect]:
    content, _ = crop_content(image)
    rgb = np.asarray(content.convert("RGB"), dtype=np.int16)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mask = (
        (green > 105)
        & (green > red * 1.12)
        & (green > blue * 1.08)
        & ((green - np.minimum(red, blue)) > 25)
    )
    mask = ndimage.binary_opening(mask, structure=np.ones((3, 5), dtype=bool))
    mask = ndimage.binary_closing(mask, structure=np.ones((5, 13), dtype=bool))
    return _component_rectangles(mask)


def find_cyan_buttons(image: Image.Image) -> list[NormalizedRect]:
    content, _ = crop_content(image)
    rgb = np.asarray(content.convert("RGB"), dtype=np.int16)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mask = (
        (green > 130)
        & (blue > 145)
        & (green > red * 1.25)
        & (blue > red * 1.25)
        & (np.abs(green - blue) < 100)
    )
    mask = ndimage.binary_opening(mask, structure=np.ones((3, 5), dtype=bool))
    mask = ndimage.binary_closing(mask, structure=np.ones((5, 13), dtype=bool))
    return _component_rectangles(mask)


def choose_button(
    buttons: list[NormalizedRect],
    *,
    min_y: float,
    min_x: float = 0.0,
    max_x: float = 1.0,
) -> NormalizedRect | None:
    candidates = [
        button
        for button in buttons
        if button.center[1] >= min_y
        and min_x <= button.center[0] <= max_x
        and button.width <= 0.35
        and button.height <= 0.16
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.width * item.height)


def fixed_cyan_button_if_present(
    image: Image.Image, rect: NormalizedRect
) -> NormalizedRect | None:
    content, _ = crop_content(image)
    width, height = content.size
    region = content.crop(
        (
            round(rect.left * width),
            round(rect.top * height),
            round(rect.right * width),
            round(rect.bottom * height),
        )
    )
    mean = np.asarray(region.convert("RGB"), dtype=np.float32).mean(axis=(0, 1))
    red, green, blue = (float(value) for value in mean)
    if green > 125 and blue > 150 and green - red > 45 and blue - red > 75:
        return rect
    return None


def pack_open_structure_score(image: Image.Image) -> float:
    content, _ = crop_content(image)
    rgb = np.asarray(content.convert("RGB"), dtype=np.float32)
    height, width = rgb.shape[:2]

    def activity(left: float, top: float, right: float, bottom: float) -> float:
        region = rgb[
            round(top * height) : round(bottom * height),
            round(left * width) : round(right * width),
        ]
        vertical = np.abs(np.diff(region, axis=0)).mean()
        horizontal = np.abs(np.diff(region, axis=1)).mean()
        return float(vertical + horizontal)

    center = activity(0.40, 0.25, 0.60, 0.78)
    left = activity(0.10, 0.25, 0.30, 0.78)
    right = activity(0.70, 0.25, 0.90, 0.78)
    background = (left + right) / 2
    return center / (background + 1.0)


def pack_open_title_score(image: Image.Image) -> float:
    content, _ = crop_content(image)
    rgb = np.asarray(content.convert("RGB"), dtype=np.float32)
    height, width = rgb.shape[:2]
    region = rgb[
        round(0.05 * height) : round(0.18 * height),
        round(0.65 * width) : round(0.93 * width),
    ]
    mean = region.mean(axis=(0, 1))
    activity = float(
        np.abs(np.diff(region, axis=0)).mean()
        + np.abs(np.diff(region, axis=1)).mean()
    )
    blue_delta = float(mean[2] - mean[0])
    color_score = blue_delta / 15.0
    activity_score = min(activity / 2.0, 12.0 / max(activity, 0.1))
    return min(color_score, activity_score)


def reward_focus_score(image: Image.Image) -> float:
    content, _ = crop_content(image)
    gray = np.asarray(
        content.convert("L").resize((300, 138), Image.Resampling.BILINEAR),
        dtype=np.float32,
    )
    center = gray[20:125, 105:195]
    sides = np.concatenate(
        (gray[20:125, :85].ravel(), gray[20:125, 215:].ravel())
    )
    return float(center.mean() / (sides.mean() + 1.0))


class ReferenceLibrary:
    def __init__(self, reference_dir: Path) -> None:
        self.reference_dir = reference_dir
        self.references = self._load()

    def _load(self) -> list[Reference]:
        references: list[Reference] = []
        if not self.reference_dir.exists():
            return references
        for path in sorted(self.reference_dir.glob("*.jpg")):
            state_name = path.stem.split("__", 1)[0]
            try:
                state = ScreenState(state_name)
            except ValueError:
                continue
            with Image.open(path) as image:
                references.append(
                    Reference(
                        state=state,
                        name=path.name,
                        feature=coarse_feature(image.copy()),
                        result_anchor_feature=result_anchor_feature(image.copy()),
                    )
                )
        return references

    def nearest(self, image: Image.Image) -> tuple[Reference | None, float]:
        if not self.references:
            return None, 1.0
        feature = coarse_feature(image)
        best = min(
            self.references,
            key=lambda reference: feature_distance(feature, reference.feature),
        )
        return best, feature_distance(feature, best.feature)

    def nearest_result_anchor(
        self, image: Image.Image, states: set[ScreenState]
    ) -> tuple[Reference | None, float]:
        candidates = [
            reference for reference in self.references if reference.state in states
        ]
        if not candidates:
            return None, 1.0
        feature = result_anchor_feature(image)
        best = min(
            candidates,
            key=lambda reference: feature_distance(
                feature, reference.result_anchor_feature
            ),
        )
        return best, feature_distance(feature, best.result_anchor_feature)


class ScreenDetector:
    def __init__(self, config: BotConfig, reference_dir: Path | None = None) -> None:
        if reference_dir is None:
            reference_dir = Path(__file__).parent / "assets" / "reference"
        self.config = config
        self.library = ReferenceLibrary(reference_dir)

    def detect(self, image: Image.Image) -> Detection:
        content, _ = crop_content(image)
        signature = frame_signature(content)
        reference, distance = self.library.nearest(content)
        if reference is None:
            return Detection(
                state=ScreenState.UNKNOWN,
                confidence=0.0,
                frame_signature=signature,
                reason="no reference assets",
            )

        state = reference.state
        confidence = max(0.0, 1.0 - distance / self.config.state_distance_threshold)
        anchor_reason = ""

        button: NormalizedRect | None = None

        if state in (
            ScreenState.EVENT_HOME,
            ScreenState.STAGE_SELECT,
            ScreenState.VS_READY,
            ScreenState.WIN_RESULT,
            ScreenState.LINEUP,
        ):
            green_buttons = find_green_buttons(content)
        else:
            green_buttons = []

        if state == ScreenState.EVENT_HOME:
            button = choose_button(green_buttons, min_y=0.72, min_x=0.65)
        elif state == ScreenState.STAGE_SELECT:
            button = choose_button(green_buttons, min_y=0.80)
        elif state in (ScreenState.VS_READY, ScreenState.WIN_RESULT):
            button = choose_button(green_buttons, min_y=0.76, min_x=0.65)
        elif state == ScreenState.LINEUP:
            button = choose_button(green_buttons, min_y=0.74, min_x=0.65)
        elif state == ScreenState.PACK_OPEN:
            # Pack artwork varies by reward source, so validate the shared
            # layout: a detailed vertical object centered on a quiet backdrop
            # and the blue-gray title slab in the upper-right corner.
            structure_score = pack_open_structure_score(content)
            title_score = pack_open_title_score(content)
            anchor_reason = (
                f" pack_structure={structure_score:.2f}"
                f" pack_title={title_score:.2f}"
            )
            if (
                structure_score >= PACK_OPEN_STRUCTURE_MIN_RATIO
                and title_score >= PACK_OPEN_TITLE_MIN_SCORE
            ):
                button = NormalizedRect(0.40, 0.25, 0.60, 0.78)
        elif state in (ScreenState.PACK_REVEAL, ScreenState.PACK_SUMMARY):
            cyan_buttons = find_cyan_buttons(content)
            show_all_button = fixed_cyan_button_if_present(
                content, NormalizedRect(0.15, 0.80, 0.33, 0.89)
            )
            continue_button = fixed_cyan_button_if_present(
                content, NormalizedRect(0.68, 0.80, 0.85, 0.89)
            )
            if show_all_button is None:
                show_all_button = choose_button(
                    cyan_buttons, min_y=0.70, max_x=0.55
                )
            if continue_button is None:
                continue_button = choose_button(
                    cyan_buttons, min_y=0.74, min_x=0.58
                )
            if continue_button is not None:
                state = ScreenState.PACK_SUMMARY
                button = continue_button
            elif show_all_button is not None:
                state = ScreenState.PACK_REVEAL
                button = show_all_button
            else:
                state = ScreenState.PACK_FLIP_ANIMATION

        if state == ScreenState.QUARTER_REWARD:
            focus_score = reward_focus_score(content)
            anchor_reason = f" reward_focus={focus_score:.2f}"
            if focus_score < REWARD_FOCUS_MIN_RATIO:
                state = ScreenState.AUTO_SUBSTITUTION

        if state in (ScreenState.VS_READY, ScreenState.WIN_RESULT):
            _, win_distance = self.library.nearest_result_anchor(
                content, {ScreenState.WIN_RESULT}
            )
            _, vs_distance = self.library.nearest_result_anchor(
                content, {ScreenState.VS_READY}
            )
            anchor_reason = (
                f" win_anchor={win_distance:.4f} vs_anchor={vs_distance:.4f}"
            )

            win_is_clear = (
                win_distance <= RESULT_ANCHOR_MAX_DISTANCE
                and win_distance + RESULT_ANCHOR_MARGIN < vs_distance
            )
            vs_is_clear = (
                vs_distance <= RESULT_ANCHOR_MAX_DISTANCE
                and vs_distance + RESULT_ANCHOR_MARGIN < win_distance
            )
            if win_is_clear:
                state = ScreenState.WIN_RESULT
            elif vs_is_clear:
                state = ScreenState.VS_READY
            else:
                if button is not None:
                    state = ScreenState.LOSS_RESULT
                    button = None
                    confidence = max(confidence, 0.65)
                else:
                    state = ScreenState.UNKNOWN
                    confidence = 0.0

        if distance > self.config.state_distance_threshold:
            state = ScreenState.UNKNOWN
            button = None
            confidence = 0.0

        reason = (
            f"reference={reference.name} distance={distance:.4f}{anchor_reason}"
        )
        if state not in (
            ScreenState.GAMEPLAY,
            ScreenState.AUTO_SUBSTITUTION,
            ScreenState.PACK_FLIP_ANIMATION,
            ScreenState.QUARTER_REWARD,
            ScreenState.UNKNOWN,
            ScreenState.LOSS_RESULT,
        ) and button is None:
            reason += " button=missing"
            confidence *= 0.65

        return Detection(
            state=state,
            confidence=confidence,
            frame_signature=signature,
            button=button,
            reason=reason,
        )
