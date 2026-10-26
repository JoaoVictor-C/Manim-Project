"""Rendered preview frames kept for playback (P3f, ADR 0028). Pure Python, no Qt.

Frames live on the canvas fps grid: frame ``i`` shows time ``i / fps``, as in
the export. ``changed_spans`` says which times an edit can change, by diffing
the two projects; a ``FrameStore`` keeps compressed frames for one view and
refuses frames rendered for another view or before their time last changed.
"""

from __future__ import annotations

import difflib
import math
from bisect import bisect_left, insort
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..code import helpers
from ..model.schema import RUNS_CODE, Layer, Project
from ..sound import subtitles

Span = tuple[float, float]  # [start, end) in seconds
# Parts of a project whose changes are not "every frame": layers, sounds (ADR 0034), subtitles (ADR 0035),
# markers (ADR 0037: no frame at all). Helpers (ADR 0058) change the frames of the code layers and
# Python objects only, which ``changed_layers`` adds.
_NOT_CANVAS = {"layers", "audio", "subtitles", "subtitle_style", "markers", "morph_matching", "helpers"}
# The scene's length draws nothing: a frame is the same in a longer scene (P7.1).
_NOT_DRAWN = {"canvas": {"duration", "grow_with_content"}}
BUDGET = 512 * 2**20  # bytes of compressed frames (B41: 4500-9700 frames)


def frame_index(t: float, fps: int) -> int:
    """The grid frame showing at time ``t`` (the last one at or before it)."""
    return max(0, math.floor(t * fps + 1e-6))


def frame_time(index: int, fps: int) -> float:
    return index / fps


def frame_count(project: Project) -> int:
    return round(project.canvas.duration * project.canvas.fps)


def on_grid(t: float, fps: int) -> bool:
    return abs(t * fps - round(t * fps)) < 1e-6


# -- what an edit changes -----------------------------------------------------------


def changed_spans(old: Project, new: Project) -> list[Span] | None:
    """The times whose frames can differ between ``old`` and ``new``; None = all of them.

    Anything but the layers (the canvas) changes every frame. Otherwise the
    changed layers - added, removed, edited, or moved in the stacking order - and
    what depends on them (morph partners, their whole object, layers moving along
    them, traces of them) can change their frames only while they are alive, before or after.
    """
    closure = changed_layers(old, new)
    if closure is None:
        return None
    spans = _lifetimes(old, closure) + _lifetimes(new, closure) if closure else []
    return _merge(spans + subtitles.changed_spans(old, new))  # subtitles are drawn too (ADR 0035)


def _drawn(project: Project) -> dict:
    """What of the project draws every frame."""
    return project.model_dump(exclude={**dict.fromkeys(_NOT_CANVAS, True), **_NOT_DRAWN})


def changed_layers(old: Project, new: Project) -> set[str] | None:
    """The layers whose frames can differ (see ``changed_spans``); None when the canvas changed."""
    if _drawn(old) != _drawn(new):
        return None
    before = {layer.id: layer for layer in old.layers}
    after = {layer.id: layer for layer in new.layers}
    changed = {i for i in before.keys() | after.keys() if before.get(i) != after.get(i)}
    changed |= _moved(old, new)
    if helpers.code_changed(old, new):  # every layer running code may import a helper (ADR 0058)
        changed |= {
            x.id for x in [*old.layers, *new.layers] if x.spec is not None and x.spec.type in RUNS_CODE
        }
    if not changed:
        return set()
    return _closure(old, changed) | _closure(new, changed)


def layer_spans(project: Project, layer_ids: Iterable[str]) -> list[Span]:
    """The times where these layers, or what depends on them, are drawn (a code render
    finished, a media file was read again: the project itself did not change)."""
    return _merge(_lifetimes(project, _closure(project, set(layer_ids))))


def _moved(old: Project, new: Project) -> set[str]:
    """Layers whose place in the stacking order changed: outside the longest common order."""
    a, b = [layer.id for layer in old.layers], [layer.id for layer in new.layers]
    kept = set()
    for block in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        kept |= set(a[block.a : block.a + block.size])
    return (set(a) | set(b)) - kept


