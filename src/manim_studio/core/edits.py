"""Document edits (ADR 0013, ADR 0014).

Edits never mutate a ``Project``. Each function returns an ``Edit``: a new,
fully validated snapshot that shares unchanged layers with the old one, plus the
edit *kind* that tells the evaluator which caches to drop:

======== ========================================== ==============================
kind     what changed                               evaluator drops
======== ========================================== ==============================
timing   clip start/duration (lane order unchanged), nothing (morphs re-begin only
         lifetime, name                             if their baked transforms move)
transform base transform or keyframe tracks          nothing (same rule for morphs)
clip     clip kind/params/ease, added/removed/       the layer's clip caches and
         reordered clips                            its morph partners'
spec     the object itself                          as ``clip`` + the built object
======== ========================================== ==============================

The kind is computed by comparing the two snapshots, so callers cannot get it
wrong. This module has no Qt dependency (coding standards rule 1).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from . import motion_paths, parts
from .schema import AudioClip, Clip, Easing, Keyframe, Layer, PartKey, Project, Spec, clip_params

EditKind = Literal["timing", "transform", "clip", "spec"]
_SEVERITY: dict[EditKind, int] = {"timing": 0, "transform": 1, "clip": 2, "spec": 3}
_TIMING_FIELDS = {"start", "duration"}


class EditError(ValueError):
    """An edit referred to something that does not exist."""


@dataclass(frozen=True)
class Edit:
    project: Project
    kind: EditKind
    layer_ids: frozenset[str]


# -- edit functions -------------------------------------------------------------


def update_clip(project: Project, layer_id: str, clip_id: str, **fields: Any) -> Edit:
    """Change fields of one clip (validated; raises ``ValidationError`` if invalid).

    A new kind keeps only the params it registers (ADR 0022): ``Write`` would
    not accept a fade's ``shift``.
    """
    layer = _layer(project, layer_id)
    clip = next((c for c in layer.clips if c.id == clip_id), None)
    if clip is None:
        raise EditError(f"layer {layer_id!r} has no clip {clip_id!r}")
    if "kind" in fields and fields["kind"] != clip.kind and "params" not in fields:
        names = {param.name for param in clip_params(fields["kind"])}
        fields = {**fields, "params": {k: v for k, v in clip.params.items() if k in names}}
    clips = [
        {**c.model_dump(by_alias=True), **fields} if c.id == clip_id else c.model_dump(by_alias=True)
        for c in layer.clips
    ]
    return _replace_layer(project, layer_id, {"clips": clips})


def move_clip(project: Project, layer_id: str, clip_id: str, start: float) -> Edit:
    return update_clip(project, layer_id, clip_id, start=start)


def trim_clip(
    project: Project, layer_id: str, clip_id: str, start: float | None = None, end: float | None = None
) -> Edit:
    """Move one or both edges of a clip; the other edge stays where it is."""
    clip = _clip(project, layer_id, clip_id)
    new_start = clip.start if start is None else start
    new_end = clip.end if end is None else end
    return update_clip(project, layer_id, clip_id, start=new_start, duration=new_end - new_start)


def update_layer(project: Project, layer_id: str, **fields: Any) -> Edit:
    """Change top-level fields of a layer (``base``, ``tracks``, ``spec``, ``lifetime``, ...)."""
    _layer(project, layer_id)
    return _replace_layer(project, layer_id, fields)


# -- structure: layers and clips (S2) ---------------------------------------------


def add_layer(
    project: Project, spec: Spec, *, index: int | None = None, name: str = "", layer_id: str | None = None
) -> Edit:
    """Insert a new layer; by default on top (drawn last). Its id is ``<type>-<n>`` unless given."""
    layer = Layer(id=layer_id or new_layer_id(project, spec.type), name=name, spec=spec)
    layers = list(project.layers)
    layers.insert(len(layers) if index is None else index, layer)
    return _replace_layers(project, layers)


def remove_layer(project: Project, layer_id: str) -> Edit:
    """Delete a layer with its parts, and morph clips that turn another layer into one of them
    (and what is drawn from it: objects on a deleted graph, traces of it)."""
    _layer(project, layer_id)
    gone = {layer_id} | {d.id for d in project.descendants(layer_id)}
    while True:  # and what is built from a deleted graph (ADR 0030), traces of what is deleted (ADR 0033)
        more = {x.id for x in project.layers if x.id not in gone and set(project.referenced_graphs(x)) & gone}
        more |= project.traces_of(gone) - gone
        if not more:
            break
        gone |= more
    layers = []
    for layer in project.layers:
        if layer.id in gone:
            continue
        if any(c.to_layer in gone or c.params.get("path") in gone for c in layer.clips):
            data = layer.model_dump(by_alias=True)  # and clips following a deleted path (ADR 0025)
            data["clips"] = [
                c for c in data["clips"] if c["to_layer"] not in gone and c["params"].get("path") not in gone
            ]
            layer = Layer.model_validate(data)
        layers.append(layer)
    return _replace_layers(project, layers)


def move_layer(project: Project, layer_id: str, index: int) -> Edit:
    """Change an object's z-order: ``index`` 0 is the back of the objects (roots), the last the front.

    An object moves together with its parts, which always follow it (ADR 0012).
    """
    layer = _layer(project, layer_id)
    if layer.is_child:
        kind = "a part: parts" if layer.is_part else f"on {layer.parent_id!r}: children"
        raise EditError(f"{layer_id!r} is {kind} are drawn with their object")
    roots = [root for root in project.roots() if root.id != layer_id]
    roots.insert(max(0, min(index, len(roots))), layer)
    return _replace_layers(project, [x for root in roots for x in (root, *project.descendants(root.id))])


# -- parts (P2c, ADR 0012) ------------------------------------------------------------


def add_child(
    project: Project, parent_id: str, spec: Spec, *, name: str = "", layer_id: str | None = None
) -> Edit:
    """A child object under ``parent_id`` (ADR 0024: a graph on axes), drawn after its siblings."""
    _layer(project, parent_id)
    layer = Layer(id=layer_id or new_layer_id(project, spec.type), name=name, spec=spec, parent_id=parent_id)
    family = {parent_id} | {d.id for d in project.descendants(parent_id)}
    last = max(i for i, other in enumerate(project.layers) if other.id in family)
    layers = list(project.layers)
    layers.insert(last + 1, layer)
    return _replace_layers(project, layers)


def add_part(
    project: Project,
    parent_id: str,
    tex: str,
    occurrence: int = 0,
    *,
    name: str = "",
    layer_id: str | None = None,
) -> Edit:
    """Add a part layer: the ``occurrence``-th ``tex`` in the parent's text.

    Raises ``EditError`` with the reason when the part would not resolve (not in
    the text, inside a script, overlapping another part, ...).
    """
    return add_parts(project, parent_id, [(tex, occurrence)], names=[name], layer_ids=[layer_id])


def add_parts(
    project: Project,
    parent_id: str,
    keys: Iterable[tuple[str, int]],
    *,
    names: Iterable[str] | None = None,
    layer_ids: Iterable[str | None] | None = None,
) -> Edit:
    """Add several parts in one edit (one undo step, one rebuild), e.g. from ``parts.split_terms``."""
    _layer(project, parent_id)
    keys = list(keys)
    if not keys:
        raise EditError("no parts to add")
    names = list(names) if names is not None else [""] * len(keys)
    layer_ids = list(layer_ids) if layer_ids is not None else [None] * len(keys)
    taken = {layer.id for layer in project.layers}
    new_layers = []
    for (tex, occurrence), name, layer_id in zip(keys, names, layer_ids, strict=True):
        layer_id = layer_id or _free_id("part", taken)
        taken.add(layer_id)
        new_layers.append(
            Layer(
                id=layer_id,
                name=name or tex,
                parent_id=parent_id,
                part=PartKey(tex=tex, occurrence=occurrence),
            )
        )
    block = [parent_id, *(d.id for d in project.descendants(parent_id))]
    at = max(i for i, layer in enumerate(project.layers) if layer.id in block) + 1
    layers = [*project.layers[:at], *new_layers, *project.layers[at:]]
    try:
        edit = _replace_layers(project, layers)
    except ValueError as error:
        raise EditError(str(error)) from None
    root_id = edit.project.root_of(parent_id).id
    resolution = parts.resolve(edit.project, root_id)
    for layer in new_layers:
        if layer.id in resolution.orphans:
            raise EditError(f"cannot add part {layer.part.tex!r}: {resolution.orphans[layer.id]}")
    return edit


def add_clip(
    project: Project,
    layer_id: str,
    kind: str,
    start: float,
    duration: float,
    *,
    to_layer: str | None = None,
    ease: Easing | None = None,
    clip_id: str | None = None,
    params: dict[str, Any] | None = None,
) -> Edit:
    """Add a clip to a layer's lane (validated: no overlap, nothing after a morph)."""
    layer = _layer(project, layer_id)
    clip = Clip(
        id=clip_id or new_clip_id(layer, kind),
        kind=kind,
        start=start,
        duration=duration,
        to_layer=to_layer,
        ease=ease,
        params=params or {},
    )
    return _replace_layer(project, layer_id, {"clips": [*layer.clips, clip]})


