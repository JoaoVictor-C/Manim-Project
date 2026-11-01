"""Compound sequences (ADR 0079): named sets of clips and keys that move, retime and copy together.

A ``Sequence`` (``Project.sequences``) is an annotation over clips and keys the layers already own, from one
layer or several: it is never drawn, and the frames are the same with or without it. What it adds is a handle:
the timeline draws one band over its members, and the edits here act on all of them at once.

Members are clips by ``(layer, clip id)`` and keys by ``(layer, track, t)``. They stay valid by themselves:
the project's validator drops members that are gone (and a sequence left with none) inside the edit that
removed them, so undo is one step; ``shift_timing`` and ``retime_keys`` carry the members of the keys they
move. A clip or key is in one sequence at most.

The API, for the timeline and for what builds on it (editable animation recipes):

* ``Members`` - what to put in a sequence; ``members_from_selection`` turns the timeline's picks into it.
* ``span(project, sequence)`` - min start .. max end of its members (pure).
* ``selection_of(project, sequence)`` - its members as a ``shift_timing.Selection``.
* ``sequence_of_clip`` / ``sequence_of_key`` - which sequence holds a member, if any.
* edits (each one ``Edit``, one undo step): ``make_sequence``, ``dissolve_sequence``, ``rename_sequence``,
  ``set_sequence_colour``,
  ``move_sequence``, ``retime_sequence``, ``duplicate_sequence``; per layer (ADR 0080, recipes):
  ``restagger_sequence`` and ``reparameterise_sequence`` (``member_layers``, ``stagger_of``, ``fit_factor``).

No Qt, no Manim.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import ValidationError

from ..model.scene_length import grow_to_fit
from ..model.schema import Layer, Project, Sequence, SequenceClip, SequenceKey, is_colour
from . import edits, shift_timing
from .edits import Edit, EditError

EPS = 1e-9


@dataclass(frozen=True)
class Members:
    """Clips ``(layer, clip id)`` and keys ``(layer, track, t)`` to put in a sequence."""

    clips: tuple[tuple[str, str], ...] = ()
    keys: tuple[tuple[str, str, float], ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.clips or self.keys)


def members_from_selection(project: Project, selection: shift_timing.Selection) -> Members:
    """The clips and keys of a timing selection (the timeline's picks): a key pick of every property
    (``props`` None) is each property's key at that time. Whole layers, sounds, subtitles and markers are
    not members of a sequence and are left out."""
    half = 0.5 / project.canvas.fps
    keys: list[tuple[str, str, float]] = []
    for layer_id, t, props in selection.keys:
        layer = edits._layer(project, layer_id)
        for track, track_keys in layer.tracks.items():
            if props is not None and track not in props:
                continue
            keys += [(layer_id, track, k.t) for k in track_keys if abs(k.t - t) < half]
    return Members(tuple(dict.fromkeys(selection.clips)), tuple(dict.fromkeys(keys)))


def sequence(project: Project, sequence_id: str) -> Sequence:
    for found in project.sequences:
        if found.id == sequence_id:
            return found
    raise EditError(f"no sequence {sequence_id!r}")


def span(project: Project, seq: Sequence) -> tuple[float, float]:
    """When the sequence starts and ends: its earliest member start to its latest member end (a key is an
    instant). (0, 0) for a sequence with no members left."""
    clips = {(layer.id, c.id): c for layer in project.layers for c in layer.clips}
    starts, ends = [], []
    for ref in seq.clips:
        clip = clips.get((ref.layer, ref.clip))
        if clip is not None:
            starts.append(clip.start)
            ends.append(clip.end)
    for ref in seq.keys:
        starts.append(ref.t)
        ends.append(ref.t)
    return (min(starts), max(ends)) if starts else (0.0, 0.0)


def selection_of(seq: Sequence) -> shift_timing.Selection:
    """The sequence's members as ``shift_timing`` moves them: its clips, and its keys by layer and time,
    each with the properties of that time that are members."""
    by_time: dict[tuple[str, float], list[str]] = {}
    for ref in seq.keys:
        by_time.setdefault((ref.layer, ref.t), []).append(ref.track)
    keys = tuple((layer, t, tuple(sorted(set(tracks)))) for (layer, t), tracks in sorted(by_time.items()))
    clips = tuple(dict.fromkeys((ref.layer, ref.clip) for ref in seq.clips))
    return shift_timing.Selection(clips=clips, keys=keys)


def sequence_of_clip(project: Project, layer_id: str, clip_id: str) -> Sequence | None:
    return next(
        (s for s in project.sequences if any(r.layer == layer_id and r.clip == clip_id for r in s.clips)),
        None,
    )


def sequence_of_key(project: Project, layer_id: str, track: str, t: float) -> Sequence | None:
    half = 0.5 / project.canvas.fps
    return next(
        (
            s
            for s in project.sequences
            if any(r.layer == layer_id and r.track == track and abs(r.t - t) < half for r in s.keys)
        ),
        None,
    )


def new_sequence_name(project: Project) -> str:
    """``Sequence <n>`` with the smallest ``n`` no sequence is called."""
    names = {s.name for s in project.sequences}
    n = 1
    while f"Sequence {n}" in names:
        n += 1
    return f"Sequence {n}"


# -- edits ------------------------------------------------------------------------------------------


def make_sequence(
    project: Project, name: str, members: Members, colour: str | None = None, recipe: str | None = None
) -> Edit:
    """A new sequence of ``members``, appended to ``project.sequences`` (``recipe``: the recipe it is an
    instance of, ADR 0080). Refused when there are no members, when one does not exist, or when one is
    already in another sequence."""
    name = str(name).strip()
    if not name:
        raise EditError("a sequence needs a name")
    if members.empty:
        raise EditError("select the clips and keys to put in the sequence")
    if colour is not None and not is_colour(colour):
        raise EditError(f"{colour!r} is not a colour (#rgb or #rrggbb)")
    fps = project.canvas.fps
    half = 0.5 / fps
    clip_refs: list[SequenceClip] = []
    for layer_id, clip_id in dict.fromkeys(members.clips):
        edits._clip(project, layer_id, clip_id)
        if (other := sequence_of_clip(project, layer_id, clip_id)) is not None:
            raise EditError(f"clip {clip_id!r} of {_label(project, layer_id)} is in {other.name!r} already")
        clip_refs.append(SequenceClip(layer=layer_id, clip=clip_id))
    key_refs: list[SequenceKey] = []
    seen: set[tuple[str, str, int]] = set()
    for layer_id, track, t in members.keys:
        layer = edits._layer(project, layer_id)
        key = next((k for k in layer.tracks.get(track, []) if abs(k.t - t) < half), None)
        if key is None:
            raise EditError(f"{_label(project, layer_id)} has no {track} key at {t:g} s")
        if (layer_id, track, round(key.t * fps)) in seen:
            continue
        seen.add((layer_id, track, round(key.t * fps)))
        if (other := sequence_of_key(project, layer_id, track, key.t)) is not None:
            raise EditError(
                f"the {track} key of {_label(project, layer_id)} at {key.t:g} s is in {other.name!r} already"
            )
        key_refs.append(SequenceKey(layer=layer_id, track=track, t=key.t))
    seq = Sequence(
        id=_free_sequence_id(project), name=name, colour=colour, clips=clip_refs, keys=key_refs, recipe=recipe
    )
    return _with_sequences(project, [*project.sequences, seq])


def dissolve_sequence(project: Project, sequence_id: str) -> Edit:
    """Remove the sequence; its clips and keys stay where they are."""
    sequence(project, sequence_id)
    return _with_sequences(project, [s for s in project.sequences if s.id != sequence_id])


def rename_sequence(project: Project, sequence_id: str, name: str) -> Edit:
    """Give the sequence another name."""
    found = sequence(project, sequence_id)
    name = str(name).strip()
    if not name:
        raise EditError("a sequence needs a name")
    return _replaced(project, found.model_copy(update={"name": name}))


def set_sequence_colour(project: Project, sequence_id: str, colour: str | None) -> Edit:
    """The colour of the sequence's band on the timeline (None: the theme's accent)."""
    found = sequence(project, sequence_id)
    if colour is not None and not is_colour(colour):
        raise EditError(f"{colour!r} is not a colour (#rgb or #rrggbb)")
    return _replaced(project, found.model_copy(update={"colour": colour}))


def move_sequence(project: Project, sequence_id: str, delta: float) -> Edit:
    """Move every member by ``delta`` seconds with ``shift_timing`` (keys on frames, a boundary clip's
    explicit Appears at / Disappears at carried, never below 0 s, refused whole with the schema's reason);
    the scene grows to hold what moved later. The sequence keeps its members."""
    found = sequence(project, sequence_id)
    if abs(delta) < EPS:
        return Edit(project, "timing", frozenset())
    edit = shift_timing.shift_timing(project, selection_of(found), delta)
    return _grown(project, edit)


def retime_sequence(project: Project, sequence_id: str, new_length: float) -> Edit:
    """Give the sequence another length: each member's start (and a clip's duration) is scaled about the
    sequence's start; keys land on frames. A layer's explicit Appears at / Disappears at on a member clip's
    edge is scaled with it. Refused, with the reason, when two keys of one property would fall on one frame
    or the schema refuses the result (two clips of one layer overlapping)."""
    found = sequence(project, sequence_id)
    if new_length <= EPS:
        raise EditError("a sequence needs a length above 0 s")
    start, end = span(project, found)
    if end - start < EPS:
        raise EditError(f"{found.name!r} lasts no time: there is nothing to stretch")
    factor = new_length / (end - start)
    if abs(factor - 1.0) < EPS:
        return Edit(project, "timing", frozenset())
    return _relayout(
        project, found, {layer: (start, start, factor) for layer in member_layers(project, found)}
    )


# -- per layer: stagger and recipe parameters (ADR 0080) --------------------------------------------


def member_layers(project: Project, seq: Sequence) -> list[str]:
    """The layers with members, in the order they start (ties: the order the members are listed)."""
    order = list(dict.fromkeys([ref.layer for ref in seq.clips] + [ref.layer for ref in seq.keys]))
    starts = {layer: layer_span(project, seq, layer)[0] for layer in order}
    return sorted(order, key=lambda layer: (round(starts[layer], 9), order.index(layer)))


def layer_span(project: Project, seq: Sequence, layer_id: str) -> tuple[float, float]:
    """When the sequence's members on one layer start and end."""
    part = seq.model_copy(
        update={
            "clips": [r for r in seq.clips if r.layer == layer_id],
            "keys": [r for r in seq.keys if r.layer == layer_id],
        }
    )
    return span(project, part)


