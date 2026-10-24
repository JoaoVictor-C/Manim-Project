"""Frame cache for code layers (ADR 0019).

A code layer's scene is played once by real Manim (in a separate process) and
its frames are kept here; the editor then maps ``t`` to a cached frame. Each
frame is stored as the **premultiplied** RGBA crop of its non-transparent
pixels plus the crop's offset — sparse layers stay small, and Cairo paints
premultiplied crops directly (B30). Crops are zlib-compressed (level 1: 34 kB
and 13 ms to decode for a typical 1280x720 frame, B30).

Layout: ``<root>/<key>/index.json`` and one ``<n>.z`` per distinct frame. A
cache is written into a temporary folder and renamed when complete, so a
half-written render is never read. Pure: numpy, zlib and the file system only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import zlib
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FORMAT_VERSION = 1
DECODED_FRAMES = 64  # per clip: scrubbing back and forth stays in memory


def normalize_code(code: str) -> str:
    """Line endings never change what a scene renders, so they never change its identity."""
    return code.replace("\r\n", "\n").replace("\r", "\n")


def code_hash(code: str) -> str:
    """The identity of a piece of code: what the trust store records (ADR 0019)."""
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


def cache_key(
    code: str,
    width: int,
    height: int,
    fps: int,
    frame_height: float,
    manim_version: str,
    helpers: str = "",
) -> str:
    """Everything a render depends on besides the code's own behaviour. ``helpers`` is the project's
    ``helpers.digest`` (ADR 0058): empty without helpers, so those keys are what they always were."""
    parts = [FORMAT_VERSION, code_hash(code), width, height, fps, round(frame_height, 6), manim_version]
    if helpers:
        parts.append(helpers)
    return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class Crop:
    """The visible part of a frame: premultiplied RGBA pixels at ``(x, y)`` in the frame."""

    pixels: np.ndarray  # (h, w, 4) uint8, C-contiguous, premultiplied
    x: int
    y: int


def crop_frame(rgba: np.ndarray) -> Crop | None:
    """The crop of a frame's visible pixels, or None when it is empty.

    Frames come from Manim's Cairo camera with a transparent background, whose
    pixel array is Cairo's own premultiplied surface (``#ff8000`` at 50 % reads
    ``[128, 64, 0, 128]``), so they are kept as they are.
    """
    alpha = rgba[..., 3]
    rows, cols = np.nonzero(alpha.any(axis=1))[0], np.nonzero(alpha.any(axis=0))[0]
    if len(rows) == 0:
        return None
    y0, y1, x0, x1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    return Crop(np.ascontiguousarray(rgba[y0:y1, x0:x1]), int(x0), int(y0))


class CodeClip:
    """A finished render: frame lookup by index, with the last frame held."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
        self.width, self.height, self.fps = index["width"], index["height"], index["fps"]
        self._frames: list[list[int] | None] = index["frames"]  # [file, x, y, w, h] or None (empty)
        self._decoded: OrderedDict[int, Crop] = OrderedDict()

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def duration(self) -> float:
        return self.frame_count / self.fps

    def crop(self, index: int) -> Crop | None:
        """Frame ``index`` (clamped: before the start is the first frame, after the end the last)."""
        if not self._frames:
            return None
        entry = self._frames[min(max(index, 0), len(self._frames) - 1)]
        if entry is None:
            return None
        file, x, y, w, h = entry
        crop = self._decoded.get(file)
        if crop is None:
            raw = zlib.decompress((self.folder / f"{file}.z").read_bytes())
            crop = Crop(np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4).copy(), x, y)
            self._decoded[file] = crop
            if len(self._decoded) > DECODED_FRAMES:
                self._decoded.popitem(last=False)
        else:
            self._decoded.move_to_end(file)
        return crop


class CacheWriter:
    """Writes one render; nothing is visible under the key until ``finish``."""

    def __init__(self, root: Path, key: str, width: int, height: int, fps: int) -> None:
        self.final = root / key
        self.temp = root / f".{key}.{os.getpid()}.{time.monotonic_ns()}.partial"
        self.temp.mkdir(parents=True)
        self.width, self.height, self.fps = width, height, fps
        self._frames: list[list[int] | None] = []
        self._previous: tuple[int, np.ndarray, list[int] | None] | None = None
        self._files = 0

    def add(self, rgba: np.ndarray) -> None:
        """Append a frame (premultiplied RGBA). A repeated frame (same array) reuses the stored one."""
        if self._previous is not None and self._previous[1] is rgba:
            self._frames.append(self._previous[2])
            return
        crop = crop_frame(rgba)
        entry = None
        if crop is not None:
            (self.temp / f"{self._files}.z").write_bytes(zlib.compress(crop.pixels.tobytes(), 1))
            h, w = crop.pixels.shape[:2]
            entry = [self._files, crop.x, crop.y, w, h]
            self._files += 1
        self._frames.append(entry)
        self._previous = (len(self._frames) - 1, rgba, entry)

    def finish(self) -> Path:
        index = {"format": FORMAT_VERSION, "width": self.width, "height": self.height, "fps": self.fps}
        index["frames"] = self._frames
        (self.temp / "index.json").write_text(json.dumps(index), encoding="utf-8")
        if self.final.exists():  # another process rendered the same key meanwhile: same content
            shutil.rmtree(self.temp, ignore_errors=True)
        else:
            self.temp.rename(self.final)
        return self.final

    def abort(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)


class CodeCache:
    """All renders under one folder (the editor's cache dir + ``code``)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._open: dict[str, CodeClip] = {}

    def has(self, key: str) -> bool:
        return (self.root / key / "index.json").is_file()

    def open(self, key: str) -> CodeClip | None:
        """The finished render for ``key``, or None (not rendered yet, or evicted)."""
        clip = self._open.get(key)
        if clip is not None and clip.folder.exists():
            return clip
        if not self.has(key):
            self._open.pop(key, None)
            return None
        clip = CodeClip(self.root / key)
        self._open[key] = clip
        os.utime(clip.folder / "index.json")  # last access, for eviction
        return clip

    def writer(self, key: str, width: int, height: int, fps: int) -> CacheWriter:
        self.root.mkdir(parents=True, exist_ok=True)
        return CacheWriter(self.root, key, width, height, fps)

    def evict(self, max_bytes: int, keep: Iterable[str] = ()) -> list[str]:
        """Delete the least recently used renders until the cache fits ``max_bytes``."""
        if not self.root.is_dir():
            return []
        keep = set(keep)
        entries = []
        for folder in self.root.iterdir():
            index = folder / "index.json"
            if folder.name.startswith(".") or not index.is_file():
                continue
            size = sum(f.stat().st_size for f in folder.iterdir())
            entries.append((index.stat().st_mtime, folder.name, size))
        total = sum(size for _, _, size in entries)
        removed = []
        for _, key, size in sorted(entries):
            if total <= max_bytes:
                break
            if key in keep:
                continue
            shutil.rmtree(self.root / key, ignore_errors=True)
            self._open.pop(key, None)
            total -= size
            removed.append(key)
        return removed