def remove_clip(project: Project, layer_id: str, clip_id: str) -> Edit:
    _clip(project, layer_id, clip_id)
    clips = [c for c in project.layer(layer_id).clips if c.id != clip_id]
    return _replace_layer(project, layer_id, {"clips": clips})


# -- keyframes (S3, ADR 0016) ------------------------------------------------------


def set_key(project: Project, layer_id: str, prop: str, t: float, value: Any) -> Edit:
    """Set ``prop`` to ``value`` at ``t`` (frame-quantized) on the layer's track.

    A key within half a frame of ``t`` is replaced and keeps its ease (and path
    tangents). A new key inherits the ease of the key before it, unless that ease
    does not end at its target (``there_and_back``): then it gets the default ease.
    A new position key inside a curved segment splits it so the path keeps its
    shape (ADR 0026).
    """
    layer = _layer(project, layer_id)
    fps = project.canvas.fps
    t = round(t * fps) / fps
    track = list(layer.tracks.get(prop, []))
    value = tuple(value) if isinstance(value, (list, tuple)) else value
    for i, key in enumerate(track):
        if abs(key.t - t) < 0.5 / fps:
            track[i] = key.model_copy(update={"value": value})
            break
    else:
        before = [key for key in track if key.t < t]
        ease = before[-1].ease if before and _reaches_target(before[-1].ease) else Easing()
        new = Keyframe(t=t, value=value, ease=ease)
        after = [key for key in track if key.t > t]
        if prop == "position" and before and after and (before[-1].out_tangent or after[0].in_tangent):
            k0, k1 = before[-1], after[0]
            fraction = _eased(k0, (t - k0.t) / (k1.t - k0.t))
            out0, _point, in_new, out_new, in1 = motion_paths.split(
                k0.value, k0.out_tangent, k1.in_tangent, k1.value, fraction
            )
            new = new.model_copy(update={"in_tangent": in_new, "out_tangent": out_new})
            track = [
                key.model_copy(update={"out_tangent": out0})
                if key is k0
                else key.model_copy(update={"in_tangent": in1})
                if key is k1
                else key
                for key in track
            ]
        track.append(new)
    return _replace_layer(project, layer_id, {"tracks": {**layer.tracks, prop: track}})