def stagger_of(project: Project, seq: Sequence) -> float | None:
    """The delay between consecutive layers' starts when it is the same for all (within half a frame),
    else None; 0 for a sequence on one layer."""
    starts = [layer_span(project, seq, layer)[0] for layer in member_layers(project, seq)]
    if len(starts) < 2:
        return 0.0
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    half = 0.5 / project.canvas.fps
    return round(gaps[0], 6) if all(abs(g - gaps[0]) < half for g in gaps) else None


def fit_factor(offsets: list[float], lengths: list[float], total: float) -> float:
    """How much to stretch each layer's part (``lengths``, starting ``offsets`` after the start, kept) so
    the latest one ends ``total`` after the start. ``EditError`` when it cannot."""
    if total <= EPS:
        raise EditError("the length must be above 0 s")
    if max(lengths, default=0.0) <= EPS:
        raise EditError("it lasts no time: there is nothing to stretch")
    if any(o > total + EPS for o in offsets):
        raise EditError(f"the delays between layers alone take more than {total:g} s")
    factor = min((total - o) / length for o, length in zip(offsets, lengths, strict=True) if length > EPS)
    if factor <= EPS:
        raise EditError(f"the delays between layers leave no time in {total:g} s")
    return factor


def restagger_sequence(
    project: Project, sequence_id: str, stagger: float, order: list[str] | None = None
) -> Edit:
    """Move each layer's members so consecutive layers start ``stagger`` s apart, the first where the
    sequence starts; ``order`` (default: the order they start in) is the layers' order. Nothing is
    stretched. Refused as ``retime_sequence`` is."""
    return reparameterise_sequence(project, sequence_id, None, stagger, order)


