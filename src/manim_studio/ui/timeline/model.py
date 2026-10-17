"""Timeline geometry and drag rules — pure Python, no Qt (S1 plan, "Interaction rules").

Everything the timeline needs to turn mouse positions into clip times lives here
so it can be tested headless:

* ``TimeScale`` — time <-> x, zooming about a point;
* ``quantize`` / ``snap`` — frame grid, then the nearest candidate within a pixel radius;
* ``snap_candidates`` — the points every drag snaps to (ADR 0037), ``drag_marker`` for markers;
* ``move_bounds`` / ``trim_bounds`` — where a clip may go on its lane (and around
  its obstacles: clips of the layer's ancestors and parts, ADR 0012);
* ``drag_move`` / ``drag_trim`` — the full rule: propose, snap, clamp.

Clamping (never rejecting) keeps every intermediate drag state valid, so the
document never sees an overlap (ADR 0014).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from ...core.layer_index import LayerIndex
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


FIT_MARGIN_PX = 24.0  # room after the end of the scene when the timeline fits it


def fit_scale(duration: float, width: float) -> TimeScale:
    """The scale that shows the whole scene, ``duration`` seconds, in ``width`` pixels (P6d.4)."""
    pps = (width - FIT_MARGIN_PX) / max(duration, 0.1)
    return TimeScale(px_per_second=min(max(pps, MIN_PX_PER_SECOND), MAX_PX_PER_SECOND))


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


# What is being dragged, left out of the snap points (ADR 0037): ("clip", layer, clip),
# ("key", layer, t), ("audio", id), ("cue", id) or ("marker", id).
SnapItem = tuple


def snap_candidates(project: Project, playhead: float, exclude: Iterable[SnapItem] = ()) -> list[float]:
    """The points drags snap to (ADR 0037): 0, the end, the playhead, markers, clip edges, key times,
    and sound and subtitle edges, except those of the dragged items in ``exclude``."""
    skip = set(exclude)
    fps = project.canvas.fps
    keys = {(item[1], round(item[2] * fps)) for item in skip if item[0] == "key"}
    points = {0.0, project.canvas.duration, playhead}
    for layer in project.layers:
        for clip in layer.clips:
            if ("clip", layer.id, clip.id) not in skip:
                points.update((clip.start, clip.end))
        for track in layer.tracks.values():
            points.update(key.t for key in track if (layer.id, round(key.t * fps)) not in keys)
    points.update(t for c in project.audio if ("audio", c.id) not in skip for t in (c.start, c.end))
    points.update(t for c in project.subtitles if ("cue", c.id) not in skip for t in (c.start, c.end))
    points.update(m.t for m in project.markers if ("marker", m.id) not in skip)
    return sorted(points)


def snapped(t: float, candidates: Iterable[float]) -> bool:
    """Whether a dragged edge rests on one of the points (the timeline draws a guide there)."""
    return any(abs(t - c) < 1e-9 for c in candidates)


def drag_marker(
    project: Project,
    marker_id: str,
    proposed: float,
    current: float,
    *,
    scale: TimeScale,
    candidates: Iterable[float] = (),
    snapping: bool = True,
) -> float:
    """New time for a dragged marker (ADR 0037): snapped, within the scene, and ``current`` when
    another marker holds that frame (it never lands on one)."""
    canvas = project.canvas
    t = _clamp(snap(proposed, candidates, scale, canvas.fps, snapping), 0.0, canvas.duration)
    taken = {round(m.t * canvas.fps) for m in project.markers if m.id != marker_id}
    return current if round(t * canvas.fps) in taken else t


def obstacles(project: Project, layer_id: str, index: LayerIndex | None = None) -> list[Clip]:
    """Clips a clip of ``layer_id`` may not overlap besides its own lane (ADR 0012).

    Those of the layer's ancestors and of its parts; sibling parts may overlap. Pass the project's
    ``LayerIndex`` when asking for many layers (B66).
    """
    tree = index or project
    related = [*tree.ancestors(layer_id), *tree.descendants(layer_id)]
    return [clip for layer in related for clip in layer.clips]


def _neighbours(
    layer: Layer, clip_id: str, obstacles: Iterable[Clip] = ()
) -> tuple[Clip | None, Clip, Clip | None]:
    """The clip and what bounds it: the latest clip ending before it, the earliest starting after."""
    clip = next((c for c in layer.clips if c.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    others = [c for c in layer.clips if c.id != clip_id] + list(obstacles)
    before = [c for c in others if c.end <= clip.start + 1e-9]
    after = [c for c in others if c.start >= clip.end - 1e-9]
    prev = max(before, key=lambda c: c.end, default=None)
    nxt = min(after, key=lambda c: c.start, default=None)
    return prev, clip, nxt


def move_bounds(
    layer: Layer, clip_id: str, duration: float, obstacles: Iterable[Clip] = ()
) -> tuple[float, float]:
    """Allowed range for the clip's start when moving it (its length is kept)."""
    prev, clip, nxt = _neighbours(layer, clip_id, obstacles)
    lo = max(0.0, prev.end if prev else 0.0)
    hi = min(duration, nxt.start if nxt else duration) - clip.duration
    return lo, max(lo, hi)


