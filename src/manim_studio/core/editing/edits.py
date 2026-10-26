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

import itertools
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import ValidationError

from ..code import helpers
from ..model import glyph_colours, motion_paths, parts, shape
from ..model.schema import (
    CAMERA_FIELDS,
    GLYPH_COLOURS,
    GROUP_TYPE,
    RUNS_CODE,
    TEXT_TYPES,
    AudioClip,
    Camera,
    Clip,
    Cue,
    Easing,
    Helper,
    Keyframe,
    Layer,
    Marker,
    PartKey,
    Project,
    Spec,
    SubtitleStyle,
    Transform2D,
    VoiceChoice,
    clip_params,
    infer_lifetime,
    is_colour,
    new_clip_params,
)
from . import equation_steps

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
    # Code texts the edit rewrote, (before, after): renaming a helper fixes the imports of the code
    # that uses it (ADR 0058). Trust is by hash, so the caller trusts each ``after`` whose ``before``
    # was trusted (``TrustStore.carry``).
    rewritten: tuple[tuple[str, str], ...] = ()


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


def split_code_layer(project: Project, layer_id: str, chapters: list[tuple[str, int, float, str]]) -> Edit:
    """Replace a code layer by one layer per chapter (ADR 0061), in one undo step.

    ``chapters`` are ``(code, start frame, clock value at that frame, name)``, in order, the first at frame 0.
    Each new layer is the old one with another code, a ``start_frame`` and a ``start_time`` (its scene clock
    starts there, to the last bit of the whole scene's): it keeps the transform, keys
    and opacity, starts at the old start plus ``start_frame / fps``, and ends where the next begins (a held
    last frame must not draw over the next chapter); the last one ends where the old layer did.
    """
    layer = _layer(project, layer_id)
    if layer.spec is None or layer.spec.type != "Code":
        raise EditError(f"{layer.label!r} is not a code layer")
    if project.children(layer_id) or layer.is_child:
        raise EditError(f"{layer.label!r} has parts or belongs to another object")
    if len(chapters) < 2 or chapters[0][1] != 0:
        raise EditError("a split needs at least two chapters, the first at frame 0")
    fps = project.canvas.fps
    start, end = project.lifetime(layer_id)
    out_end = None if math.isinf(end) else end
    taken = {x.id for x in project.layers} | {c.id for c in project.audio}
    taken |= {c.id for c in project.subtitles} | {m.id for m in project.markers}
    new_layers = []
    for number, (code, frame, clock, name) in enumerate(chapters):
        new_id = _free_id("Code", taken)
        taken.add(new_id)
        following = start + chapters[number + 1][1] / fps if number + 1 < len(chapters) else out_end
        data = layer.model_dump(by_alias=True)
        params = {**data["spec"]["params"], "code": code}
        if frame:
            params["start_frame"] = frame
            params["start_time"] = clock
        else:
            params.pop("start_frame", None)
            params.pop("start_time", None)
        data.update(
            id=new_id,
            name=f"{layer.label} - {name}",
            spec={**data["spec"], "params": params},
            lifetime={"in": start + frame / fps, "out": following},
        )
        new_layers.append(Layer.model_validate(data))
    layers = []
    for existing in project.layers:
        if existing.id == layer_id:
            layers.extend(new_layers)
        else:
            layers.append(existing)
    return _replace_layers(project, layers)


def move_code_to_new_layer(project: Project, layer_id: str, kept: str, moved: str, name: str = "") -> Edit:
    """Give some of a scene's statements a layer of their own (ADR 0061), in one undo step: the layer
    keeps the code ``kept``, and a copy of it - same transform, keys, opacity and lifetime - right above
    it runs ``moved``. The two cache and render separately from then on."""
    layer = _layer(project, layer_id)
    if layer.spec is None or layer.spec.type != "Code":
        raise EditError(f"{layer.label!r} is not a code layer")
    if project.children(layer_id) or layer.is_child:
        raise EditError(f"{layer.label!r} has parts or belongs to another object")
    new_id = new_layer_id(project, "Code")
    data = layer.model_dump(by_alias=True)
    data.update(id=new_id, name=name or f"{layer.label} (moved)")
    data["spec"]["params"] = {**data["spec"]["params"], "code": moved}
    original = layer.model_dump(by_alias=True)
    original["spec"]["params"] = {**original["spec"]["params"], "code": kept}
    layers = []
    for existing in project.layers:
        if existing.id == layer_id:
            layers += [Layer.model_validate(original), Layer.model_validate(data)]
        else:
            layers.append(existing)
    return _replace_layers(project, layers)


def remove_layer(project: Project, layer_id: str) -> Edit:
    """Delete a layer with its parts, and morph clips that turn another layer into one of them
    (and what is drawn from it: objects on a deleted graph, traces of it, connectors to it)."""
    return remove_layers(project, [layer_id])


def remove_layers(project: Project, layer_ids) -> Edit:
    """Delete several layers at once (one undo step, ADR 0043), as ``remove_layer`` does each."""
    layer_ids = list(layer_ids)
    if not layer_ids:
        raise EditError("no layers to delete")
    gone: set[str] = set()
    for layer_id in layer_ids:
        _layer(project, layer_id)
        gone |= {layer_id} | {d.id for d in project.descendants(layer_id)}
    while True:  # and what is built from a deleted graph (ADR 0030), traces of what is deleted (ADR 0033)
        more = {x.id for x in project.layers if x.id not in gone and set(project.referenced_graphs(x)) & gone}
        more |= (project.traces_of(gone) | project.connectors_of(gone)) - gone  # and connectors (ADR 0036)
        more |= {  # and a group left with nothing in it (ADR 0050)
            x.id
            for x in project.layers
            if x.is_group
            and x.id not in gone
            and (kids := project.children(x.id))
            and all(k.id in gone for k in kids)
        }
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


# -- groups (U6, ADR 0050) ---------------------------------------------------------------


