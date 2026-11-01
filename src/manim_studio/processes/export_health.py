"""The export health report (ADR 0066): what will be slow or will not work, found before the export starts.

``check`` looks only at the project, the options and the cache folders: it never runs the user's code, never
starts LaTeX and never draws a frame, so the Deliver page can show it on every change. Its time figures are
estimates, worded as such: the code-layer figure comes from the angular momentum project (seven scenes, 278 s,
rendered in about 230 s: 0.8 s of rendering for each second of scene), everything else from the figures in
B75 in docs/logs/benchmarks.md. The frame cost is measured only when asked (``measure``, a few frames drawn
here), because that takes seconds.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ..core.code import python_object
from ..core.code.code_cache import CodeCache
from ..core.engine.evaluator import Evaluator
from ..core.model.schema import CODE_TYPES, PYTHON_TYPES, TEXT_TYPES, Project
from ..render import encoders, farm, resources
from ..render.options import RenderOptions, apply_options, frame_window
from . import code_batch

CODE_SECONDS_PER_SECOND = 0.8  # rendering a code layer: seconds of work for each second of its scene
LATEX_SECONDS = 2.0  # a LaTeX object's first build
DISK_MARGIN = 2 * 2**30  # free space an export should leave beyond what it writes
CODE_CACHE_BYTES_PER_PIXEL_SECOND = (
    0.05  # cached crops, compressed: a rough figure from the 587 MB / 278 s case
)

INFO, WARNING, PROBLEM = "info", "warning", "problem"


@dataclass(frozen=True)
class Finding:
    severity: str  # INFO, WARNING (slow or degraded) or PROBLEM (will not do what was asked)
    title: str
    detail: str = ""
    seconds: float = 0.0  # time this adds to the export, 0 when it adds none or it is unknown
    kind: str = ""  # what it is about, for the Deliver page's health chips: "code", "text", "untrusted", ...
    layers: tuple[str, ...] = ()  # the layers it names, so a chip can open the first one


@dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...]
    frames: int
    seconds: float  # the estimate of the whole export, from the findings that carry a time

    @property
    def worst(self) -> str:
        order = (INFO, WARNING, PROBLEM)
        return max((f.severity for f in self.findings), key=order.index, default=INFO)

    def lines(self) -> list[str]:
        marks = {INFO: "  ", WARNING: "! ", PROBLEM: "X "}
        out = []
        for finding in self.findings:
            time = f" (~{clock(finding.seconds)})" if finding.seconds >= 1 else ""
            out.append(f"{marks[finding.severity]}{finding.title}{time}")
            if finding.detail:
                out.append(f"    {finding.detail}")
        return out


def clock(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} min {rest:02d} s" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"


def check(
    project: Project,
    options: RenderOptions,
    cache_dir: Path,
    output: Path | None = None,
    trust_code: bool = False,
    frame_seconds: float | None = None,
) -> Report:
    """Everything worth knowing before exporting ``project`` with ``options`` (frame window and size applied).

    ``frame_seconds``: the measured cost of drawing one frame here (``measure``); without it the report says
    nothing about the frames' own time."""
    sized = apply_options(project, options)
    canvas = sized.canvas
    first, last = frame_window(canvas, options)
    frames = last - first
    findings: list[Finding] = []
    runners = farm.plan(options.jobs, frames, canvas.width_px * canvas.height_px * 4)

    findings += _code_layers(sized, options, cache_dir, trust_code, first, last)
    findings += _text(sized, cache_dir)
    findings += _untrusted(sized, trust_code)
    findings += _frames(frames, canvas.width_px, canvas.height_px, runners, frame_seconds)
    findings += _encoder(options, frames, canvas.width_px, canvas.height_px, runners)
    findings += _disk(sized, options, frames, cache_dir, output)
    rank = {PROBLEM: 0, WARNING: 1, INFO: 2}
    ordered = sorted(findings, key=lambda f: (rank[f.severity], -f.seconds))
    return Report(tuple(ordered), frames, sum(f.seconds for f in findings))