def set_property(
    project: Project, layer_id: str, prop: str, value: Any, t: float, auto_key: bool = False
) -> Edit:
    """Change a transform property the way the editor does (ADR 0016, ADR 0018).

    * keyed property: a key at ``t`` (frame-quantized);
    * untracked, auto-key off: the base value;
    * untracked, auto-key on: a new track animating from the old value at the
      layer's start to ``value`` at ``t`` (one key when ``t`` is the start).
    """
    layer = _layer(project, layer_id)
    if layer.tracks.get(prop):
        return set_key(project, layer_id, prop, t, value)
    if not auto_key:
        base = layer.base.model_dump()
        base[prop] = value
        return update_layer(project, layer_id, base=base)
    fps = project.canvas.fps
    start = round(project.lifetime(layer_id)[0] * fps) / fps
    t = round(t * fps) / fps
    if t <= start + 0.5 / fps:
        return set_key(project, layer_id, prop, t, value)
    with_old = set_key(project, layer_id, prop, start, getattr(layer.base, prop)).project
    final = set_key(with_old, layer_id, prop, t, value).project
    kind, layer_ids = classify(project, final)
    return Edit(final, kind, layer_ids)


def clear_track(project: Project, layer_id: str, prop: str, at: float) -> Edit:
    """Remove ``prop``'s keyframes, keeping the value they give at ``at`` as the base."""
    from .evaluator import layer_transform  # sampling rules live with the evaluator (imports Manim)

    layer = _layer(project, layer_id)
    if prop not in layer.tracks:
        raise EditError(f"layer {layer_id!r} has no {prop} keyframes")
    value = getattr(layer_transform(layer, at), prop)
    base = layer.base.model_dump()
    base[prop] = value
    tracks = {name: keys for name, keys in layer.tracks.items() if name != prop}
    return _replace_layer(project, layer_id, {"tracks": tracks, "base": base})


