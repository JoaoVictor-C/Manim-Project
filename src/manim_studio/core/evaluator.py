"""Random-access timeline evaluation on top of Manim.

``Scene.play`` is only a driver loop: ``begin()``, then ``interpolate(t / run_time)``
for every frame, then ``finish()``. The evaluator owns that clock instead, so it can
produce the frame at any time ``t`` in any order:

* the state of a layer after each clip is a cached checkpoint (``begin()`` +
  ``finish()`` applied to a copy of the previous checkpoint);
* a clip active at ``t`` owns a working copy that is begun once and then
  ``interpolate(alpha)``-ed for every requested frame;
* keyframed layer transforms are applied to a throwaway copy, never in place.

The frame at ``t`` is therefore a pure function of (project, t).

Edits are applied with ``invalidate`` / ``apply`` and an edit kind (ADR 0008,
ADR 0013): timing and transform edits keep every cache, clip and spec edits drop
the affected layers' caches.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import manim as m
import numpy as np

from ..logging_config import get_logger
from . import adapter
from .edits import Edit, EditKind
from .schema import Clip, Keyframe, Layer, Project, Transform2D

log = get_logger(__name__)


@dataclass
class _Active:
    anim: m.Animation
    drawn: m.Mobject
    baked: tuple[Transform2D, Transform2D] | None = None  # morphs: world transforms at start/end


class Evaluator:
    def __init__(self, project: Project) -> None:
        self.project = project
        self._base: dict[str, m.Mobject] = {}
        self._checkpoints: dict[tuple[str, str], m.Mobject] = {}
        self._active: dict[tuple[str, str], _Active] = {}
        self._proxies: dict[str, m.Mobject] = {}
        self._index_morphs()

    def _index_morphs(self) -> None:
        self._morph_into: dict[str, tuple[Layer, Clip]] = {}
        for layer in self.project.layers:
            for clip in layer.clips:
                if clip.to_layer:
                    self._morph_into[clip.to_layer] = (layer, clip)

    # -- public ----------------------------------------------------------------

    def missing_checkpoints(self) -> list[tuple[Layer, int]]:
        """Checkpoints not yet computed, in dependency order.

        An editor computes one per idle tick (each costs at most ~25 ms) so the
        first frame after a clip ends never stalls playback.
        """
        missing = []
        for layer in self.project.layers:
            for index, clip in enumerate(layer.clips, start=1):
                if clip.info.category == "morph":
                    break  # the layer hands off to its morph target here
                if (layer.id, clip.id) not in self._checkpoints:
                    missing.append((layer, index))
        return missing

    def compute_checkpoint(self, layer: Layer, index: int) -> None:
        self._state_before(layer, index)

    def apply(self, edit: Edit) -> None:
        """Adopt an ``Edit`` from ``core.edits`` (its kind was computed by diffing)."""
        self.invalidate(edit.project, set(edit.layer_ids), edit.kind)

    def invalidate(self, project: Project, layer_ids: set[str], kind: EditKind = "clip") -> None:
        """Adopt an edited ``project`` and drop only the caches the edit can affect.

        Rebuilding the whole evaluator costs 100-200 ms (B3); this keeps edits cheap.

        * ``timing`` / ``transform``: nothing is dropped. Begun animations and
          checkpoints depend on the preceding clips, kind, params and ease, never
          on *when* a clip plays, and layer transforms are applied afterwards on
          scratch proxies. Morphs bake both ends' world transforms, so they are
          re-begun lazily when those transforms differ (``_morph_at``).
        * ``clip`` / ``spec``: the layers' checkpoints, active clips and proxies,
          plus morph partners (a morph reads both ends); ``spec`` also rebuilds the
          base object when its spec changed.
        """
        if kind in ("timing", "transform"):
            self.project = project
            self._index_morphs()
            log.debug("invalidate %s %s: caches kept", kind, layer_ids)
            return
        old_partners = {
            layer.id: {c.to_layer for c in layer.clips if c.to_layer} for layer in self.project.layers
        }
        old_specs = {layer.id: layer.spec for layer in self.project.layers}
        self.project = project
        self._index_morphs()
        affected = set(layer_ids)
        for layer_id in layer_ids:
            affected |= old_partners.get(layer_id, set())
            if layer_id in self._morph_into:
                affected.add(self._morph_into[layer_id][0].id)
        for layer in project.layers:
            if any(c.to_layer in affected for c in layer.clips):
                affected.add(layer.id)
        for cache in (self._checkpoints, self._active):
            for key in [k for k in cache if k[0] in affected]:
                del cache[key]
        log.debug("invalidate %s -> affected %s", layer_ids, affected)
        new_specs = {layer.id: layer.spec for layer in project.layers}
        for layer_id in affected:
            self._proxies.pop(layer_id, None)
            if old_specs.get(layer_id) != new_specs.get(layer_id):
                self._base.pop(layer_id, None)

    def frame(self, t: float) -> list[m.Mobject]:
        """World-space mobjects to draw at time ``t``, back to front.

        The returned mobjects are shared render buffers: draw them before the
        next call, and never mutate them.
        """
        out: list[m.Mobject] = []
        for layer in self.project.layers:
            mob = self._layer_at(layer, t)
            if mob is not None:
                out.append(mob)
        return out

    # -- lifetime --------------------------------------------------------------

    def lifetime(self, layer: Layer) -> tuple[float, float]:
        start, end = layer.lifetime.in_, layer.lifetime.out
        if start is None:
            start = 0.0
            if layer.id in self._morph_into:
                start = self._morph_into[layer.id][1].end
            elif layer.clips and layer.clips[0].info.introducer:
                start = layer.clips[0].start
        if end is None:
            end = math.inf
            for clip in layer.clips:
                info = clip.info
                if info.remover or info.category == "morph":
                    end = clip.end
                    break
        return start, end

    # -- local state (clips) ---------------------------------------------------

    def _base_mobject(self, layer: Layer) -> m.Mobject:
        if layer.id not in self._base:
            self._base[layer.id] = adapter.build_mobject(layer.spec)
        return self._base[layer.id]

    def _state_before(self, layer: Layer, index: int) -> m.Mobject:
        """Local state right before clip ``index`` starts (never mutate it)."""
        if index == 0:
            return self._base_mobject(layer)
        prev = layer.clips[index - 1]
        key = (layer.id, prev.id)
        if key not in self._checkpoints:
            working = self._state_before(layer, index - 1).copy()
            anim = adapter.make_animation(prev.kind, working, prev.ease, prev.params)
            anim.begin()
            anim.finish()
            self._checkpoints[key] = anim.mobject
        return self._checkpoints[key]

    def _layer_at(self, layer: Layer, t: float) -> m.Mobject | None:
        start, end = self.lifetime(layer)
        if not (start <= t < end):  # the lifetime gates everything, clips included
            return None
        for index, clip in enumerate(layer.clips):
            if clip.start <= t < clip.end:
                alpha = (t - clip.start) / clip.duration
                if clip.info.category == "morph":
                    return self._morph_at(layer, index, clip, alpha)
                active = self._activate(layer, index, clip)
                active.anim.interpolate(alpha)
                return self._to_world(active.drawn, layer, t)
        index = sum(1 for clip in layer.clips if clip.end <= t)
        return self._to_world(self._state_before(layer, index), layer, t)

    def _activate(self, layer: Layer, index: int, clip: Clip) -> _Active:
        key = (layer.id, clip.id)
        if key not in self._active:
            working = self._state_before(layer, index).copy()
            anim = adapter.make_animation(clip.kind, working, clip.ease, clip.params)
            anim.begin()
            self._active[key] = _Active(anim, anim.mobject)
        return self._active[key]

    def _morph_at(self, layer: Layer, index: int, clip: Clip, alpha: float) -> m.Mobject:
        """Morphs are world-space hand-offs: A at clip start -> B at clip end (ADR 0005).

        The begun animation bakes both ends' world transforms, so it is reused
        only while those transforms are unchanged (ADR 0013): moving a morph whose
        partners are static or settled costs no new ``begin()``.
        """
        key = (layer.id, clip.id)
        target_layer = self.project.layer(clip.to_layer)
        baked = (self.transform_at(layer, clip.start), self.transform_at(target_layer, clip.end))
        cached = self._active.get(key)
        if cached is None or cached.baked != baked:
            # _to_world may return shared buffers; the animation mutates its inputs.
            source = self._to_world(self._state_before(layer, index), layer, clip.start).copy()
            target = self._to_world(self._base_mobject(target_layer), target_layer, clip.end).copy()
            anim = adapter.make_animation(clip.kind, source, clip.ease, clip.params, target)
            anim.begin()
            self._active[key] = _Active(anim, anim.mobject, baked)
        active = self._active[key]
        active.anim.interpolate(alpha)
        return active.drawn

    # -- layer transform (keyframes) -------------------------------------------

    def transform_at(self, layer: Layer, t: float) -> Transform2D:
        base = layer.base
        values = {
            name: _sample(layer.tracks.get(name), t, getattr(base, name))
            for name in ("position", "scale", "rotation", "opacity")
        }
        return Transform2D(**values)

    def _to_world(self, local: m.Mobject, layer: Layer, t: float) -> m.Mobject:
        """Apply the keyframed layer transform without touching ``local``.

        The result is a per-layer scratch mobject that is fully overwritten on
        every call, so it is only valid until the next ``frame()``.
        """
        tr = self.transform_at(layer, t)
        if tr == _IDENTITY:
            return local
        proxy = self._proxies.get(layer.id)
        if proxy is None or not _same_structure(proxy, local):
            proxy = local.copy()
            self._proxies[layer.id] = proxy
        angle = math.radians(tr.rotation)
        c, s = math.cos(angle) * tr.scale, math.sin(angle) * tr.scale
        matrix = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, tr.scale]])
        offset = np.array([tr.position[0], tr.position[1], 0.0])
        for dst, src in zip(proxy.get_family(), local.get_family(), strict=True):
            _copy_drawable_state(dst, src)
            if len(src.points):
                dst.points = src.points @ matrix.T + offset
            if tr.opacity != 1:
                _multiply_opacity(dst, tr.opacity)
        return proxy


def _sample(track: list[Keyframe] | None, t: float, default):
    if not track:
        return default
    if t <= track[0].t:
        return track[0].value
    if t >= track[-1].t:
        return track[-1].value
    for k0, k1 in itertools.pairwise(track):
        if k0.t <= t < k1.t:
            u = adapter.rate_func(k0.ease)((t - k0.t) / (k1.t - k0.t))
            if isinstance(k0.value, tuple):
                return tuple(a + (b - a) * u for a, b in zip(k0.value, k1.value, strict=True))
            return k0.value + (k1.value - k0.value) * u
    return track[-1].value


_IDENTITY = Transform2D()

# Everything Manim's Cairo camera reads from a VMobject besides its points.
_VMOBJECT_STATE = (
    "fill_rgbas",
    "stroke_rgbas",
    "background_stroke_rgbas",
    "stroke_width",
    "background_stroke_width",
    "sheen_factor",
    "sheen_direction",
    "joint_type",
    "cap_style",
)


def _same_structure(a: m.Mobject, b: m.Mobject) -> bool:
    fa, fb = a.get_family(), b.get_family()
    return len(fa) == len(fb) and all(
        type(x) is type(y) and x.points.shape == y.points.shape for x, y in zip(fa, fb, strict=True)
    )


def _copy_drawable_state(dst: m.Mobject, src: m.Mobject) -> None:
    if isinstance(src, m.VMobject):
        for attr in _VMOBJECT_STATE:
            value = getattr(src, attr, None)
            if isinstance(value, np.ndarray):
                value = value.copy()
            setattr(dst, attr, value)
    elif isinstance(src, m.ImageMobject):
        # Copy: ImageMobject.set_opacity and fades write pixel_array in place, so a
        # shared array would let one frame corrupt the source state of the next.
        dst.pixel_array = src.pixel_array.copy()


def _multiply_opacity(sub: m.Mobject, factor: float) -> None:
    if isinstance(sub, m.VMobject):
        for attr in ("fill_rgbas", "stroke_rgbas", "background_stroke_rgbas"):
            rgbas = getattr(sub, attr, None)
            if rgbas is not None and len(rgbas):
                rgbas[:, 3] *= factor
    elif isinstance(sub, m.ImageMobject):
        # Not set_opacity(): it is relative to the ORIGINAL alpha and would discard
        # the current one (e.g. mid-FadeIn). Multiply what is there instead.
        sub.pixel_array[:, :, 3] = (sub.pixel_array[:, :, 3] * factor).astype(np.uint8)
