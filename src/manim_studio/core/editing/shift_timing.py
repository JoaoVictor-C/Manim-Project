"""Shifting timing (U4): move a whole layer, or a selection of clips and keys, by one delta.

One pure edit for everything the timeline can select, so a drag of several items, Edit > Shift
Timing and "move this object five seconds on" are the same step. The rules, from the user's
Pythagoras project (decision session 44):

* a **whole layer** moves its clips, its keys and its explicit Appears at / Disappears at;
* a **clip** moves alone, but the layer's *boundary* clip carries the matching explicit lifetime:
  the first clip an explicit Appears at that equalled its start, the last clip an explicit
  Disappears at that equalled its end (a deliberate offset is left where it is);
* **keys** never carry the lifetime and move on the frame grid;
* the delta is clamped for the **whole** selection so nothing goes below 0 s, and an edit the
  schema refuses (two clips overlapping, two keys on one frame) is refused whole.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from ..model.schema import Layer, Project
from . import edits
from .edits import Edit, EditError

EPS = 1e-9


@dataclass(frozen=True)
class Selection:
    """What to move: whole layers, clips ``(layer, clip)``, keys ``(layer, t, props or None)``,
    and markers, sounds and subtitles by id."""

    layers: tuple[str, ...] = ()
    clips: tuple[tuple[str, str], ...] = ()
    keys: tuple[tuple[str, float, tuple[str, ...] | None], ...] = ()
    markers: tuple[str, ...] = ()
    audio: tuple[str, ...] = ()
    cues: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.layers or self.clips or self.keys or self.markers or self.audio or self.cues)


def _whole_layers(project: Project, selection: Selection) -> list[str]:
    """The layers that move whole: the selected ones, and what is inside a selected group."""
    out = list(selection.layers)
    for layer_id in selection.layers:
        if project.layer(layer_id).is_group:
            out += [x.id for x in project.layers if x.parent_id == layer_id]
    return list(dict.fromkeys(out))


def earliest(project: Project, selection: Selection) -> float:
    """The earliest time anything selected sits at (the limit for moving earlier)."""
    times: list[float] = []
    for layer_id in _whole_layers(project, selection):
        layer = project.layer(layer_id)
        times += [c.start for c in layer.clips]
        times += [k.t for track in layer.tracks.values() for k in track]
        if layer.lifetime.in_ is not None:
            times.append(layer.lifetime.in_)
    for layer_id, clip_id in selection.clips:
        times += [c.start for c in project.layer(layer_id).clips if c.id == clip_id]
    times += [t for _, t, _ in selection.keys]
    times += [m.t for m in project.markers if m.id in selection.markers]
    times += [a.start for a in project.audio if a.id in selection.audio]
    times += [c.start for c in project.subtitles if c.id in selection.cues]
    return min(times, default=0.0)


def latest(project: Project, selection: Selection) -> float:
    """The latest time anything selected reaches (a drag's limit for moving later, U4b)."""
    times: list[float] = []
    for layer_id in _whole_layers(project, selection):
        layer = project.layer(layer_id)
        times += [c.end for c in layer.clips]
        times += [k.t for track in layer.tracks.values() for k in track]
        if layer.lifetime.out is not None:
            times.append(layer.lifetime.out)
    for layer_id, clip_id in selection.clips:
        times += [c.end for c in project.layer(layer_id).clips if c.id == clip_id]
    times += [t for _, t, _ in selection.keys]
    times += [m.t for m in project.markers if m.id in selection.markers]
    times += [a.end for a in project.audio if a.id in selection.audio]
    times += [c.end for c in project.subtitles if c.id in selection.cues]
    return max(times, default=0.0)


def shift_timing(project: Project, selection: Selection, delta: float) -> Edit:
    """Move everything in ``selection`` by ``delta`` seconds (see the module's rules)."""
    if selection.empty:
        raise EditError("nothing is selected to move")
    delta = max(delta, -earliest(project, selection))  # never below 0 s, for all of it
    if abs(delta) < EPS:
        return Edit(project, "timing", frozenset())
    fps = project.canvas.fps

    def on_grid(t: float) -> float:  # keys and markers sit on frames
        return round((t + delta) * fps) / fps

    whole = set(_whole_layers(project, selection))
    clips_of: dict[str, set[str]] = {}
    for layer_id, clip_id in selection.clips:
        clips_of.setdefault(layer_id, set()).add(clip_id)
    keys_of: dict[str, list[tuple[float, tuple[str, ...] | None]]] = {}
    for layer_id, t, props in selection.keys:
        keys_of.setdefault(layer_id, []).append((t, props))

    try:
        layers = []
        for layer in project.layers:
            if layer.id in whole or layer.id in clips_of or layer.id in keys_of:
                layers.append(
                    _shifted_layer(
                        layer,
                        layer.id in whole,
                        clips_of.get(layer.id, set()),
                        keys_of.get(layer.id, []),
                        delta,
                        on_grid,
                        fps,
                    )
                )
            else:
                layers.append(layer)
        extra: dict = {}
        if selection.markers:
            extra["markers"] = [
                m.model_copy(update={"t": on_grid(m.t)}) if m.id in selection.markers else m
                for m in project.markers
            ]
        if selection.audio:
            extra["audio"] = [
                a.model_copy(update={"start": a.start + delta}) if a.id in selection.audio else a
                for a in project.audio
            ]
        if selection.cues:
            extra["subtitles"] = [
                c.model_copy(update={"start": c.start + delta, "end": c.end + delta})
                if c.id in selection.cues
                else c
                for c in project.subtitles
            ]
        new = edits._rebuilt(project, layers=layers, **extra)
    except ValidationError as exc:
        raise EditError(str(exc.errors()[0]["msg"]).removeprefix("Value error, ")) from exc
    kind, layer_ids = edits.classify(project, new)
    return Edit(new, kind, layer_ids)


def _shifted_layer(
    layer: Layer, whole: bool, clip_ids: set[str], key_picks, delta: float, on_grid, fps: int
) -> Layer:
    data = layer.model_dump(by_alias=True)
    lifetime = dict(data["lifetime"])
    if whole:
        for c in data["clips"]:
            c["start"] += delta
        for track in data["tracks"].values():
            for k in track:
                k["t"] = on_grid(k["t"])
        for edge in ("in", "out"):
            if lifetime.get(edge) is not None:
                lifetime[edge] += delta
    else:
        ordered = sorted(layer.clips, key=lambda c: c.start)
        first = ordered[0] if ordered else None
        last = max(ordered, key=lambda c: c.end) if ordered else None
        for c in data["clips"]:
            if c["id"] in clip_ids:
                c["start"] += delta
        life = layer.lifetime
        if (
            first is not None
            and first.id in clip_ids
            and life.in_ is not None
            and abs(life.in_ - first.start) < 0.5 / fps
        ):
            lifetime["in"] = life.in_ + delta
        if (
            last is not None
            and last.id in clip_ids
            and life.out is not None
            and abs(life.out - last.end) < 0.5 / fps
        ):
            lifetime["out"] = life.out + delta
        picked: set[tuple[str, int]] = set()  # found first, moved once: a key moved onto another
        for t, props in key_picks:  # pick's time must not be picked up again (U4b)
            for prop, track in data["tracks"].items():
                if props is not None and prop not in props:
                    continue
                picked.update((prop, i) for i, k in enumerate(track) if abs(k["t"] - t) < 0.5 / fps)
        for prop, i in picked:
            key = data["tracks"][prop][i]
            key["t"] = on_grid(key["t"])
    data["lifetime"] = lifetime
    for track in data["tracks"].values():
        track.sort(key=lambda k: k["t"])
    return Layer.model_validate(data)


def remove_items(project: Project, selection: Selection) -> Edit:
    """Remove the selected clips and keys (the timeline's Delete, U4b) in one edit. Each goes
    through ``edits.remove_clip`` / ``edits.remove_keys``, so their rules and messages hold: a
    property losing its last key keeps that value as its base. A key a wider pick already took
    (every key at that time) is skipped."""
    if not (selection.clips or selection.keys):
        raise EditError("nothing is selected to remove")
    before = project
    for layer_id, clip_id in selection.clips:
        project = edits.remove_clip(project, layer_id, clip_id).project
    half = 0.5 / project.canvas.fps
    for layer_id, t, props in selection.keys:
        tracks = project.layer(layer_id).tracks
        if any(
            abs(k.t - t) < half
            for prop, track in tracks.items()
            if props is None or prop in props
            for k in track
        ):
            project = edits.remove_keys(project, layer_id, t, props=props).project
    kind, layer_ids = edits.classify(before, project)
    return Edit(project, kind, layer_ids)


def timing_warnings(project: Project) -> list[str]:
    """Layers whose explicit lifetime cuts their own animation: it ends before its last clip ends,
    or begins after its first clip starts (the object would be missing for part of it)."""
    out = []
    for layer in project.layers:
        if not layer.clips:
            continue
        first = min(c.start for c in layer.clips)
        last = max(c.end for c in layer.clips)
        life = layer.lifetime
        if life.out is not None and life.out < last - EPS:
            out.append(
                f"{layer.label}: its lifetime ends before its animation "
                f"(Disappears at {life.out:g} s, animation until {last:g} s)"
            )
        if life.in_ is not None and life.in_ > first + EPS:
            out.append(
                f"{layer.label}: its lifetime starts after its animation "
                f"(Appears at {life.in_:g} s, animation from {first:g} s)"
            )
    return out