def set_anchor(project: Project, layer_id: str, anchor: Any, t: float) -> Edit:
    """Move the layer's anchor (its pivot, ADR 0021) without moving the drawing at ``t``.

    The position is compensated by ``(I - A)(old - new)``, ``A`` being the layer's
    rotation and scale at ``t``: on the base, and on every position key (a rigid
    shift of the path). Exact at all times unless rotation or scale is keyed
    (``anchor_shifts_elsewhere``). Never creates keys.
    """
    from .evaluator import layer_transform  # sampling rules live with the evaluator (imports Manim)

    layer = _layer(project, layer_id)
    tr = layer_transform(layer, t)
    angle = math.radians(tr.rotation)
    c, s = math.cos(angle) * tr.scale, math.sin(angle) * tr.scale
    ox, oy = layer.base.anchor[0] - float(anchor[0]), layer.base.anchor[1] - float(anchor[1])
    dx, dy = ox - (c * ox - s * oy), oy - (s * ox + c * oy)

    def shifted(value) -> tuple[float, float]:
        return (value[0] + dx, value[1] + dy)

    base = layer.base.model_dump()
    base["anchor"] = (float(anchor[0]), float(anchor[1]))
    base["position"] = shifted(layer.base.position)
    tracks = dict(layer.tracks)
    if tracks.get("position"):
        tracks["position"] = [k.model_copy(update={"value": shifted(k.value)}) for k in tracks["position"]]
    return _replace_layer(project, layer_id, {"base": base, "tracks": tracks})


def anchor_shifts_elsewhere(layer: Layer) -> bool:
    """Whether moving the anchor keeps the drawing only at the edit time (keyed rotation/scale)."""
    return bool(layer.tracks.get("rotation") or layer.tracks.get("scale"))