def reparameterise_sequence(
    project: Project,
    sequence_id: str,
    length: float | None = None,
    stagger: float | None = None,
    order: list[str] | None = None,
) -> Edit:
    """A recipe's parameters on a sequence (ADR 0080): consecutive layers start ``stagger`` s apart (None:
    as they are), and each layer's part is stretched by one factor so the whole lasts ``length`` (None:
    unstretched) with the delays kept. ``order`` lists the member layers in their new order."""
    found = sequence(project, sequence_id)
    if stagger is not None and stagger < -EPS:
        raise EditError("the delay between layers cannot be below 0 s")
    layers = member_layers(project, found)
    if order is not None:
        if sorted(order) != sorted(layers):
            raise EditError(f"the order must list the layers of {found.name!r}, each once")
        layers = list(order)
    start, _end = span(project, found)
    spans = [layer_span(project, found, layer) for layer in layers]
    offsets = (
        [i * stagger for i in range(len(layers))] if stagger is not None else [s - start for s, _ in spans]
    )
    lengths = [e - s for s, e in spans]
    factor = 1.0 if length is None else fit_factor(offsets, lengths, length)
    maps = {
        layer: (s, start + offset, factor)
        for layer, (s, _e), offset in zip(layers, spans, offsets, strict=True)
    }
    if all(abs(old - new) < EPS and abs(f - 1.0) < EPS for old, new, f in maps.values()):
        return Edit(project, "timing", frozenset())
    return _relayout(project, found, maps)


