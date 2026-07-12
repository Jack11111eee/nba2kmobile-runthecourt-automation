from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).parents[1]
ASSET_DIRS = (
    ROOT / "rtc_bot" / "assets" / "reference",
    ROOT / "tests" / "fixtures",
)
PRIVATE_SCREEN_PREFIXES = ("vs_ready", "win_result")
NAME_RECTS = (
    (0.085, 0.608, 0.298, 0.663),
    (0.704, 0.608, 0.916, 0.663),
)


def redact_names(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for left, top, right, bottom in NAME_RECTS:
        draw.rectangle(
            (
                round(left * width),
                round(top * height),
                round(right * width),
                round(bottom * height),
            ),
            fill=(6, 8, 12),
        )


def sanitize(path: Path) -> None:
    with Image.open(path) as source:
        image = source.convert("RGB")
    image.info.clear()
    if path.stem.startswith(PRIVATE_SCREEN_PREFIXES):
        redact_names(image)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        image.save(path, format="JPEG", quality=95, optimize=True)
    else:
        image.save(path, format="PNG", optimize=True)


def main() -> None:
    for directory in ASSET_DIRS:
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                sanitize(path)


if __name__ == "__main__":
    main()