def measure(project: Project, options: RenderOptions) -> float:
    """Seconds to draw one frame of this export, from a few frames drawn here (a second or two)."""
    import time

    from ..render.cairo_export import make_camera, render_frame

    sized = apply_options(project, options)
    canvas = sized.canvas
    first, last = frame_window(canvas, options)
    camera, evaluator = make_camera(canvas, sized.camera, sized.view_background), Evaluator(sized)
    costs = []
    for k in (1, 2, 3):
        t = (first + (last - first) * k // 4) / canvas.fps
        for _ in range(2):  # the second time is the steady cost
            started = time.perf_counter()
            render_frame(camera, [m for _, m in evaluator.frame_layers(t)], evaluator.overlay(t), copy=False)
            took = time.perf_counter() - started
        costs.append(took)
    return sorted(costs)[1]


# -- the checks ----------------------------------------------------------------------------------


def _code_layers(sized: Project, options: RenderOptions, cache_dir: Path, trust: bool, first: int, last: int):
    evaluator = Evaluator(sized)
    cache = CodeCache(cache_dir / "code")  # the folder the export will use, not the process's own
    missing, seconds = [], 0.0
    lengths: dict[str, float] = {}
    seen: set[str] = set()
    for layer in sized.layers:
        if layer.spec is None or layer.spec.type not in CODE_TYPES:
            continue
        key = evaluator.code_key(layer)
        if key in seen or cache.has(key):
            continue
        seen.add(key)
        length = _scene_seconds(evaluator, layer, sized.canvas.duration)
        missing.append(layer.id)
        lengths[layer.id] = length
        seconds += length * CODE_SECONDS_PER_SECOND
    if not missing:
        return []
    names = ", ".join(missing[:4]) + (f" and {len(missing) - 4} more" if len(missing) > 4 else "")
    if not trust:
        return [
            Finding(
                WARNING,
                f"{len(missing)} code layer(s) will be drawn as placeholders",
                f"{names} not rendered at this size, and exporting does not run code without trust.",
                kind="untrusted",
                layers=tuple(missing),
            )
        ]
    runners = code_batch.plan(options.jobs, len(missing))
    parallel = max(seconds / runners, max(lengths.values(), default=0.0) * CODE_SECONDS_PER_SECOND)
    return [
        Finding(
            WARNING,
            f"{len(missing)} code layer(s) must be rendered at this size",
            f"{names}; {runners} at a time. Exporting at the editor's own size reuses the editor's renders.",
            parallel,
            kind="code",
            layers=tuple(missing),
        )
    ]


def _scene_seconds(evaluator: Evaluator, layer, duration: float) -> float:
    """How long a code layer's scene plays: its lifetime, which has no end until it is rendered (its length is
    its content's), so no longer than the scene."""
    start, end = evaluator.lifetime(layer)
    return max(0.0, min(end, duration) - start)


def _text(sized: Project, cache_dir: Path) -> list[Finding]:
    objects = [
        layer
        for layer in sized.layers
        if layer.spec is not None and layer.spec.type in (TEXT_TYPES - {"Text"} | {"DecimalNumber"})
    ]
    if not objects:
        return []
    tex = cache_dir / "Tex"
    warmed = len(list(tex.glob("*.svg"))) if tex.is_dir() else 0
    if warmed >= len(objects):
        return []
    return [
        Finding(
            INFO,
            f"{len(objects)} LaTeX object(s); the cache holds {warmed} LaTeX drawing(s)",
            "A LaTeX object not yet built takes a second or two the first time; the editor builds them "
            "as you edit, so this only matters for a project opened fresh.",
            LATEX_SECONDS * (len(objects) - warmed) / 2,
            kind="text",
            layers=tuple(layer.id for layer in objects),
        )
    ]


def _untrusted(sized: Project, trust: bool) -> list[Finding]:
    if trust:
        return []
    names = [
        layer.id
        for layer in sized.layers
        if layer.spec is not None
        and layer.spec.type in PYTHON_TYPES
        and not python_object.is_trusted(str(layer.spec.params.get("code", "")))
    ]
    if not names:
        return []
    return [
        Finding(
            WARNING,
            f"{len(names)} Python object(s) will be drawn as placeholders",
            f"{', '.join(names[:4])}: their code is not trusted yet.",
            kind="untrusted",
            layers=tuple(names),
        )
    ]


def _frames(frames: int, width: int, height: int, runners: int, frame_seconds: float | None) -> list[Finding]:
    out: list[Finding] = []
    if frame_seconds is not None:
        total = frame_seconds * frames
        detail = f"{frame_seconds * 1000:.0f} ms a frame, {frames} frames"
        if runners > 1:
            detail += f"; about {runners} render processes, which in practice give 1.5-2x on a laptop"
            total /= 1.7
        out.append(Finding(INFO, "Drawing the frames", detail, total))
    ring = width * height * 4 * 2 * max(runners, 1)
    if ring > 512 * 2**20:
        out.append(
            Finding(
                WARNING,
                f"Very large frames ({width}x{height})",
                f"Each is {width * height * 4 / 2**20:.0f} MB; the export holds several at once, "
                f"and free memory is {resources.available_memory() / 2**30:.1f} GB.",
            )
        )
    if width * height > 3840 * 2160:
        out.append(Finding(WARNING, "Above 4K", "Expect long render times and a very large file."))
    return out


def _encoder(options: RenderOptions, frames: int, width: int, height: int, runners: int) -> list[Finding]:
    chosen = encoders.candidates(options.encoder, options.crf, frames, width, height, farming=runners > 1)
    first = chosen[0]
    if options.encoder == "gpu" and not first.hardware:
        reason = (
            f"{max(width, height)} px is beyond the card's H.264 limit ({encoders.NVENC_MAX_SIDE})"
            if max(width, height) > encoders.NVENC_MAX_SIDE
            else "this installation has no NVIDIA encoder"
        )
        return [
            Finding(
                WARNING, "The graphics card cannot be used", f"{reason}; x264 on the processor will encode."
            )
        ]
    if first.hardware:
        return [
            Finding(
                INFO, "Encoding on the graphics card (NVENC)", "x264 takes over if the card cannot start."
            )
        ]
    return [Finding(INFO, "Encoding on the processor (x264)")]


def _disk(sized: Project, options: RenderOptions, frames: int, cache_dir: Path, output: Path | None):
    canvas = sized.canvas
    bits = 0.05 * 2 ** ((23 - options.crf) / 6)
    video = frames * canvas.width_px * canvas.height_px * bits / 8
    where = Path(output).parent if output is not None else cache_dir
    try:
        probe = where if where.exists() else next(p for p in where.parents if p.exists())
        free = shutil.disk_usage(probe).free
    except (OSError, StopIteration):
        return []
    if free < video + DISK_MARGIN:
        severity = PROBLEM if free < video else WARNING
        return [
            Finding(
                severity,
                "Little free disk space",
                f"The video needs about {video / 2**20:.0f} MB and {free / 2**30:.1f} GB is free there.",
            )
        ]
    return []