def _relayout(project: Project, found: Sequence, maps: dict[str, tuple[float, float, float]]) -> Edit:
    """Each member layer's members mapped ``t -> new + (t - old) * factor`` (``maps[layer]``): clip starts
    and durations, keys on frames, an explicit Appears at / Disappears at on a member clip's edge. Refused
    when two keys of one property would share a frame or the schema refuses the result."""
    fps = project.canvas.fps
    half = 0.5 / fps

    def mapper(layer_id: str):
        old, new, factor = maps[layer_id]
        return lambda t: new + (t - old) * factor

    def on_grid(layer_id: str):
        scaled = mapper(layer_id)
        return lambda t: round(scaled(t) * fps) / fps

    clip_ids: dict[str, set[str]] = {}
    for ref in found.clips:
        clip_ids.setdefault(ref.layer, set()).add(ref.clip)
    key_refs: dict[str, list[SequenceKey]] = {}
    for ref in found.keys:
        key_refs.setdefault(ref.layer, []).append(ref)
    layers = []
    for layer in project.layers:
        if layer.id not in maps:
            layers.append(layer)
            continue
        scaled, grid, factor = mapper(layer.id), on_grid(layer.id), maps[layer.id][2]
        data = layer.model_dump(by_alias=True)
        ids = clip_ids.get(layer.id, set())
        life = dict(data["lifetime"])
        for c in data["clips"]:
            if c["id"] not in ids:
                continue
            if life.get("in") is not None and abs(life["in"] - c["start"]) < half:
                life["in"] = scaled(life["in"])
            if life.get("out") is not None and abs(life["out"] - (c["start"] + c["duration"])) < half:
                life["out"] = scaled(life["out"])
            c["duration"] *= factor
            c["start"] = scaled(c["start"])
        data["lifetime"] = life
        data["clips"].sort(key=lambda c: c["start"])
        for ref in key_refs.get(layer.id, []):
            for k in data["tracks"].get(ref.track, []):
                if abs(k["t"] - ref.t) < half and not k.get("_moved"):
                    k["t"], k["_moved"] = grid(k["t"]), True
                    break
        for track, keys in data["tracks"].items():
            for k in keys:
                k.pop("_moved", None)
            keys.sort(key=lambda k: k["t"])
            frames = [round(k["t"] * fps) for k in keys]
            if len(frames) != len(set(frames)):
                raise EditError(
                    f"{layer.label}: two {track} keys would fall on one frame at that length; "
                    "make it longer or move them apart first"
                )
        layers.append(_validated_layer(data))
    # a key is in one sequence only: the moved key members are this sequence's own
    keys = [ref.model_copy(update={"t": on_grid(ref.layer)(ref.t)}) for ref in found.keys]
    sequences = [s.model_copy(update={"keys": keys}) if s.id == found.id else s for s in project.sequences]
    return _rebuilt(project, layers=layers, sequences=sequences)