def group_layers(project: Project, layer_ids: Iterable[str], name: str = "") -> Edit:
    """Put whole objects in a new group, drawn where the front-most of them was (the others come
    up to it, in their order). Their ids, specs, clips and keys are kept; the group's transform is
    the identity, so nothing moves."""
    picked = list(dict.fromkeys(layer_ids))
    if not picked:
        raise EditError("select the objects to group")
    for layer_id in picked:
        layer = _layer(project, layer_id)
        if layer.is_group:
            raise EditError(f"{layer.label!r} is a group: groups cannot be put in a group (not yet)")
        if layer.is_child:
            owner = project.layer(layer.parent_id)
            what = "is a part of" if layer.is_part else "belongs to"
            raise EditError(f"{layer.label!r} {what} {owner.label!r}: group whole objects")
        if project.children(layer_id):
            raise EditError(
                f"{layer.label!r} has parts or objects on axes: it cannot be in a group (not yet)"
            )
    chosen = set(picked)
    group = Layer(id=new_layer_id(project, GROUP_TYPE), name=name, spec=Spec(type=GROUP_TYPE))
    members = [x.model_copy(update={"parent_id": group.id}) for x in project.layers if x.id in chosen]
    front = max(i for i, x in enumerate(project.layers) if x.id in chosen)
    layers = []
    for i, layer in enumerate(project.layers):
        if layer.id not in chosen:
            layers.append(layer)
        elif i == front:
            layers += [group, *members]
    return _validated(project, layers, "Group")


def ungroup(project: Project, group_id: str) -> Edit:
    """Take a group's objects out of it, where it was drawn, each keeping how it looks: the
    group's transform is baked into their own (exact while the group is not keyed: refused then),
    and its Appears / Disappears into their lifetimes."""
    group = _layer(project, group_id)
    if not group.is_group:
        raise EditError(f"{group.label!r} is not a group")
    if any(group.tracks.values()):
        raise EditError(
            f"{group.label!r} has keyframes: bake the keys first (remove them, keeping its look) to ungroup"
        )
    g_start, g_end = project.lifetime(group_id)
    sources = project.morph_sources()
    freed: list[Layer] = []
    for child in project.children(group_id):
        data = _carried(child, group.base).model_dump(by_alias=True)
        data["parent_id"] = None
        start, end = infer_lifetime(child, sources.get(child.id))
        if group.lifetime.in_ is not None and start < g_start:
            data["lifetime"]["in"] = g_start  # the group made it appear later
        if group.lifetime.out is not None and end > g_end:
            data["lifetime"]["out"] = g_end
        freed.append(Layer.model_validate(data))
    layers = []
    for layer in project.layers:
        if layer.id == group_id:
            layers += freed
        elif layer.parent_id != group_id:
            layers.append(layer)
    return _validated(project, layers, "Ungroup")


def _carried(layer: Layer, outer: Transform2D) -> Layer:
    """``layer`` with ``outer`` (a constant parent transform) composed onto its own transform.

    World = G(C(p)) with G, C similarities about their anchors. Keeping C's anchor, the composed
    transform has scale sG*sC, rotation rG+rC, opacity oG*oC and position A_G pos + A_G anchor
    - anchor + b_G: affine in pos alone, so every key (and path tangent) maps exactly."""
    if outer == Transform2D():
        return layer
    angle = math.radians(outer.rotation)
    c, s = math.cos(angle) * outer.scale, math.sin(angle) * outer.scale
    a = np.array([[c, -s], [s, c]])
    g_anchor = np.array(outer.anchor, dtype=float)
    b_g = np.array(outer.position, dtype=float) + g_anchor - a @ g_anchor
    anchor = np.array(layer.base.anchor, dtype=float)
    shift = a @ anchor - anchor + b_g

    def point(value) -> tuple[float, float]:
        x, y = a @ np.asarray(value, dtype=float) + shift
        return (float(x), float(y))

    def vector(value):
        if value is None:
            return None
        x, y = a @ np.asarray(value, dtype=float)
        return (float(x), float(y))

    maps = {
        "position": point,
        "scale": lambda v: v * outer.scale,
        "rotation": lambda v: v + outer.rotation,
        "opacity": lambda v: v * outer.opacity,
    }
    base = layer.base.model_copy(update={name: maps[name](getattr(layer.base, name)) for name in maps})
    tracks = {}
    for name, track in layer.tracks.items():
        tracks[name] = [
            key.model_copy(
                update={
                    "value": maps[name](key.value),
                    "in_tangent": vector(key.in_tangent),
                    "out_tangent": vector(key.out_tangent),
                }
            )
            for key in track
        ]
    return layer.model_copy(update={"base": base, "tracks": tracks})


def _validated(project: Project, layers: list[Layer], verb: str) -> Edit:
    """``_replace_layers``, a refusal of the project's rules said as an ``EditError``."""
    try:
        return _replace_layers(project, layers)
    except ValidationError as error:
        message = str(error.errors()[0]["msg"]).removeprefix("Value error, ")
        raise EditError(f"cannot {verb.lower()}: {message}") from None


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


def set_part_style(project: Project, layer_id: str, **style: Any) -> Edit:
    """Change a part's colours (ADR 0049): each given key is set, or removed when None.

    The keys are those ``Spec.style`` uses (``fill``, ``stroke``, ...); the layer validates them."""
    layer = _layer(project, layer_id)
    if not layer.is_part:
        raise EditError(f"{layer_id!r} is not a part: colour an object with its style")
    merged = {k: v for k, v in {**layer.style, **style}.items() if v is not None}
    return _replace_layer(project, layer_id, {"style": merged})