def retime_keys(project: Project, layer_id: str, t_from: float, t_to: float) -> Edit:
    """Move every key at ``t_from`` (any property, within half a frame) to ``t_to`` (P2b)."""
    layer = _layer(project, layer_id)
    fps = project.canvas.fps
    t_to = round(t_to * fps) / fps
    tracks, moved = {}, False
    for prop, track in layer.tracks.items():
        index = _key_index(track, t_from, fps)
        if index is None:
            tracks[prop] = track
            continue
        others = [key for i, key in enumerate(track) if i != index]
        if any(abs(key.t - t_to) < 0.5 / fps for key in others):
            raise EditError(f"{prop} already has a key at {t_to:g} s")
        key = track[index]
        tracks[prop] = [*others, key.model_copy(update={"t": t_to})]
        moved = True
    if not moved:
        raise EditError(f"layer {layer_id!r} has no keys at {t_from:g} s")
    return _replace_layer(project, layer_id, {"tracks": tracks})


def remove_keys(project: Project, layer_id: str, t: float) -> Edit:
    """Remove every key at ``t``; a property losing its last key keeps that value as its base."""
    layer = _layer(project, layer_id)
    fps = project.canvas.fps
    tracks, base, removed = {}, layer.base.model_dump(), False
    for prop, track in layer.tracks.items():
        index = _key_index(track, t, fps)
        if index is None:
            tracks[prop] = track
            continue
        removed = True
        if len(track) == 1:
            base[prop] = track[0].value  # nothing jumps when the track disappears
        else:
            tracks[prop] = [key for i, key in enumerate(track) if i != index]
    if not removed:
        raise EditError(f"layer {layer_id!r} has no keys at {t:g} s")
    return _replace_layer(project, layer_id, {"tracks": tracks, "base": base})


def set_key_ease(
    project: Project, layer_id: str, t: float, ease: Easing, props: Iterable[str] | None = None
) -> Edit:
    """Set the ease of the keys at ``t`` (the motion from them to the next key)."""
    layer = _layer(project, layer_id)
    fps = project.canvas.fps
    wanted = set(props) if props is not None else None
    tracks, changed = dict(layer.tracks), False
    for prop, track in layer.tracks.items():
        index = _key_index(track, t, fps)
        if index is None or (wanted is not None and prop not in wanted):
            continue
        key = track[index]
        tracks[prop] = [*track[:index], key.model_copy(update={"ease": ease}), *track[index + 1 :]]
        changed = True
    if not changed:
        raise EditError(f"layer {layer_id!r} has no keys at {t:g} s")
    return _replace_layer(project, layer_id, {"tracks": tracks})


def set_tangents(project: Project, layer_id: str, t: float, in_tangent: Any, out_tangent: Any) -> Edit:
    """The path tangents of the position key at ``t`` (None = no handle; ADR 0026)."""
    layer = _layer(project, layer_id)
    track = list(layer.tracks.get("position", []))
    index = _key_index(track, t, project.canvas.fps)
    if index is None:
        raise EditError(f"layer {layer_id!r} has no position key at {t:g} s")
    track[index] = track[index].model_copy(
        update={"in_tangent": _vec(in_tangent), "out_tangent": _vec(out_tangent)}
    )
    return _replace_layer(project, layer_id, {"tracks": {**layer.tracks, "position": track}})


def smooth_key(project: Project, layer_id: str, t: float) -> Edit:
    """Give the position key at ``t`` aligned handles from its neighbours (ADR 0026)."""
    layer = _layer(project, layer_id)
    track = layer.tracks.get("position", [])
    index = _key_index(track, t, project.canvas.fps)
    if index is None:
        raise EditError(f"layer {layer_id!r} has no position key at {t:g} s")
    here = np.asarray(track[index].value, float)
    prev = np.asarray(track[index - 1].value, float) if index > 0 else None
    nxt = np.asarray(track[index + 1].value, float) if index + 1 < len(track) else None
    if prev is not None and nxt is not None:
        direction = (nxt - prev) / 6
        in_t, out_t = -direction, direction
    elif nxt is not None:
        in_t, out_t = None, (nxt - here) / 3
    elif prev is not None:
        in_t, out_t = (prev - here) / 3, None
    else:
        raise EditError("a single key has no path to smooth")
    return set_tangents(project, layer_id, t, in_t, out_t)