def _closure(project: Project, changed: set[str]) -> set[str]:
    """``changed`` plus what draws differently because of them, in ``project``."""
    by_id = {layer.id: layer for layer in project.layers}  # lookups once, not per layer (B53)
    children: dict[str, list[str]] = {}
    for layer in project.layers:
        if layer.parent_id is not None:
            children.setdefault(layer.parent_id, []).append(layer.id)
    ids = set(by_id)
    objects: dict[str, set[str]] = {}  # root id -> the root and everything under it

    def whole_object(layer_id: str) -> set[str]:
        root = by_id[layer_id]
        while root.parent_id is not None and not by_id[root.parent_id].is_group:
            root = by_id[root.parent_id]  # an object in a group is an object of its own (ADR 0050)
        if root.id not in objects:
            members, pending = {root.id}, [root.id]
            while pending:
                for child in children.get(pending.pop(), ()):
                    members.add(child)
                    pending.append(child)
            objects[root.id] = members
        return objects[root.id]

    out = changed & ids
    while True:
        grown = set(out)
        for layer in project.layers:
            for clip in layer.clips:
                if clip.to_layer and (layer.id in out or clip.to_layer in out):  # a morph reads both ends
                    grown |= {layer.id, clip.to_layer}
                path = clip.params.get("path") if clip.info.category == "motion" else None
                if path in out:  # it moves along a changed shape (ADR 0025)
                    grown.add(layer.id)
        grown |= project.traces_of(grown)  # a trace draws where a changed layer was (ADR 0033)
        grown |= project.connectors_of(grown)  # a connector ends at a changed layer (ADR 0036)
        for layer_id in list(grown & ids):  # an object is evaluated whole (parts, child objects)
            grown |= whole_object(layer_id)
        grown &= ids
        if grown == out:
            return out
        out = grown


def _lifetimes(project: Project, layer_ids: Iterable[str]) -> list[Span]:
    from .evaluator import Evaluator  # cheap: no object is built until a frame is asked for

    evaluator = Evaluator(project)
    layers: dict[str, Layer] = {layer.id: layer for layer in project.layers}
    return [evaluator.lifetime(layers[i]) for i in layer_ids if i in layers]


def _merge(spans: list[Span]) -> list[Span]:
    out: list[Span] = []
    for start, end in sorted(s for s in spans if s[1] > s[0]):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def span_indices(spans: Iterable[Span], fps: int, total: int) -> set[int]:
    """Grid frames inside the spans (frame i is inside [s, e) when s <= i / fps < e)."""
    out: set[int] = set()
    for start, end in spans:
        first = max(0, math.ceil(start * fps - 1e-6))
        last = total if math.isinf(end) else min(total, math.ceil(end * fps - 1e-6))
        out.update(range(first, last))
    return out


# -- the store ------------------------------------------------------------------------