def trim_bounds(
    layer: Layer, clip_id: str, edge: Edge, duration: float, fps: int, obstacles: Iterable[Clip] = ()
) -> tuple[float, float]:
    """Allowed range for one edge; the clip never gets shorter than one frame."""
    prev, clip, nxt = _neighbours(layer, clip_id, obstacles)
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
    obstacles: Iterable[Clip] = (),
) -> float:
    """New start for a moved clip.

    Either edge may snap; if both can, the one needing the smaller shift wins.
    Otherwise the start is frame-quantized. The result is clamped to the lane.
    """
    obstacles = list(obstacles)
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
    return _clamp(start, *move_bounds(layer, clip_id, duration, obstacles))


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
    obstacles: Iterable[Clip] = (),
) -> tuple[float, float]:
    """New (start, end) after dragging one edge: snap the edge, then clamp."""
    clip = _neighbours(layer, clip_id)[1]
    value = _clamp(
        snap(proposed, candidates, scale, fps, snapping),
        *trim_bounds(layer, clip_id, edge, duration, fps, obstacles),
    )
    return (value, clip.end) if edge == "start" else (clip.start, value)


def rows(project: Project, index: LayerIndex | None = None) -> list[Layer]:
    """Timeline rows: objects front-most first, each followed by its parts (ADR 0012)."""
    return (index or LayerIndex(project)).rows()


def depth(project: Project, layer: Layer, index: LayerIndex | None = None) -> int:
    """0 for an object, 1 for its parts, 2 for parts of parts..."""
    if layer.parent_id is None:
        return 0
    return index.depth(layer.id) if index is not None else len(project.ancestors(layer.id))


def place_new_clip(
    layer: Layer,
    t: float,
    *,
    duration: float,
    fps: int,
    length: float = 1.0,
    obstacles: Iterable[Clip] = (),
) -> tuple[float, float] | None:
    """Where a clip added at time ``t`` goes: ``(start, duration)``, or None if it cannot.

    The clip starts at ``t`` on the frame grid and is ``length`` long, shortened
    to fit the free gap around ``t``; near the end of a gap it slides back so it
    keeps at least one frame. Nothing can go inside another clip or after a
    morph (ADR 0005).
    """
    frame = 1.0 / fps
    lo, hi = 0.0, duration
    own = {id(clip) for clip in layer.clips}
    for clip in [*layer.clips, *obstacles]:
        if clip.start - 1e-9 <= t < clip.end - 1e-9:
            return None  # on a clip
        if clip.end <= t + 1e-9:
            if clip.info.category == "morph" and id(clip) in own:
                return None  # the layer has handed off
            lo = max(lo, clip.end)
        elif clip.start > t:
            hi = min(hi, clip.start)
    if hi - lo < frame - 1e-9:
        return None
    start = _clamp(quantize(t, fps), lo, hi - frame)
    return start, min(length, hi - start)


# -- keyframes (P2b) ------------------------------------------------------------------


def key_times(layer: Layer, fps: int) -> list[tuple[float, tuple[str, ...]]]:
    """Key times merged across properties (within half a frame), with the properties keyed at each."""
    keys = sorted((key.t, prop) for prop, track in layer.tracks.items() for key in track)
    merged: list[tuple[float, list[str]]] = []
    for t, prop in keys:
        if merged and t - merged[-1][0] < 0.5 / fps:
            merged[-1][1].append(prop)
        else:
            merged.append((t, [prop]))
    return [(t, tuple(sorted(set(props)))) for t, props in merged]


def key_bounds(layer: Layer, t: float, duration: float, fps: int) -> tuple[float, float]:
    """Where the keys at ``t`` may move: more than a frame from each moved property's neighbours."""
    frame = 1.0 / fps
    lo, hi = 0.0, duration
    for track in layer.tracks.values():
        times = [key.t for key in track]
        if not any(abs(k - t) < 0.5 * frame for k in times):
            continue
        before = [k for k in times if k < t - 0.5 * frame]
        after = [k for k in times if k > t + 0.5 * frame]
        if before:
            lo = max(lo, before[-1] + frame)
        if after:
            hi = min(hi, after[0] - frame)
    return lo, max(lo, hi)


def drag_keys(
    layer: Layer,
    t: float,
    proposed: float,
    *,
    duration: float,
    fps: int,
    scale: TimeScale,
    candidates: Iterable[float] = (),
    snapping: bool = True,
) -> float:
    """New time for the keys at ``t`` dragged to ``proposed``: snap, then clamp."""
    return _clamp(snap(proposed, candidates, scale, fps, snapping), *key_bounds(layer, t, duration, fps))