def colour_part(project: Project, parent_id: str, tex: str, occurrence: int = 0, **style: Any) -> Edit:
    """Colour the ``occurrence``-th ``tex`` of an equation (or part) in one edit (ADR 0049): its part
    layer if it has one, else a new part. Raises ``EditError`` when the part would not resolve."""
    key = PartKey(tex=tex, occurrence=occurrence)
    existing = next((x for x in project.children(parent_id) if x.part == key), None)
    if existing is not None:
        return set_part_style(project, existing.id, **style)
    added = add_part(project, parent_id, tex, occurrence)
    (new_id,) = {x.id for x in added.project.layers} - {x.id for x in project.layers}
    final = set_part_style(added.project, new_id, **style).project
    kind, layer_ids = classify(project, final)
    return Edit(final, kind, layer_ids)


def set_text_colour(project: Project, layer_id: str, piece: str, colour: str | None) -> Edit:
    """Colour every ``piece`` of a Text (Manim's ``t2c``, ADR 0049), or stop colouring it (None)."""
    layer = _layer(project, layer_id)
    if layer.spec is None or layer.spec.type != "Text":
        raise EditError(f"{layer_id!r} is not a Text")
    if not piece:
        raise EditError("type the piece of text to colour")
    t2c = dict(layer.spec.params.get("t2c") or {})
    if colour is None:
        t2c.pop(piece, None)
    else:
        t2c[piece] = colour  # a recoloured piece keeps its place in the list
    params = {k: v for k, v in layer.spec.params.items() if k != "t2c"}
    if t2c:
        params["t2c"] = t2c
    return _replace_layer(project, layer_id, {"spec": layer.spec.model_copy(update={"params": params})})


def set_glyph_colours(project: Project, layer_id: str, colours: Iterable[str | None] | None) -> Edit:
    """One colour per drawn glyph of a Text, MathTex or Tex (ADR 0055), None keeping the object's
    colour; trailing Nones are dropped and a list of only Nones removes the param (the object as
    it was). The layer validates the colours."""
    layer = _layer(project, layer_id)
    if layer.spec is None or layer.spec.type not in TEXT_TYPES:
        raise EditError(f"{layer_id!r} is not a Text, MathTex or Tex")
    kept = glyph_colours.normalised(colours)
    params = {k: v for k, v in layer.spec.params.items() if k != GLYPH_COLOURS}
    if kept:
        params[GLYPH_COLOURS] = kept
    return _replace_layer(project, layer_id, {"spec": layer.spec.model_copy(update={"params": params})})


def insert_scene(
    project: Project, scene: Project, offset: float = 0.0, replace: str | None = None
) -> tuple[Edit, list[str]]:
    """An imported scene's layers, sounds and subtitles in ``project`` (P10.3, ADR 0053), as one
    edit, and the new layers' ids: on top of the other layers - or where the code layer ``replace``
    was, which they replace - every time moved by ``offset``. Ids that are taken are renamed (with
    the morphs and paths naming them); a subtitle overlapping one already there is left out; the scene
    grows to hold them."""
    taken = {x.id for x in project.layers if x.id != replace}
    taken |= (
        {c.id for c in project.audio} | {c.id for c in project.subtitles} | {m.id for m in project.markers}
    )
    names: dict[str, str] = {}
    for layer in scene.layers:
        new = layer.id if layer.id not in taken else _free_id(re.sub(r"-\d+$", "", layer.id), taken)
        names[layer.id] = new
        taken.add(new)

    def moved(value: float | None) -> float | None:
        return None if value is None else value + offset

    added = []
    for layer in scene.layers:
        data = layer.model_dump(by_alias=True)
        data["id"] = names[layer.id]
        if data.get("parent_id") is not None:
            data["parent_id"] = names[data["parent_id"]]
        data["lifetime"] = {"in": moved(layer.lifetime.in_), "out": moved(layer.lifetime.out)}
        for clip in data["clips"]:
            clip["start"] += offset
            if clip.get("to_layer"):
                clip["to_layer"] = names[clip["to_layer"]]
            if clip.get("params", {}).get("path") in names:
                clip["params"]["path"] = names[clip["params"]["path"]]
        for track in data["tracks"].values():
            for key in track:
                key["t"] += offset
        added.append(Layer.model_validate(data))
    layers = list(project.layers)
    index = len(layers)
    if replace is not None:
        index = next(i for i, x in enumerate(layers) if x.id == replace)
        del layers[index]
    layers[index:index] = added
    audio = list(project.audio)
    for clip in scene.audio:
        new_id = _free_id("sound", taken)
        taken.add(new_id)
        audio.append(clip.model_copy(update={"id": new_id, "start": clip.start + offset}))
    cues = list(project.subtitles)
    for cue in scene.subtitles:
        start, end = cue.start + offset, cue.end + offset
        if any(start < c.end - 1e-9 and c.start < end - 1e-9 for c in cues):
            continue  # one lane (ADR 0035)
        new_id = _free_id("cue", taken)
        taken.add(new_id)
        cues.append(cue.model_copy(update={"id": new_id, "start": start, "end": end}))
    canvas = project.canvas
    if scene.canvas.duration + offset > canvas.duration:
        canvas = canvas.model_copy(update={"duration": scene.canvas.duration + offset})
    new = _rebuilt(project, layers=layers, audio=audio, subtitles=cues, canvas=canvas)
    kind, layer_ids = classify(project, new)
    return Edit(new, kind, layer_ids), [names[x.id] for x in scene.layers]


def freeze_layer(project: Project, layer_id: str, data: dict[str, Any]) -> Edit:
    """Turn an object into a shape of what it draws (ADR 0052): plain vector data that needs no
    code, no trust and no LaTeX. ``data`` is ``adapter.freeze_data`` of the layer's spec - what
    it draws, with its style - computed by the caller, which knows whether it is drawn here.

    The layer keeps its id, name, transform, keys, lifetime, clips and group; its style is in the
    data, so the shape's own style is empty (a theme or the Style section recolours it later).
    Raises ``EditError`` with the reason when the layer cannot be frozen (``shape.freeze_problem``)
    or the data is not a shape's."""

    _layer(project, layer_id)
    problem = shape.freeze_problem(project, layer_id)
    if problem is not None:
        raise EditError(f"cannot freeze {layer_id!r}: {problem}")
    problem = shape.spec_problem(data)
    if problem is not None:
        raise EditError(f"cannot freeze {layer_id!r}: {problem}")
    frozen = Spec(type=shape.SHAPE_TYPE, params=data)
    layer = project.layer(layer_id)
    fields: dict[str, Any] = {"spec": frozen}
    if not layer.name and layer.label != layer.id:
        fields["name"] = layer.label  # a text was named by its words: the shape keeps that name
    try:
        return _replace_layer(project, layer_id, fields)
    except ValidationError as exc:  # a rule elsewhere in the project needs the old type
        reason = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise EditError(f"cannot freeze {layer_id!r}: {reason}") from None


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


