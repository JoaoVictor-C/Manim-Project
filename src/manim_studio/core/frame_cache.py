"""Rendered preview frames kept for playback (P3f, ADR 0028). Pure Python, no Qt.

Frames live on the canvas fps grid: frame ``i`` shows time ``i / fps``, as in
the export. ``changed_spans`` says which times an edit can change, by diffing
the two projects; a ``FrameStore`` keeps compressed frames for one view and
refuses frames rendered for another view or before their time last changed.
"""

from __future__ import annotations

import difflib
import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from .schema import Layer, Project

Span = tuple[float, float]  # [start, end) in seconds
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
    them) can change their frames only while they are alive, before or after.
    """
    if old.model_dump(exclude={"layers"}) != new.model_dump(exclude={"layers"}):
        return None
    before = {layer.id: layer for layer in old.layers}
    after = {layer.id: layer for layer in new.layers}
    changed = {i for i in before.keys() | after.keys() if before.get(i) != after.get(i)}
    changed |= _moved(old, new)
    if not changed:
        return []
    closure = _closure(old, changed) | _closure(new, changed)
    spans = _lifetimes(old, closure) + _lifetimes(new, closure)
    return _merge(spans)


def _moved(old: Project, new: Project) -> set[str]:
    """Layers whose place in the stacking order changed: outside the longest common order."""
    a, b = [layer.id for layer in old.layers], [layer.id for layer in new.layers]
    kept = set()
    for block in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        kept |= set(a[block.a : block.a + block.size])
    return (set(a) | set(b)) - kept


def _closure(project: Project, changed: set[str]) -> set[str]:
    """``changed`` plus what draws differently because of them, in ``project``."""
    ids = {layer.id for layer in project.layers}
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
        for layer_id in list(grown & ids):  # an object is evaluated whole (parts, child objects)
            root = project.root_of(layer_id)
            grown |= {root.id} | {d.id for d in project.descendants(root.id)}
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
    """

    budget: int = BUDGET
    total: int = 1  # frames in the timeline: distances wrap around it
    view: int = 0
    generation: int = 0
    frames: dict[int, bytes] = field(default_factory=dict)
    _changed_at: dict[int, int] = field(default_factory=dict)
    _all_changed_at: int = 0
    nbytes: int = 0

    def get(self, index: int) -> bytes | None:
        return self.frames.get(index)

    def __len__(self) -> int:
        return len(self.frames)

    def set_view(self, view: int) -> None:
        """A new framing: no frame is valid any more."""
        self.view = view
        self.invalidate_all()

    def invalidate_all(self) -> None:
        self.generation += 1
        self._all_changed_at = self.generation
        self._changed_at.clear()
        self.frames.clear()
        self.nbytes = 0

    def invalidate(self, indices: Iterable[int]) -> None:
        self.generation += 1
        for index in indices:
            self._changed_at[index] = self.generation
            data = self.frames.pop(index, None)
            if data is not None:
                self.nbytes -= len(data)

    def accept(self, view: int, generation: int, index: int, data: bytes, playhead: int = 0) -> bool:
        """Keep a rendered frame if it is still what that index shows; evict to fit the budget."""
        if view != self.view or generation < max(self._all_changed_at, self._changed_at.get(index, 0)):
            return False
        old = self.frames.get(index)
        if old is not None:
            self.nbytes -= len(old)
        self.frames[index] = data
        self.nbytes += len(data)
        while self.nbytes > self.budget and len(self.frames) > 1:  # farthest ahead of the playhead first
            far = max((i for i in self.frames if i != index), key=lambda i: self._ahead(i, playhead))
            self.nbytes -= len(self.frames.pop(far))
        return index in self.frames

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
            horizon = max(self._ahead(i, start) for i in self.frames)
        out = []
        for offset in range(horizon):
            index = (start + offset) % self.total
            if index not in self.frames:
                out.append(index)
                if len(out) == count:
                    break
        return out
