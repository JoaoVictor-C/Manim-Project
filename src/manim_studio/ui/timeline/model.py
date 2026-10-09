"""Timeline geometry and drag rules — pure Python, no Qt (S1 plan, "Interaction rules").

Everything the timeline needs to turn mouse positions into clip times lives here
so it can be tested headless:

* ``TimeScale`` — time <-> x, zooming about a point;
* ``quantize`` / ``snap`` — frame grid, then the nearest candidate within a pixel radius;
* ``move_bounds`` / ``trim_bounds`` — where a clip may go on its lane;
* ``drag_move`` / ``drag_trim`` — the full rule: propose, snap, clamp.

Clamping (never rejecting) keeps every intermediate drag state valid, so the
document never sees an overlap (ADR 0014).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from ...core.schema import Clip, Layer, Project

SNAP_RADIUS_PX = 8.0
MIN_PX_PER_SECOND = 10.0
MAX_PX_PER_SECOND = 4000.0

Edge = Literal["start", "end"]


@dataclass(frozen=True)
class TimeScale:
    """Maps seconds to scene x (pixels). ``offset`` is the time at x = 0."""

    px_per_second: float = 100.0
    offset: float = 0.0

    def x(self, t: float) -> float:
        return (t - self.offset) * self.px_per_second

    def t(self, x: float) -> float:
        return x / self.px_per_second + self.offset

    def zoomed(self, factor: float, anchor_x: float) -> TimeScale:
        """Zoom by ``factor`` keeping the time under ``anchor_x`` where it is."""
        anchor_t = self.t(anchor_x)
        pps = min(max(self.px_per_second * factor, MIN_PX_PER_SECOND), MAX_PX_PER_SECOND)
        return TimeScale(pps, anchor_t - anchor_x / pps)

    def seconds(self, px: float) -> float:
        return px / self.px_per_second


def quantize(t: float, fps: int) -> float:
    """Nearest frame boundary."""
    return round(t * fps) / fps


def snap(
    t: float,
    candidates: Iterable[float],
    scale: TimeScale,
    fps: int,
    enabled: bool = True,
    radius_px: float = SNAP_RADIUS_PX,
) -> float:
    """Frame-quantize ``t``, then snap to the nearest candidate within ``radius_px``."""
    best = quantize(t, fps)
    if not enabled:
        return best
    radius = scale.seconds(radius_px)
    nearest = min(candidates, key=lambda c: abs(c - t), default=None)
    if nearest is not None and abs(nearest - t) <= radius:
        return nearest
    return best


def snap_candidates(project: Project, playhead: float, exclude: tuple[str, str] | None = None) -> list[float]:
    """0, the canvas end, the playhead, and every clip edge except the dragged clip's."""
    points = {0.0, project.canvas.duration, playhead}
    for layer in project.layers:
        for clip in layer.clips:
            if exclude != (layer.id, clip.id):
                points.update((clip.start, clip.end))
    return sorted(points)


def _neighbours(layer: Layer, clip_id: str) -> tuple[Clip | None, Clip, Clip | None]:
    for i, clip in enumerate(layer.clips):
        if clip.id == clip_id:
            prev = layer.clips[i - 1] if i > 0 else None
            nxt = layer.clips[i + 1] if i + 1 < len(layer.clips) else None
            return prev, clip, nxt
    raise KeyError(clip_id)


def move_bounds(layer: Layer, clip_id: str, duration: float) -> tuple[float, float]:
    """Allowed range for the clip's start when moving it (its length is kept)."""
    prev, clip, nxt = _neighbours(layer, clip_id)
    lo = max(0.0, prev.end if prev else 0.0)
    hi = min(duration, nxt.start if nxt else duration) - clip.duration
    return lo, max(lo, hi)


def trim_bounds(layer: Layer, clip_id: str, edge: Edge, duration: float, fps: int) -> tuple[float, float]:
    """Allowed range for one edge; the clip never gets shorter than one frame."""
    prev, clip, nxt = _neighbours(layer, clip_id)
    frame = 1.0 / fps
    if edge == "start":
        return max(0.0, prev.end if prev else 0.0), clip.end - frame
    return clip.start + frame, min(duration, nxt.start if nxt else duration)


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(max(value, lo), hi)


def _nearest_candidate(t: float, candidates: list[float], scale: TimeScale) -> float | None:
    """The closest candidate within the snap radius, or None."""
    nearest = min(candidates, key=lambda c: abs(c - t), default=None)
    if nearest is not None and abs(nearest - t) <= scale.seconds(SNAP_RADIUS_PX):
        return nearest
    return None


def drag_move(
    layer: Layer,
    clip_id: str,
    proposed_start: float,
    *,
    duration: float,
    fps: int,
    scale: TimeScale,
    candidates: Iterable[float] = (),
    snapping: bool = True,
) -> float:
    """New start for a moved clip.

    Either edge may snap; if both can, the one needing the smaller shift wins.
    Otherwise the start is frame-quantized. The result is clamped to the lane.
    """
    clip = _neighbours(layer, clip_id)[1]
    start = quantize(proposed_start, fps)
    if snapping:
        candidates = list(candidates)
        options = []
        hit = _nearest_candidate(proposed_start, candidates, scale)
        if hit is not None:
            options.append(hit)
        hit = _nearest_candidate(proposed_start + clip.duration, candidates, scale)
        if hit is not None:
            options.append(hit - clip.duration)
        if options:
            start = min(options, key=lambda s: abs(s - proposed_start))
    return _clamp(start, *move_bounds(layer, clip_id, duration))


def drag_trim(
    layer: Layer,
    clip_id: str,
    edge: Edge,
    proposed: float,
    *,
    duration: float,
    fps: int,
    scale: TimeScale,
    candidates: Iterable[float] = (),
    snapping: bool = True,
) -> tuple[float, float]:
    """New (start, end) after dragging one edge: snap the edge, then clamp."""
    clip = _neighbours(layer, clip_id)[1]
    value = _clamp(
        snap(proposed, candidates, scale, fps, snapping), *trim_bounds(layer, clip_id, edge, duration, fps)
    )
    return (value, clip.end) if edge == "start" else (clip.start, value)


def place_new_clip(
    layer: Layer, t: float, *, duration: float, fps: int, length: float = 1.0
) -> tuple[float, float] | None:
    """Where a clip added at time ``t`` goes: ``(start, duration)``, or None if it cannot.

    The clip starts at ``t`` on the frame grid and is ``length`` long, shortened
    to fit the free gap around ``t``; near the end of a gap it slides back so it
    keeps at least one frame. Nothing can go inside another clip or after a
    morph (ADR 0005).
    """
    frame = 1.0 / fps
    lo, hi = 0.0, duration
    for clip in layer.clips:
        if clip.start - 1e-9 <= t < clip.end - 1e-9:
            return None  # on a clip
        if clip.end <= t + 1e-9:
            if clip.info.category == "morph":
                return None  # the layer has handed off
            lo = max(lo, clip.end)
        elif clip.start > t:
            hi = min(hi, clip.start)
    if hi - lo < frame - 1e-9:
        return None
    start = _clamp(quantize(t, fps), lo, hi - frame)
    return start, min(length, hi - start)