ENTRANCES = ("Write", "FadeIn")  # how the first equation step appears (P11)


def add_equation_steps(
    project: Project,
    steps: Iterable[str],
    *,
    start: float = 0.0,
    step_duration: float = 1.0,
    hold: float = 1.0,
    font_size: float | None = None,
    colour: str | None = None,
    highlight_colour: str | None = None,
    position: tuple[float, float] = (0.0, 0.0),
    name: str = "Step",
    entrance: str = "Write",
) -> tuple[Edit, equation_steps.StepsReport]:
    """One MathTex layer per step, morphing from each to the next (P11, ADR 0054), in one edit.

    The first step enters with ``entrance`` at ``start``; every animation runs ``step_duration``
    and is followed by ``hold`` seconds of stillness. Step k morphs into step k+1 (``to_layer``)
    with the kind ``equation_steps.plan_transition`` picks, so each step is visible only between
    the morph that brings it and the morph that turns it into the next (lifetimes are inferred,
    ADR 0005); the last one stays. With ``highlight_colour``, the pieces new in a step are part
    layers in that colour (ADR 0049) - the next step's copies are plain again; pieces the parts
    cannot isolate are skipped and reported. All steps sit at ``position``; the scene grows to
    hold the last step for ``hold`` seconds when it grows with its content."""
    steps = [str(s).strip() for s in steps]
    if not steps:
        raise EditError("type at least one equation")
    if len(steps) > equation_steps.MAX_STEPS:
        raise EditError(f"{len(steps)} steps: at most {equation_steps.MAX_STEPS}")
    if any(not s for s in steps):
        raise EditError("a step is empty")
    if not step_duration > 0 or not hold >= 0 or not start >= 0:
        raise EditError("start and hold must be 0 or more, and the step duration more than 0")
    if entrance not in ENTRANCES:
        raise EditError(f"the first step enters with {' or '.join(ENTRANCES)}, not {entrance!r}")
    for what, value in (("colour", colour), ("highlight colour", highlight_colour)):
        if value is not None and not is_colour(value):
            raise EditError(f"the {what} must be like #ff0000, not {value!r}")
    if font_size is not None and not 4 <= font_size <= 400:
        raise EditError("the font size must be from 4 to 400")
    params: dict[str, Any] = {}
    if font_size is not None and font_size != 48:
        params["font_size"] = float(font_size)
    style = {"fill": colour} if colour and colour.lower() != equation_steps.BASE_COLOUR.lower() else {}
    taken = {layer.id for layer in project.layers} | {clip.id for clip in project.audio}
    taken |= {cue.id for cue in project.subtitles} | {marker.id for marker in project.markers}
    ids = []
    for _ in steps:
        ids.append(_free_id("MathTex", taken))
        taken.add(ids[-1])
    plans = [equation_steps.plan_transition(a, b) for a, b in itertools.pairwise(steps)]
    cycle = step_duration + hold
    added: list[Layer] = []
    highlighted: list[tuple[int, str, int]] = []
    skipped: list[tuple[int, str, str]] = []
    for index, (layer_id, tex) in enumerate(zip(ids, steps, strict=True)):
        clips = []
        if index == 0:
            clips.append(
                Clip(id=_free_id(entrance, set()), kind=entrance, start=start, duration=step_duration)
            )
        if index < len(steps) - 1:
            kind = plans[index].kind
            clips.append(
                Clip(
                    id=_free_id(kind, {c.id for c in clips}),
                    kind=kind,
                    start=start + (index + 1) * cycle,
                    duration=step_duration,
                    to_layer=ids[index + 1],
                    params=new_clip_params(kind, project.morph_matching),  # as the project chose (ADR 0056)
                )
            )
        root = Layer(
            id=layer_id,
            name=f"{name} {index + 1}" if name else "",
            spec=Spec(type="MathTex", params={"text": tex, **params}, style=style),
            base=Transform2D(position=position),
            clips=clips,
        )
        added.append(root)
        plan = plans[index - 1] if index > 0 else None
        if plan is None or highlight_colour is None or plan.kind != equation_steps.MATCHING:
            continue
        skipped += [(index + 1, tex_, why) for tex_, why in plan.skipped if tex_]
        candidates = []
        for piece in plan.new:
            part_id = _free_id("part", taken)
            taken.add(part_id)
            key = PartKey(tex=piece.tex, occurrence=piece.occurrence)
            candidates.append(
                Layer(id=part_id, parent_id=layer_id, part=key, style={"fill": highlight_colour})
            )
        alone = root.model_copy(update={"clips": []})  # its morph's target is not made yet
        resolution = parts.resolve(Project(layers=[alone, *candidates]), layer_id)
        for part in candidates:
            if part.id in resolution.orphans:
                skipped.append((index + 1, part.part.tex, resolution.orphans[part.id]))
                continue
            added.append(part)
            highlighted.append((index + 1, part.part.tex, part.part.occurrence))
    end = start + len(steps) * step_duration + (len(steps) - 1) * hold
    canvas = project.canvas
    if canvas.grow_with_content and canvas.duration < end + hold - 1e-9:
        frames = math.ceil((end + hold) * canvas.fps - 1e-9)
        canvas = canvas.model_copy(update={"duration": frames / canvas.fps})
    try:
        new = _rebuilt(project, layers=[*project.layers, *added], canvas=canvas)
    except ValidationError as error:
        message = str(error.errors()[0]["msg"]).removeprefix("Value error, ")
        raise EditError(f"cannot add equation steps: {message}") from None
    report = equation_steps.StepsReport(
        layer_ids=tuple(ids),
        transitions=tuple(plan.kind for plan in plans),
        highlighted=tuple(highlighted),
        skipped=tuple(skipped),
        end=end,
    )
    return Edit(new, *classify(project, new)), report


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