def _vec(value: Any) -> tuple[float, float] | None:
    return None if value is None else (float(value[0]), float(value[1]))


def _eased(key: Keyframe, u: float) -> float:
    from .adapter import rate_func  # the evaluator's sampling rule (imports Manim)

    return rate_func(key.ease)(u)


def _key_index(track: list[Keyframe], t: float, fps: int) -> int | None:
    for i, key in enumerate(track):
        if abs(key.t - t) < 0.5 / fps:
            return i
    return None


def _reaches_target(ease: Easing) -> bool:
    from . import adapter

    return abs(adapter.rate_func(ease)(1.0) - 1.0) < 1e-6


def new_layer_id(project: Project, type_name: str) -> str:
    """``<type>-<n>`` with the smallest free ``n`` (e.g. ``mathtex-1``)."""
    return _free_id(type_name, {layer.id for layer in project.layers} | {clip.id for clip in project.audio})


def new_clip_id(layer: Layer, kind: str) -> str:
    """``<kind>-<n>`` with the smallest free ``n`` on this layer's lane."""
    return _free_id(kind, {clip.id for clip in layer.clips})


# -- sound (P4d, ADR 0034) ------------------------------------------------------------


def add_audio(project: Project, path: str, start: float, duration: float, name: str = "") -> Edit:
    """Add a sound at ``start`` playing ``duration`` seconds of the file (its length, measured
    by the caller): it changes no frame, so every cache is kept."""
    clip = AudioClip(id=new_layer_id(project, "audio"), name=name, path=path, start=start, duration=duration)
    return _replace_audio(project, [*project.audio, clip])


def update_audio(project: Project, clip_id: str, **fields: Any) -> Edit:
    """Change fields of a sound (``start``, ``offset``, ``duration``, ``gain``, fades, ``name``)."""
    _audio(project, clip_id)
    return _replace_audio(
        project,
        [
            AudioClip.model_validate({**c.model_dump(), **fields}) if c.id == clip_id else c
            for c in project.audio
        ],
    )


def trim_audio(project: Project, clip_id: str, start: float | None = None, end: float | None = None) -> Edit:
    """Move one or both edges of a sound on the timeline: the left edge trims the file's start
    (the sound stays where it was in time), the right edge its end."""
    clip = _audio(project, clip_id)
    new_start = clip.start if start is None else max(start, clip.start - clip.offset)
    new_end = clip.end if end is None else end
    offset = clip.offset + (new_start - clip.start)
    return update_audio(project, clip_id, start=new_start, offset=offset, duration=new_end - new_start)


def remove_audio(project: Project, clip_id: str) -> Edit:
    _audio(project, clip_id)
    return _replace_audio(project, [c for c in project.audio if c.id != clip_id])


def _audio(project: Project, clip_id: str) -> AudioClip:
    for clip in project.audio:
        if clip.id == clip_id:
            return clip
    raise EditError(f"no sound {clip_id!r}")


def _replace_audio(project: Project, audio: list[AudioClip]) -> Edit:
    new_project = Project.model_validate(
        {
            "schema_version": project.schema_version,
            "canvas": project.canvas,
            "layers": project.layers,
            "audio": audio,
        }
    )
    return Edit(new_project, "timing", frozenset())


# -- classification -------------------------------------------------------------


