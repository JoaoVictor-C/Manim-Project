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

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from .schema import Clip, Easing, Keyframe, Layer, Project, Spec

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
    """Change fields of one clip (validated; raises ``ValidationError`` if invalid)."""
    layer = _layer(project, layer_id)
    if not any(c.id == clip_id for c in layer.clips):
        raise EditError(f"layer {layer_id!r} has no clip {clip_id!r}")
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
    """Delete a layer, and the morph clip that turns another layer into it (ADR 0005)."""
    _layer(project, layer_id)
    layers = []
    for layer in project.layers:
        if layer.id == layer_id:
            continue
        if any(c.to_layer == layer_id for c in layer.clips):
            data = layer.model_dump(by_alias=True)
            data["clips"] = [c for c in data["clips"] if c["to_layer"] != layer_id]
            layer = Layer.model_validate(data)
        layers.append(layer)
    return _replace_layers(project, layers)


def move_layer(project: Project, layer_id: str, index: int) -> Edit:
    """Change a layer's z-order: ``index`` 0 is the back, ``len(layers) - 1`` the front."""
    layer = _layer(project, layer_id)
    layers = [other for other in project.layers if other.id != layer_id]
    layers.insert(max(0, min(index, len(layers))), layer)
    return _replace_layers(project, layers)


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
    )
    return _replace_layer(project, layer_id, {"clips": [*layer.clips, clip]})


def remove_clip(project: Project, layer_id: str, clip_id: str) -> Edit:
    _clip(project, layer_id, clip_id)
    clips = [c for c in project.layer(layer_id).clips if c.id != clip_id]
    return _replace_layer(project, layer_id, {"clips": clips})


# -- keyframes (S3, ADR 0016) ------------------------------------------------------


def set_key(project: Project, layer_id: str, prop: str, t: float, value: Any) -> Edit:
    """Set ``prop`` to ``value`` at ``t`` (frame-quantized) on the layer's track.

    A key within half a frame of ``t`` is replaced and keeps its ease. A new
    key inherits the ease of the key before it, unless that ease does not end
    at its target (``there_and_back``): then it gets the default ease.
    """
    layer = _layer(project, layer_id)
    fps = project.canvas.fps
    t = round(t * fps) / fps
    track = list(layer.tracks.get(prop, []))
    value = tuple(value) if isinstance(value, (list, tuple)) else value
    for i, key in enumerate(track):
        if abs(key.t - t) < 0.5 / fps:
            track[i] = Keyframe(t=key.t, value=value, ease=key.ease)
            break
    else:
        before = [key for key in track if key.t < t]
        ease = before[-1].ease if before and _reaches_target(before[-1].ease) else Easing()
        track.append(Keyframe(t=t, value=value, ease=ease))
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
        tracks[prop] = [*others, Keyframe(t=t_to, value=key.value, ease=key.ease)]
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
        tracks[prop] = [*track[:index], Keyframe(t=key.t, value=key.value, ease=ease), *track[index + 1 :]]
        changed = True
    if not changed:
        raise EditError(f"layer {layer_id!r} has no keys at {t:g} s")
    return _replace_layer(project, layer_id, {"tracks": tracks})


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
    return _free_id(type_name, {layer.id for layer in project.layers})


def new_clip_id(layer: Layer, kind: str) -> str:
    """``<kind>-<n>`` with the smallest free ``n`` on this layer's lane."""
    return _free_id(kind, {clip.id for clip in layer.clips})


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
        if layer_kind is None:
            continue
        touched.add(layer_id)
        if _SEVERITY[layer_kind] > _SEVERITY[kind]:
            kind = layer_kind
    return kind, frozenset(touched | _morph_partners(old, touched) | _morph_partners(new, touched))


def _layer_kind(a: Layer, b: Layer) -> EditKind | None:
    if a == b:
        return None
    if a.spec != b.spec:
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
        {"schema_version": project.schema_version, "canvas": project.canvas, "layers": layers}
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