def auto_key_places(project: Project, layer_id: str, t: float) -> bool:
    """With auto-key on, does an edit of an untracked property at ``t`` just place the object?

    Yes when the object has nothing to animate from: at its first frame (a one-key track is
    the base again but switches the stopwatch rule on, so every later move became a key), and
    for an object that has no entrance clip, no keys and no appear time (a new object, drawn
    from the start of the scene: keys at 0 and at the playhead made it glide in from the
    middle). Auto-key animates once the object has an entrance (a clip, keys or Appears at)
    and the playhead is past its start; a part has the entrance of its parent.
    """
    layer = _layer(project, layer_id)
    fps = project.canvas.fps
    start = round(project.lifetime(layer_id)[0] * fps) / fps
    if round(t * fps) / fps <= start + 0.5 / fps:
        return True
    chain = [layer, *project.ancestors(layer_id)]  # a part enters with its parent
    return not any(x.clips or x.tracks or x.lifetime.in_ is not None for x in chain)


def set_property(
    project: Project, layer_id: str, prop: str, value: Any, t: float, auto_key: bool = False
) -> Edit:
    """Change a transform property the way the editor does (ADR 0016, ADR 0018).

    * keyed property: a key at ``t`` (frame-quantized);
    * untracked, auto-key off: the base value;
    * untracked, auto-key on: a new track animating from the old value at the
      layer's start to ``value`` at ``t`` - but where there is nothing to animate yet the
      base changes (see ``auto_key_places``): placing an object is not animating it.
    """
    layer = _layer(project, layer_id)
    if layer.tracks.get(prop):
        return set_key(project, layer_id, prop, t, value)
    if not auto_key or auto_key_places(project, layer_id, t):
        base = layer.base.model_dump()
        base[prop] = value
        return update_layer(project, layer_id, base=base)
    fps = project.canvas.fps
    start = round(project.lifetime(layer_id)[0] * fps) / fps
    t = round(t * fps) / fps
    with_old = set_key(project, layer_id, prop, start, getattr(layer.base, prop)).project
    final = set_key(with_old, layer_id, prop, t, value).project
    kind, layer_ids = classify(project, final)
    return Edit(final, kind, layer_ids)


def clear_track(project: Project, layer_id: str, prop: str, at: float) -> Edit:
    """Remove ``prop``'s keyframes, keeping the value they give at ``at`` as the base."""
    from ..engine.evaluator import layer_transform  # sampling rules live with the evaluator (imports Manim)

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
    from ..engine.evaluator import layer_transform  # sampling rules live with the evaluator (imports Manim)

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


def set_params(project: Project, layer_id: str, params: dict[str, Any], shift: Any = (0.0, 0.0)) -> Edit:
    """Change some of a layer's object parameters (a canvas handle, ADR 0043), moving it by
    ``shift``: on the base and on every position key (a rigid shift of the path), so a line's
    other end stays where it was. Never creates keys."""
    layer = _layer(project, layer_id)
    if layer.spec is None:
        raise EditError(f"layer {layer_id!r} has no object")
    spec = layer.spec.model_copy(update={"params": {**layer.spec.params, **params}})
    fields: dict[str, Any] = {"spec": spec}
    dx, dy = float(shift[0]), float(shift[1])
    if dx or dy:

        def shifted(value) -> tuple[float, float]:
            return (value[0] + dx, value[1] + dy)

        base = layer.base.model_dump()
        base["position"] = shifted(layer.base.position)
        fields["base"] = base
        if layer.tracks.get("position"):
            moved = [k.model_copy(update={"value": shifted(k.value)}) for k in layer.tracks["position"]]
            fields["tracks"] = {**layer.tracks, "position": moved}
    return _replace_layer(project, layer_id, fields)


CANVAS_FIELDS = frozenset({"duration", "width_px", "height_px", "fps", "background", "grow_with_content"})


def set_canvas(project: Project, **fields: Any) -> Edit:
    """Change the scene's settings (P7.1): its length, size, frame rate, background, or whether its
    length grows with its content. The layers are untouched; the edit kind is ``spec`` for all of
    them (every frame may change), ``timing`` for none when only the length or the growth changes."""
    unknown = set(fields) - CANVAS_FIELDS
    if unknown:
        raise EditError(f"not a scene setting: {', '.join(sorted(unknown))}")
    canvas = project.canvas.model_validate({**project.canvas.model_dump(), **fields})
    new = _rebuilt(project, canvas=canvas)
    picture = {"width_px", "height_px", "fps", "background"} & {
        k for k in fields if getattr(project.canvas, k) != getattr(canvas, k)
    }
    if not picture:
        return Edit(new, "timing", frozenset())
    return Edit(new, "spec", frozenset(layer.id for layer in project.layers))


def set_morph_matching(project: Project, matching: str) -> Edit:
    """How the morph clips added from now on match their pieces: 'smart' or 'classic' (ADR 0056).
    Existing clips keep their own choice; no frame changes."""
    if matching not in ("smart", "classic"):
        raise EditError(f"morph matching is smart or classic, not {matching!r}")
    return Edit(_rebuilt(project, morph_matching=matching), "timing", frozenset())