def duplicate_sequence(project: Project, sequence_id: str, at: float) -> Edit:
    """Copy the sequence's clips and keys, each on its own layer and track, so the copy starts at ``at``,
    as a new sequence (last in ``project.sequences``, named "<name> copy"). The copies get fresh clip ids;
    keys land on frames. Refused when a copied key would land on a key already there, or the schema refuses
    the result (a copied clip on top of another, a second morph into one layer), with the reason."""
    found = sequence(project, sequence_id)
    if at < 0:
        raise EditError("a sequence cannot start before 0 s")
    start, _end = span(project, found)
    offset = at - start
    fps = project.canvas.fps
    half = 0.5 / fps

    def on_grid(t: float) -> float:
        return round((t + offset) * fps) / fps

    clip_refs: list[SequenceClip] = []
    key_refs: list[SequenceKey] = []
    touched = {ref.layer for ref in found.clips} | {ref.layer for ref in found.keys}
    layers = []
    for layer in project.layers:
        if layer.id not in touched:
            layers.append(layer)
            continue
        data = layer.model_dump(by_alias=True)
        taken = {c.id for c in layer.clips}
        for ref in found.clips:
            if ref.layer != layer.id:
                continue
            clip = next(c for c in layer.clips if c.id == ref.clip)
            new_id = edits._free_id(clip.kind, taken)
            taken.add(new_id)
            copied = {**clip.model_dump(by_alias=True), "id": new_id, "start": clip.start + offset}
            data["clips"].append(copied)
            clip_refs.append(SequenceClip(layer=layer.id, clip=new_id))
        for ref in found.keys:
            if ref.layer != layer.id:
                continue
            track = data["tracks"][ref.track]
            key = next(k for k in layer.tracks[ref.track] if abs(k.t - ref.t) < half)
            t = on_grid(key.t)
            if any(abs(k["t"] - t) < half for k in track):
                raise EditError(f"{layer.label} already has a {ref.track} key at {t:g} s")
            track.append({**key.model_dump(by_alias=True), "t": t})
            key_refs.append(SequenceKey(layer=layer.id, track=ref.track, t=t))
        data["clips"].sort(key=lambda c: c["start"])
        for track in data["tracks"].values():
            track.sort(key=lambda k: k["t"])
        layers.append(_validated_layer(data))
    copy = Sequence(
        id=_free_sequence_id(project),
        name=f"{found.name} copy",
        colour=found.colour,
        clips=clip_refs,
        keys=key_refs,
        recipe=found.recipe,
    )
    return _rebuilt(project, layers=layers, sequences=[*project.sequences, copy])


# -- helpers ----------------------------------------------------------------------------------------


def _label(project: Project, layer_id: str) -> str:
    return edits._layer(project, layer_id).label


def _free_sequence_id(project: Project) -> str:
    taken = {x.id for x in project.layers} | {a.id for a in project.audio}
    taken |= {c.id for c in project.subtitles} | {m.id for m in project.markers}
    taken |= {g.id for g in project.guides} | {s.id for s in project.sequences}
    return edits._free_id("sequence", taken)


def _validated_layer(data: dict) -> Layer:
    try:
        return Layer.model_validate(data)
    except ValidationError as exc:
        raise EditError(_reason(exc)) from exc


def _reason(exc: ValidationError) -> str:
    return str(exc.errors()[0]["msg"]).removeprefix("Value error, ")


def _replaced(project: Project, changed: Sequence) -> Edit:
    return _with_sequences(project, [changed if s.id == changed.id else s for s in project.sequences])


def _with_sequences(project: Project, sequences: Iterable[Sequence]) -> Edit:
    try:
        new = edits._rebuilt(project, sequences=list(sequences))
    except ValidationError as exc:
        raise EditError(_reason(exc)) from exc
    return Edit(new, "timing", frozenset())


def _rebuilt(project: Project, **parts) -> Edit:
    """The project with new layers and sequences, validated (the schema's reason when refused), grown."""
    try:
        new = edits._rebuilt(project, **parts)
    except ValidationError as exc:
        raise EditError(_reason(exc)) from exc
    return _grown(project, Edit(new, *edits.classify(project, new)))


def _grown(before: Project, edit: Edit) -> Edit:
    grown = grow_to_fit(edit.project)
    return Edit(grown, *edits.classify(before, grown)) if grown is not edit.project else edit
