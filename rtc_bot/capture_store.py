from __future__ import annotations

from pathlib import Path

from PIL import Image


class CaptureStore:
    def __init__(self, directory: Path, *, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.directory = directory
        self.max_bytes = max_bytes
        self._written_count = 0
        self._written_bytes = 0

    @property
    def written_count(self) -> int:
        return self._written_count

    @property
    def written_bytes(self) -> int:
        return self._written_bytes

    def save(self, image: Image.Image, name: str) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{name}.png"
        image.save(path, format="PNG")
        self._written_count += 1
        self._written_bytes += path.stat().st_size
        self._prune(path)
        return path

    def _prune(self, latest: Path) -> None:
        captures: list[tuple[int, int, Path]] = []
        total_bytes = 0
        for path in self.directory.glob("*.png"):
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            captures.append((stat.st_mtime_ns, stat.st_size, path))
            total_bytes += stat.st_size

        for _, size, path in sorted(captures):
            if total_bytes <= self.max_bytes:
                break
            if path == latest:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            total_bytes -= size