def set_camera(project: Project, **fields: Any) -> Edit:
    """Change the camera's angles (ADR 0048): ``phi``, ``theta``, ``gamma`` in degrees, validated.
    Every frame may change, so the edit kind is ``spec`` for every layer (``classify`` agrees)."""
    unknown = set(fields) - set(CAMERA_FIELDS)
    if unknown:
        raise EditError(f"not a camera setting: {', '.join(sorted(unknown))}")
    try:
        camera = Camera.model_validate({**project.camera.model_dump(), **fields})
    except ValidationError as exc:
        raise EditError(f"camera: {exc.errors()[0]['msg']}") from exc
    if camera == project.camera:
        return Edit(project, "timing", frozenset())
    return Edit(_rebuilt(project, camera=camera), "spec", frozenset(layer.id for layer in project.layers))


def reset_camera(project: Project) -> Edit:
    """Back to the flat 2D view (ADR 0048)."""
    return set_camera(project, **Camera().model_dump())


def anchor_shifts_elsewhere(layer: Layer) -> bool:
    """Whether moving the anchor keeps the drawing only at the edit time (keyed rotation/scale)."""
    return bool(layer.tracks.get("rotation") or layer.tracks.get("scale"))


def retime_keys(
    project: Project, layer_id: str, t_from: float, t_to: float, props: Iterable[str] | None = None
) -> Edit:
    """Move every key at ``t_from`` (within half a frame) to ``t_to`` (P2b): of every property,
    or of ``props`` only (the graph editor moves one curve's key, P6b.2)."""
    layer = _layer(project, layer_id)
    fps = project.canvas.fps
    t_to = round(t_to * fps) / fps
    wanted = set(props) if props is not None else None
    tracks, moved = {}, False
    for prop, track in layer.tracks.items():
        index = _key_index(track, t_from, fps)
        if index is None or (wanted is not None and prop not in wanted):
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


def remove_keys(project: Project, layer_id: str, t: float, props: Iterable[str] | None = None) -> Edit:
    """Remove every key at ``t`` (of ``props`` only, if given); a property losing its last key
    keeps that value as its base."""
    layer = _layer(project, layer_id)
    fps = project.canvas.fps
    wanted = set(props) if props is not None else None
    tracks, base, removed = {}, layer.base.model_dump(), False
    for prop, track in layer.tracks.items():
        index = _key_index(track, t, fps)
        if index is None or (wanted is not None and prop not in wanted):
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
    from ..engine.adapter import rate_func  # the evaluator's sampling rule (imports Manim)

    return rate_func(key.ease)(u)


def _key_index(track: list[Keyframe], t: float, fps: int) -> int | None:
    for i, key in enumerate(track):
        if abs(key.t - t) < 0.5 / fps:
            return i
    return None


def _reaches_target(ease: Easing) -> bool:
    from ..engine import adapter

    return abs(adapter.rate_func(ease)(1.0) - 1.0) < 1e-6


def new_layer_id(project: Project, type_name: str) -> str:
    """``<type>-<n>`` with the smallest free ``n`` (e.g. ``mathtex-1``)."""
    taken = {layer.id for layer in project.layers} | {clip.id for clip in project.audio}
    taken |= {cue.id for cue in project.subtitles} | {marker.id for marker in project.markers}
    return _free_id(type_name, taken)


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
    return Edit(_rebuilt(project, audio=audio), "timing", frozenset())


def _rebuilt(project: Project, **parts: Any) -> Project:
    """The project with some of its parts replaced, validated (unchanged parts are reused as-is)."""
    data = {
        "schema_version": project.schema_version,
        "canvas": project.canvas,
        "layers": project.layers,
        "audio": project.audio,
        "subtitles": project.subtitles,
        "subtitle_style": project.subtitle_style,
        "markers": project.markers,
        "camera": project.camera,
        "morph_matching": project.morph_matching,
        "helpers": project.helpers,
        "voice": project.voice,
        "pronunciations": project.pronunciations,
    }
    return Project.model_validate({**data, **parts})


# -- helpers (ADR 0058) -------------------------------------------------------------------------------
# A helper's code can change what every code layer and Python object draws: ``classify`` marks them
# all ``spec`` when the helpers' code changes (coarse on purpose); a description changes nothing.


def add_helper(project: Project, name: str, code: str, description: str = "") -> Edit:
    """A new helper named ``name`` (a Python name that hides no module: ``helpers.check_name``)."""
    problem = helpers.check_name(name, (h.name for h in project.helpers), installed=True)
    if problem is not None:
        raise EditError(problem)
    if len(project.helpers) >= helpers.MAX_HELPERS:
        raise EditError(f"a project has at most {helpers.MAX_HELPERS} helpers")
    helper = _new_helper(name, code, description)
    return _replace_helpers(project, [*project.helpers, helper])


def update_helper(
    project: Project, name: str, code: str | None = None, description: str | None = None
) -> Edit:
    """Change a helper's code and/or description."""
    old = _helper(project, name)
    helper = _new_helper(
        name, old.code if code is None else code, old.description if description is None else description
    )
    return _replace_helpers(project, [helper if h.name == name else h for h in project.helpers])


def rename_helper(project: Project, old: str, new: str, *, fix_imports: bool = True) -> Edit:
    """Rename helper ``old`` to ``new``. With ``fix_imports`` the code layers, Python objects and
    other helpers that import it are rewritten to import ``new`` (``helpers.rename_imports``: only
    the import statements and, when safe, the uses of a plain ``import old``); the texts rewritten
    are in ``Edit.rewritten``, so their trust can follow."""
    helper = _helper(project, old)
    if new == old:
        return Edit(project, "timing", frozenset())
    problem = helpers.check_name(new, (h.name for h in project.helpers if h.name != old), installed=True)
    if problem is not None:
        raise EditError(problem)
    rewritten: list[tuple[str, str]] = []

    def fixed(code: str) -> str:
        if not fix_imports:
            return code
        out = helpers.rename_imports(code, old, new)
        if out is None:
            return code
        rewritten.append((code, out))
        return out

    renamed = []
    for h in project.helpers:
        if h.name == old:
            renamed.append(_new_helper(new, helper.code, helper.description))
            continue
        code = fixed(h.code) if old in helpers.imports_of(h.code) else h.code
        renamed.append(h if code == h.code else _new_helper(h.name, code, h.description))
    layers = []
    for layer in project.layers:
        code = str(layer.spec.params.get("code", "")) if layer.spec is not None else ""
        if layer.spec is not None and layer.spec.type in RUNS_CODE and old in helpers.imports_of(code):
            after = fixed(code)
            if after != code:  # rebuilt from data so the layer's validators run
                data = layer.model_dump(by_alias=True)
                data["spec"]["params"]["code"] = after
                layer = Layer.model_validate(data)
        layers.append(layer)
    edit = _replace_helpers(project, renamed, layers)
    return Edit(edit.project, edit.kind, edit.layer_ids, tuple(rewritten))


