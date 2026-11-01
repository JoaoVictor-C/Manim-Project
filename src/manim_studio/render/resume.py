"""Resumable exports (ADR 0081): a long export is made of segments kept in a work folder until it is done.

An export of at least two segments (``RenderOptions.segment_seconds``, 10 s by default) renders each
segment into its own small video in ``<stem>.export/`` beside the output: ``segment_0000.mp4``, ... and
``state.json``.
A segment is written as ``segment_NNNN.mp4.tmp``, renamed when complete and only then recorded in the state
(itself replaced atomically), so a crash, a kill or a power cut loses at most the segment being written. The
state names the project and the options it was made for (two hashes); an export that finds a folder for the
same project and options renders only the segments missing from it, one whose file is gone or changed (its
size or SHA-256 differ) included. A folder for anything else is replaced.

No Qt and no Manim: the folder, its state, the hashes and the cleanup; ``cairo_export`` renders and joins.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..core.model.schema import Project
from ..logging_config import get_logger
from .options import RenderOptions, apply_options, frame_window

log = get_logger(__name__)

STATE = "state.json"
SUFFIX = ".export"  # <stem>.export beside the video
FORMAT = 1  # of state.json; a folder of another format is replaced
MAX_AGE = 7 * 24 * 3600.0  # a work folder untouched this long is removed by the next export to that folder
CHUNK = 1 << 20


@dataclass(frozen=True)
class Segment:
    """One finished segment: frames ``[first, last)`` of the scene, in ``file`` (inside the work folder)."""

    index: int
    first: int
    last: int
    file: str
    sha256: str
    size: int


@dataclass
class State:
    """What ``state.json`` says: what the folder was made for, and the segments finished so far."""

    project: str  # project_key of the project as rendered (options applied)
    options: str  # options_key
    first: int  # the export's frame window [first, last)
    last: int
    segment_frames: int
    fps: int
    audio: bool  # the sound is mixed at the end, from the project: whether there is any
    codec: str = ""  # the encoder every segment was made with ("libx264", "h264_nvenc"); "" before the first
    label: str = ""  # its name for the user ("CPU (x264)")
    segments: dict[int, Segment] = field(default_factory=dict)

    def to_json(self) -> str:
        data = asdict(self)
        data["format"] = FORMAT
        data["segments"] = [asdict(s) for s in sorted(self.segments.values(), key=lambda s: s.index)]
        return json.dumps(data, indent=1)

    @classmethod
    def from_json(cls, text: str) -> State:
        data = json.loads(text)
        if data.pop("format", None) != FORMAT:
            raise ValueError("another format")
        segments = {s["index"]: Segment(**s) for s in data.pop("segments")}
        return cls(**data, segments=segments)


def work_dir(out_path: Path) -> Path:
    """Where the segments of an export to ``out_path`` are kept: ``<stem>.export`` beside it."""
    out_path = Path(out_path)
    return out_path.with_name(f"{out_path.stem}{SUFFIX}")


def segment_frames(seconds: float, fps: int) -> int:
    """Frames in one segment: ``seconds`` at ``fps``, at least one."""
    return max(1, round(seconds * fps))


def segmented(first: int, last: int, frames_per_segment: int) -> bool:
    """Is the export long enough to render in segments (two at least)? A shorter one renders in one pass."""
    return last - first >= 2 * frames_per_segment


def spans(first: int, last: int, frames_per_segment: int) -> list[tuple[int, int, int]]:
    """``(index, a, b)`` for each segment of ``[first, last)``; the last may be shorter."""
    return [
        (index, a, min(a + frames_per_segment, last))
        for index, a in enumerate(range(first, last, frames_per_segment))
    ]


def project_key(project: Project) -> str:
    """SHA-256 of the project as it is rendered (the options applied: canvas, size, fps, subtitle style)."""
    return hashlib.sha256(project.model_dump_json(by_alias=True).encode("utf-8")).hexdigest()


def options_key(options: RenderOptions, trust: bool = False) -> str:
    """SHA-256 of what decides the pixels besides the project: range, quality, encoder choice, segment
    length and whether Python code may run. The number of render processes is not among them."""
    data = asdict(options)
    data.pop("jobs", None)
    for name in ("start", "end", "segment_seconds"):  # 1 and 1.0 are the same option
        if data.get(name) is not None:
            data[name] = float(data[name])
    data["trust"] = bool(trust)
    data["format"] = FORMAT
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def load(work: Path) -> State | None:
    """The folder's state, or None (no folder, no state, or one this version cannot read)."""
    try:
        return State.from_json((work / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if (work / STATE).exists():
            log.warning("export: ignoring the unreadable %s (%s)", work / STATE, exc)
        return None


def save(work: Path, state: State) -> None:
    """Write ``state.json`` atomically: the old one stays whole until the new one is."""
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / f"{STATE}.tmp"
    with open(tmp, "w", encoding="utf-8") as stream:
        stream.write(state.to_json())
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, work / STATE)


def intact(work: Path, segment: Segment, check_hash: bool = True) -> bool:
    """Is the segment's file there, as it was written (its size, and with ``check_hash`` its SHA-256)?"""
    path = work / segment.file
    try:
        if path.stat().st_size != segment.size:
            return False
        return not check_hash or file_sha256(path) == segment.sha256
    except OSError:
        return False


def _ours(path: Path) -> bool:
    """A file an export writes in its work folder (nothing else is ever deleted there)."""
    name = path.name
    return name in (STATE, f"{STATE}.tmp") or (
        name.startswith("segment_") and (name.endswith(".mp4") or name.endswith(".mp4.tmp"))
    )


def discard(work: Path) -> None:
    """Remove a work folder: the files an export writes, then the folder if nothing else is in it."""
    if not work.is_dir():
        return
    for path in work.iterdir():
        if path.is_file() and _ours(path):
            with contextlib.suppress(OSError):
                path.unlink()
    try:
        work.rmdir()
    except OSError:
        log.warning("export: left %s, it holds files an export did not write", work)


def remove_temporary(work: Path) -> None:
    """Remove half-written files (``*.tmp``) left by an export that stopped."""
    if work.is_dir():
        for path in work.glob("*.tmp"):
            if _ours(path):
                with contextlib.suppress(OSError):
                    path.unlink()


def sweep(
    folder: Path, keep: Path | None = None, max_age: float = MAX_AGE, now: float | None = None
) -> list[Path]:
    """Remove work folders in ``folder`` (only ``*.export`` folders holding a ``state.json``) untouched for
    ``max_age`` seconds, except ``keep``; returns those removed."""
    now = time.time() if now is None else now
    removed: list[Path] = []
    try:
        candidates = [p for p in Path(folder).iterdir() if p.name.endswith(SUFFIX) and p.is_dir()]
    except OSError:
        return removed
    for work in candidates:
        if keep is not None and work == keep:
            continue
        state = work / STATE
        try:
            touched = max(p.stat().st_mtime for p in work.iterdir())
        except (OSError, ValueError):  # ValueError: empty
            continue
        if state.is_file() and now - touched > max_age:
            log.info("export: removing the old work folder %s", work)
            discard(work)
            removed.append(work)
    return removed


@dataclass(frozen=True)
class Pending:
    """An interrupted export that can resume: ``done`` of ``total`` segments are finished."""

    work: Path
    done: int
    total: int


def pending(project: Project, options: RenderOptions, out_path: Path, trust: bool = False) -> Pending | None:
    """The work folder an export of ``project`` to ``out_path`` with ``options`` would resume from, if there
    is one for the same project and options with at least one segment done (files checked by size only)."""
    work = work_dir(out_path)
    state = load(work)
    if state is None:
        return None
    sized = apply_options(project, options)
    try:
        first, last = frame_window(sized.canvas, options)
    except ValueError:
        return None
    frames = segment_frames(options.segment_seconds, sized.canvas.fps)
    if not matches(state, sized, options, trust, first, last, frames):
        return None
    total = len(spans(first, last, frames))
    done = sum(1 for s in state.segments.values() if intact(work, s, check_hash=False))
    return Pending(work, done, total) if done else None


def matches(
    state: State, project: Project, options: RenderOptions, trust: bool, first: int, last: int, frames: int
) -> bool:
    """Was the state made for this project (options applied) and these options?"""
    return (
        state.project == project_key(project)
        and state.options == options_key(options, trust)
        and (state.first, state.last, state.segment_frames, state.fps)
        == (first, last, frames, project.canvas.fps)
    )