def classify(old: Project, new: Project) -> tuple[EditKind, frozenset[str]]:
    """The most severe edit kind between two snapshots, and the layers it touches.

    Morph partners of touched layers are included, so observers (lifetime bands,
    morph caches) refresh both ends.
    """
    old_layers = {layer.id: layer for layer in old.layers}
    new_layers = {layer.id: layer for layer in new.layers}
    kind: EditKind = "timing"
    touched: set[str] = set()
    for layer_id in old_layers.keys() | new_layers.keys():
        a, b = old_layers.get(layer_id), new_layers.get(layer_id)
        layer_kind = "clip" if a is None or b is None else _layer_kind(a, b)
        if (
            layer_kind != "spec"
            and a is not None
            and b is not None
            and b.parent_id is None
            and parts.build_spec(old, layer_id) != parts.build_spec(new, layer_id)
        ):
            layer_kind = "spec"  # its parts changed: the object is rebuilt with other markers
        if (
            layer_kind != "spec"
            and a is not None
            and b is not None
            and b.is_child
            and not b.is_part
            and old.layer(a.parent_id).spec != new.layer(b.parent_id).spec
        ):
            layer_kind = "spec"  # its parent changed: a graph is plotted again on new axes (ADR 0024)
        if (
            layer_kind != "spec"
            and a is not None
            and b is not None
            and old.referenced_graphs(a) != new.referenced_graphs(b)
        ):
            layer_kind = "spec"  # its graph changed: an area is built again (ADR 0030)
        if layer_kind is None:
            continue
        touched.add(layer_id)
        if _SEVERITY[layer_kind] > _SEVERITY[kind]:
            kind = layer_kind
    return kind, frozenset(touched | _morph_partners(old, touched) | _morph_partners(new, touched))


def _layer_kind(a: Layer, b: Layer) -> EditKind | None:
    if a == b:
        return None
    if a.spec != b.spec or a.part != b.part or a.parent_id != b.parent_id:
        return "spec"
    if [c.id for c in a.clips] != [c.id for c in b.clips]:
        return "clip"  # added, removed or reordered: predecessors changed
    timing = False
    for ca, cb in zip(a.clips, b.clips, strict=True):
        if ca == cb:
            continue
        changed = {name for name in Clip.model_fields if getattr(ca, name) != getattr(cb, name)}
        if changed - _TIMING_FIELDS:
            return "clip"
        timing = True
    if a.base != b.base or a.tracks != b.tracks:
        return "transform"
    return "timing" if timing or a.lifetime != b.lifetime or a.name != b.name else None


def _morph_partners(project: Project, layer_ids: set[str]) -> set[str]:
    partners = set()
    for layer in project.layers:
        for clip in layer.clips:
            if clip.to_layer and (layer.id in layer_ids or clip.to_layer in layer_ids):
                partners |= {layer.id, clip.to_layer}
    return partners


# -- helpers --------------------------------------------------------------------


def _layer(project: Project, layer_id: str) -> Layer:
    try:
        return project.layer(layer_id)
    except KeyError:
        raise EditError(f"no layer {layer_id!r}") from None


def _clip(project: Project, layer_id: str, clip_id: str) -> Clip:
    for clip in _layer(project, layer_id).clips:
        if clip.id == clip_id:
            return clip
    raise EditError(f"layer {layer_id!r} has no clip {clip_id!r}")


def _replace_layer(project: Project, layer_id: str, fields: dict[str, Any]) -> Edit:
    old_layer = project.layer(layer_id)
    # Rebuilt from data so the layer's validators run; model_copy(update=) would skip them.
    data = {**old_layer.model_dump(by_alias=True), **_dump(fields)}
    new_layer = Layer.model_validate(data)
    return _replace_layers(
        project, [new_layer if layer.id == layer_id else layer for layer in project.layers]
    )


def _replace_layers(project: Project, layers: list[Layer]) -> Edit:
    # Unchanged layers are reused as-is; the project-level validator still runs.
    new_project = Project.model_validate(
        {
            "schema_version": project.schema_version,
            "canvas": project.canvas,
            "layers": layers,
            "audio": project.audio,
        }
    )
    kind, layer_ids = classify(project, new_project)
    return Edit(new_project, kind, layer_ids)


def _dump(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: _plain(v) for k, v in fields.items()}


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _free_id(prefix: str, taken: set[str]) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-") or "item"
    n = 1
    while f"{stem}-{n}" in taken:
        n += 1
    return f"{stem}-{n}"