def remove_helper(project: Project, name: str, *, force: bool = False) -> Edit:
    """Delete a helper; refused while code imports it, unless ``force`` (that code then fails at its
    import, as any missing module)."""
    _helper(project, name)
    users = helpers.importers(project, name)
    if users and not force:
        labels = [
            f"helper {key.removeprefix('helper:')}" if key.startswith("helper:") else project.layer(key).label
            for key in users
        ]
        raise EditError(f"helper {name!r} is imported by {', '.join(labels)}")
    return _replace_helpers(project, [h for h in project.helpers if h.name != name])


def _helper(project: Project, name: str) -> Helper:
    try:
        return project.helper(name)
    except KeyError:
        raise EditError(f"no helper {name!r}") from None


def _new_helper(name: str, code: str, description: str) -> Helper:
    try:
        return Helper(name=name, code=code, description=description)
    except ValidationError as exc:
        raise EditError(str(exc.errors()[0]["msg"]).removeprefix("Value error, ")) from exc


def _replace_helpers(project: Project, new_helpers: list[Helper], layers: list[Layer] | None = None) -> Edit:
    parts: dict[str, Any] = {"helpers": new_helpers}
    if layers is not None:
        parts["layers"] = layers
    try:
        new_project = _rebuilt(project, **parts)
    except ValidationError as exc:
        raise EditError(str(exc.errors()[0]["msg"]).removeprefix("Value error, ")) from exc
    kind, layer_ids = classify(project, new_project)
    return Edit(new_project, kind, layer_ids)


# -- subtitles (P5a, ADR 0035) ------------------------------------------------------------
# They change no layer: the evaluator keeps every cache; render-ahead re-renders their spans.


def add_cue(project: Project, start: float, end: float, text: str = "") -> Edit:
    cue = Cue(id=new_layer_id(project, "cue"), start=start, end=end, text=text)
    return _replace_subtitles(project, [*project.subtitles, cue])


def update_cue(project: Project, cue_id: str, **fields: Any) -> Edit:
    """Change a subtitle's ``start``, ``end`` or ``text`` (overlapping another one is refused)."""
    _cue(project, cue_id)
    cues = [
        Cue.model_validate({**c.model_dump(), **fields}) if c.id == cue_id else c for c in project.subtitles
    ]
    return _replace_subtitles(project, cues)


def remove_cue(project: Project, cue_id: str, with_audio: bool = True) -> Edit:
    """Delete a subtitle. The sound it generated (narration, ADR 0060) goes with it, so that no
    speech is left without its words; undo brings both back."""
    cue = _cue(project, cue_id)
    cues = [c for c in project.subtitles if c.id != cue_id]
    if with_audio and cue.audio_id is not None and any(clip.id == cue.audio_id for clip in project.audio):
        return set_narration(project, cues, [c for c in project.audio if c.id != cue.audio_id])
    return _replace_subtitles(project, cues)


def set_subtitles(project: Project, cues: list[Cue]) -> Edit:
    """Replace every subtitle (an imported .srt)."""
    return _replace_subtitles(project, cues)


def set_narration(project: Project, cues: list[Cue], audio: list[AudioClip]) -> Edit:
    """Replace the subtitles and the sounds together (generated speech placed, cues retimed): one edit."""
    return Edit(_rebuilt(project, subtitles=cues, audio=audio), "timing", frozenset())


def set_voice(project: Project, voice: VoiceChoice | None) -> Edit:
    """The voice cues without their own are spoken with (None: none)."""
    return Edit(_rebuilt(project, voice=voice), "timing", frozenset())


def set_cue_voice(project: Project, cue_ids: Iterable[str], voice: VoiceChoice | None) -> Edit:
    """A voice of their own for these cues (None: back to the project's)."""
    chosen = set(cue_ids)
    for cue_id in chosen:
        _cue(project, cue_id)
    cues = [c.model_copy(update={"voice": voice}) if c.id in chosen else c for c in project.subtitles]
    return _replace_subtitles(project, cues)


def set_pronunciations(project: Project, pronunciations: dict[str, str]) -> Edit:
    """How written texts are spoken (ADR 0060); empty keys and no-op entries are dropped."""
    cleaned = {
        k.strip(): v.strip() for k, v in pronunciations.items() if k.strip() and k.strip() != v.strip()
    }
    return Edit(_rebuilt(project, pronunciations=cleaned), "timing", frozenset())


def set_subtitle_style(project: Project, **fields: Any) -> Edit:
    style = SubtitleStyle.model_validate({**project.subtitle_style.model_dump(), **fields})
    return Edit(_rebuilt(project, subtitle_style=style), "timing", frozenset())


def _cue(project: Project, cue_id: str) -> Cue:
    for cue in project.subtitles:
        if cue.id == cue_id:
            return cue
    raise EditError(f"no subtitle {cue_id!r}")


def _replace_subtitles(project: Project, cues: list[Cue]) -> Edit:
    return Edit(_rebuilt(project, subtitles=cues), "timing", frozenset())


# -- markers (P5c, ADR 0037) --------------------------------------------------------------
# They change no frame: every cache is kept and render-ahead re-renders nothing.