@dataclass
class FrameStore:
    """Compressed frames by grid index, for one view (ADR 0028).

    ``generation`` counts invalidations; a frame rendered from the project as it
    was at generation g is accepted only for a frame whose time has not changed
    since (its last invalidation <= g) and only for the current view.

    The kept indices are also held sorted (``_order``), so a full store finds the frame farthest
    ahead of the playhead - the one just before it, circularly - and skips runs of kept frames in
    ``missing`` by bisection, both O(log n) instead of a scan of every kept frame (B66: 7.4 and
    6.2 ms per call at 15 000 frames).
    """

    budget: int = BUDGET
    total: int = 1  # frames in the timeline: distances wrap around it
    view: int = 0
    generation: int = 0
    frames: dict[int, bytes] = field(default_factory=dict)
    _changed_at: dict[int, int] = field(default_factory=dict)
    _all_changed_at: int = 0
    nbytes: int = 0
    _order: list[int] = field(default_factory=list)  # the keys of ``frames``, sorted

    def get(self, index: int) -> bytes | None:
        return self.frames.get(index)

    def __len__(self) -> int:
        return len(self.frames)

    def set_view(self, view: int) -> None:
        """A new framing: no kept frame is valid. Frames carry their view, so the generation
        stays (frames rendered from the current project for the new view are fine)."""
        self.view = view
        self._clear()

    def _clear(self) -> None:
        self.frames.clear()
        self._order.clear()
        self.nbytes = 0

    def invalidate_all(self) -> None:
        self.generation += 1
        self._all_changed_at = self.generation
        self._changed_at.clear()
        self._clear()

    def invalidate(self, indices: Iterable[int]) -> None:
        self.generation += 1
        for index in indices:
            self._changed_at[index] = self.generation
            self._drop(index)

    def _drop(self, index: int) -> bool:
        data = self.frames.pop(index, None)
        if data is None:
            return False
        self.nbytes -= len(data)
        position = bisect_left(self._order, index)
        del self._order[position]
        return True

    def accept(self, view: int, generation: int, index: int, data: bytes, playhead: int = 0) -> bool:
        """Keep a rendered frame if it is still what that index shows; evict to fit the budget."""
        if view != self.view or generation < max(self._all_changed_at, self._changed_at.get(index, 0)):
            return False
        old = self.frames.get(index)
        if old is not None:
            self.nbytes -= len(old)
        else:
            insort(self._order, index)
        self.frames[index] = data
        self.nbytes += len(data)
        while self.nbytes > self.budget and len(self.frames) > 1:  # farthest ahead of the playhead first
            self._drop(self._farthest(playhead, skip=index))
        return index in self.frames

    def _plain(self, playhead: int) -> bool:
        """Whether every distance is a plain modulo of ``total`` (always, but for a store whose
        total was set below a kept index: those keep the exhaustive rules)."""
        return playhead < self.total and self._order[-1] < self.total

    def _farthest(self, playhead: int, skip: int) -> int:
        """The kept frame farthest ahead of ``playhead`` other than ``skip`` (wrapping: playback
        loops back to 0). Farthest ahead = the nearest kept index behind the playhead."""
        if not self._plain(playhead):
            return max((i for i in self.frames if i != skip), key=lambda i: self._ahead(i, playhead))
        order = self._order
        position = bisect_left(order, playhead) - 1  # walk back from the playhead, circularly
        for step in range(2):  # at most one kept index is skipped
            candidate = order[(position - step) % len(order)]
            if candidate != skip:
                return candidate
        raise AssertionError("two or more frames are kept")

    def _ahead(self, index: int, playhead: int) -> int:
        """How far ``index`` plays after ``playhead`` (wrapping: playback loops back to 0)."""
        return (index - playhead) % max(self.total, index + 1, playhead + 1)

    def missing(self, start: int, count: int) -> list[int]:
        """Up to ``count`` frames not kept, from ``start`` forward, then wrapping to 0.

        A full store asks only for frames nearer than the farthest it keeps (they
        would evict it); asking for farther ones would evict what was just made.
        """
        horizon = self.total
        if self.nbytes >= self.budget * 0.95 and self.frames:
            if self._plain(start):
                horizon = self._ahead(self._farthest(start, skip=-1), start)
            else:
                horizon = max(self._ahead(i, start) for i in self.frames)
        if self.frames and not self._plain(start):
            return self._missing_scan(start, count, horizon)
        out: list[int] = []
        first = start % self.total
        # offsets 0..horizon-1 from ``first``: the stretch up to the end, then the one from 0
        stretch = min(horizon, self.total - first)
        self._gaps(first, first + stretch, count, out)
        if len(out) < count and horizon > stretch:
            self._gaps(0, horizon - stretch, count, out)
        return out

    def _gaps(self, lo: int, hi: int, count: int, out: list[int]) -> None:
        """Append the indices in [lo, hi) not kept, until ``out`` has ``count``; kept runs are
        jumped over by bisection."""
        order = self._order
        position = bisect_left(order, lo)
        index = lo
        while index < hi and len(out) < count:
            if position < len(order) and order[position] == index:
                run = order[position] - position  # constant along a run of consecutive indices
                low, high = position, len(order)  # the last position still in the run
                while low + 1 < high:
                    middle = (low + high) // 2
                    if order[middle] - middle == run:
                        low = middle
                    else:
                        high = middle
                index = order[low] + 1
                position = low + 1
            else:
                out.append(index)
                index += 1

    def _missing_scan(self, start: int, count: int, horizon: int) -> list[int]:
        out = []
        for offset in range(horizon):
            index = (start + offset) % self.total
            if index not in self.frames:
                out.append(index)
                if len(out) == count:
                    break
        return out
