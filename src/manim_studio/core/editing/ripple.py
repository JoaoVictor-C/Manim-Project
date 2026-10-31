"""Linked ripple editing (ADR 0071): open or close time at a point and let what follows move with it.

A ripple moves everything that *starts* at or after a time, by one amount, so the rest of the scene keeps its
timing relative to what moved. What counts as "everything" is chosen by ``Scope``: clips, keys, sounds,
subtitles and markers, each on or off, so a gap can be opened in the picture and the narration left where it
is, or the reverse. Items that start before the point stay; one that spans it keeps its start and its length
(a gap opened inside a clip lands after it). The moving is ``shift_timing``'s, with its rules: keys on frames,
a layer's explicit Appears at / Disappears at carried with its boundary clip, nothing below 0 s, and an edit
the schema refuses (two clips of one layer overlapping once a gap is closed) refused whole, with its reason.

``affected`` lists what a ripple would move, for the preview; ``beats`` names the spans between markers, and
``retime_beat`` gives one a new length by rippling at its end. No Qt, no Manim.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.scene_length import grow_to_fit
from ..model.schema import Project
from . import edits, shift_timing
from .edits import Edit, EditError

EPS = 1e-9


@dataclass(frozen=True)
class Scope:
    """What moves together."""

    clips: bool = True
    keys: bool = True
    audio: bool = True
    subtitles: bool = True
    markers: bool = True


EVERYTHING = Scope()


@dataclass(frozen=True)
class Affected:
    """What a ripple at one time would move."""

    selection: shift_timing.Selection
    layers: tuple[str, ...]  # layers with a clip or key that moves

    @property
    def counts(self) -> dict[str, int]:
        s = self.selection
        return {
            "clips": len(s.clips),
            "keys": len(s.keys),
            "sounds": len(s.audio),
            "subtitles": len(s.cues),
            "markers": len(s.markers),
        }

    @property
    def empty(self) -> bool:
        return self.selection.empty

    def summary(self) -> str:
        parts = [f"{n} {name}" for name, n in self.counts.items() if n]
        if not parts:
            return "Nothing starts at or after that time."
        where = f" on {len(self.layers)} layer(s)" if self.layers else ""
        return "Moves " + ", ".join(parts) + where + "."


@dataclass(frozen=True)
class Beat:
    """The span between two markers (or the ends of the scene)."""

    name: str
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def affected(project: Project, at: float, scope: Scope = EVERYTHING) -> Affected:
    """Everything in ``scope`` that starts at or after ``at``."""
    clips: list[tuple[str, str]] = []
    keys: list[tuple[str, float, tuple[str, ...] | None]] = []
    layers: list[str] = []
    for layer in project.layers:
        moved = False
        if scope.clips:
            for clip in layer.clips:
                if clip.start >= at - EPS:
                    clips.append((layer.id, clip.id))
                    moved = True
        if scope.keys:
            times = sorted({k.t for track in layer.tracks.values() for k in track if k.t >= at - EPS})
            keys += [(layer.id, t, None) for t in times]
            moved = moved or bool(times)
        if moved:
            layers.append(layer.id)
    selection = shift_timing.Selection(
        clips=tuple(clips),
        keys=tuple(keys),
        markers=tuple(m.id for m in project.markers if scope.markers and m.t >= at - EPS),
        audio=tuple(a.id for a in project.audio if scope.audio and a.start >= at - EPS),
        cues=tuple(c.id for c in project.subtitles if scope.subtitles and c.start >= at - EPS),
    )
    return Affected(selection, tuple(layers))


def ripple(project: Project, at: float, delta: float, scope: Scope = EVERYTHING) -> Edit:
    """Move everything in ``scope`` that starts at or after ``at`` by ``delta`` seconds (negative closes).

    One edit: the scene grows to fit what moved later, and undo puts it all back."""
    if at < 0:
        raise EditError("the point must not be before 0 s")
    found = affected(project, at, scope)
    if found.empty:
        raise EditError("nothing starts at or after that time")
    if abs(delta) < EPS:
        return Edit(project, "timing", frozenset())
    edit = shift_timing.shift_timing(project, found.selection, delta)
    grown = grow_to_fit(edit.project)
    return Edit(grown, *edits.classify(project, grown)) if grown != edit.project else edit


def beats(project: Project) -> list[Beat]:
    """The spans between markers, in time order: the lead-in before the first, those between, and the last
    to the end of the scene. A marker's name names the beat it starts."""
    marks = sorted(project.markers, key=lambda m: m.t)
    edges = [(0.0, "Start")] + [(m.t, m.name or f"Marker {i + 1}") for i, m in enumerate(marks)]
    edges = [(t, name) for k, (t, name) in enumerate(edges) if k == 0 or t > edges[k - 1][0] + EPS]
    end = project.canvas.duration
    out = []
    for k, (t, name) in enumerate(edges):
        stop = edges[k + 1][0] if k + 1 < len(edges) else end
        if stop > t + EPS:
            out.append(Beat(name, t, stop))
    return out


def retime_beat(project: Project, beat: Beat, new_length: float, scope: Scope = EVERYTHING) -> Edit:
    """Give ``beat`` another length by rippling at its end: what follows moves, what is inside stays."""
    if new_length <= 0:
        raise EditError("a beat needs a length above 0 s")
    inside_end = max(
        [
            c.end
            for layer in project.layers
            for c in layer.clips
            if beat.start - EPS <= c.start < beat.end - EPS
        ]
        if scope.clips
        else [],
        default=beat.start,
    )
    if new_length < inside_end - beat.start - EPS:
        raise EditError(
            f"{beat.name!r} cannot be shorter than {inside_end - beat.start:.2f} s: a clip in it ends there"
        )
    return ripple(project, beat.end, new_length - beat.length, scope)