def add_marker(project: Project, t: float, name: str = "") -> Edit:
    """A marker at the frame nearest ``t`` (refused where one already is)."""
    fps = project.canvas.fps
    if marker_at(project, t) is not None:
        raise EditError(f"a marker is already at {t:g} s")
    marker = Marker(id=new_layer_id(project, "marker"), t=max(0.0, round(t * fps) / fps), name=name)
    return _replace_markers(project, [*project.markers, marker])


def update_marker(project: Project, marker_id: str, **fields: Any) -> Edit:
    """Change a marker's ``t``, ``name`` or ``colour`` (onto another marker's frame is refused)."""
    _marker(project, marker_id)
    if "t" in fields and (other := marker_at(project, fields["t"])) is not None and other.id != marker_id:
        raise EditError(f"marker {other.id!r} is already at {fields['t']:g} s")
    markers = [
        Marker.model_validate({**m.model_dump(), **fields}) if m.id == marker_id else m
        for m in project.markers
    ]
    return _replace_markers(project, markers)


def remove_marker(project: Project, marker_id: str) -> Edit:
    _marker(project, marker_id)
    return _replace_markers(project, [m for m in project.markers if m.id != marker_id])


def marker_at(project: Project, t: float) -> Marker | None:
    """The marker on the frame of ``t``, if any."""
    fps = project.canvas.fps
    return next((m for m in project.markers if round(m.t * fps) == round(t * fps)), None)


def _marker(project: Project, marker_id: str) -> Marker:
    for marker in project.markers:
        if marker.id == marker_id:
            return marker
    raise EditError(f"no marker {marker_id!r}")


def _replace_markers(project: Project, markers: list[Marker]) -> Edit:
    return Edit(_rebuilt(project, markers=markers), "timing", frozenset())


# -- classification -------------------------------------------------------------


def classify(old: Project, new: Project) -> tuple[EditKind, frozenset[str]]:
    """The most severe edit kind between two snapshots, and the layers it touches.

    Morph partners of touched layers are included, so observers (lifetime bands,
    morph caches) refresh both ends.
    """
    old_layers = {layer.id: layer for layer in old.layers}
    new_layers = {layer.id: layer for layer in new.layers}
    # Lookups once per snapshot, not per layer (B53): a root is resolved again only when its parts
    # (their ids, parents and keys) differ; with the same spec and the same parts it builds the same.
    old_parts, new_parts = _part_signature(old), _part_signature(new)
    kind: EditKind = "timing"
    touched: set[str] = set()
    if old.camera != new.camera:  # every object is seen from elsewhere: every frame changes (ADR 0048)
        kind = "spec"
        touched = set(old_layers) | set(new_layers)
    if helpers.code_changed(old, new):  # any code may import a helper (ADR 0058)
        running = {i for i, x in {**old_layers, **new_layers}.items() if x.spec and x.spec.type in RUNS_CODE}
        if running:
            kind = "spec"
            touched |= running
    for layer_id in old_layers.keys() | new_layers.keys():
        a, b = old_layers.get(layer_id), new_layers.get(layer_id)
        # Into, out of or between groups (ADR 0050): built and animated as before, only carried.
        regrouped = (
            a is not None
            and b is not None
            and a.parent_id != b.parent_id
            and _group_or_none(old_layers, a.parent_id)
            and _group_or_none(new_layers, b.parent_id)
        )
        layer_kind = "clip" if a is None or b is None else _layer_kind(a, b, regrouped)
        if (
            layer_kind != "spec"
            and a is not None
            and b is not None
            and b.parent_id is None
            and old_parts.get(layer_id) != new_parts.get(layer_id)
            and parts.build_spec(old, layer_id) != parts.build_spec(new, layer_id)
        ):
            layer_kind = "spec"  # its parts changed: the object is rebuilt with other markers
        if (
            layer_kind != "spec"
            and a is not None
            and b is not None
            and b.is_child
            and not b.is_part
            and not regrouped
            and old_layers[a.parent_id].spec != new_layers[b.parent_id].spec
        ):
            layer_kind = "spec"  # its parent changed: a graph is plotted again on new axes (ADR 0024)
        if (
            layer_kind != "spec"
            and a is not None
            and b is not None
            and old.referenced_graphs(a, old_layers) != new.referenced_graphs(b, new_layers)
        ):
            layer_kind = "spec"  # its graph changed: an area is built again (ADR 0030)
        if layer_kind is None:
            continue
        touched.add(layer_id)
        if _SEVERITY[layer_kind] > _SEVERITY[kind]:
            kind = layer_kind
    return kind, frozenset(touched | _morph_partners(old, touched) | _morph_partners(new, touched))


def _group_or_none(layers: dict[str, Layer], parent_id: str | None) -> bool:
    return parent_id is None or (parent_id in layers and layers[parent_id].is_group)


def _layer_kind(a: Layer, b: Layer, regrouped: bool = False) -> EditKind | None:
    if a == b:
        return None
    moved = a.parent_id != b.parent_id and not regrouped
    if a.spec != b.spec or a.part != b.part or moved or a.style != b.style:
        return "spec"  # a part's colours (ADR 0049) are in its object's states: the tree is redone
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
    if a.base != b.base or a.tracks != b.tracks or a.parent_id != b.parent_id:
        return "transform"  # another group carries it: drawn elsewhere, built the same (ADR 0050)
    return "timing" if timing or a.lifetime != b.lifetime or a.name != b.name else None


def _part_signature(project: Project) -> dict[str, list[tuple[str, str | None, PartKey | None]]]:
    """What ``parts.resolve`` reads of each root's parts: ``(id, parent_id, part key)`` in layer order,
    by root id. Two projects with the same entry (and the same root spec) build the root alike."""
    by_id = {layer.id: layer for layer in project.layers}
    signature: dict[str, list[tuple[str, str | None, PartKey | None]]] = {}
    for layer in project.layers:
        if layer.is_part:
            root = layer
            while root.parent_id is not None:
                root = by_id[root.parent_id]
            signature.setdefault(root.id, []).append((layer.id, layer.parent_id, layer.part))
    return signature


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
    new_project = _rebuilt(project, layers=layers)
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
