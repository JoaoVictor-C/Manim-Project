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
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import manim as m
import numpy as np

from ..logging_config import get_logger
from . import adapter
from .schema import Clip, Keyframe, Layer, Project, Transform2D

log = get_logger(__name__)


@dataclass
class _Active:
    anim: m.Animation
    drawn: m.Mobject


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
                if adapter.CLIP_KINDS[clip.kind].category == "morph":
                    break  # the layer hands off to its morph target here
                if (layer.id, clip.id) not in self._checkpoints:
                    missing.append((layer, index))
        return missing

    def compute_checkpoint(self, layer: Layer, index: int) -> None:
        self._state_before(layer, index)

    def invalidate(self, project: Project, layer_ids: set[str], transform_only: bool = False) -> None:
        """Adopt an edited ``project`` and drop caches of the changed layers only.

        Morph partners are invalidated too: a morph clip reads both ends.
        Rebuilding the whole evaluator costs 100-200 ms; this keeps edits cheap.

        ``transform_only`` is for edits to position/scale/rotation/opacity (gizmo
        drags, keyframes): layer transforms are applied after clips on scratch
        proxies, so only morph clips, which bake both ends' transforms, go stale.
        """
        if transform_only:
            self.project = project
            self._index_morphs()
            stale = {
                (layer.id, clip.id)
                for layer in project.layers
                for clip in layer.clips
                if clip.to_layer and (layer.id in layer_ids or clip.to_layer in layer_ids)
            }
            for key in stale:
                self._active.pop(key, None)
            log.debug("invalidate transform-only %s: %d morph clips dropped", layer_ids, len(stale))
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
            elif layer.clips and adapter.CLIP_KINDS[layer.clips[0].kind].introducer:
                start = layer.clips[0].start
        if end is None:
            end = math.inf
            for clip in layer.clips:
                info = adapter.CLIP_KINDS[clip.kind]
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
        for index, clip in enumerate(layer.clips):
            if clip.start <= t < clip.end:
                alpha = (t - clip.start) / clip.duration
                if adapter.CLIP_KINDS[clip.kind].category == "morph":
                    return self._morph_at(layer, index, clip, alpha)
                active = self._activate(layer, index, clip)
                active.anim.interpolate(alpha)
                return self._to_world(active.drawn, layer, t)
        if not (start <= t < end):
            return None
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
        """Morphs are world-space hand-offs: A at clip start -> B at clip end."""
        key = (layer.id, clip.id)
        if key not in self._active:
            target_layer = self.project.layer(clip.to_layer)
            # _to_world may return shared buffers; the animation mutates its inputs.
            source = self._to_world(self._state_before(layer, index), layer, clip.start).copy()
            target = self._to_world(self._base_mobject(target_layer), target_layer, clip.end).copy()
            anim = adapter.make_animation(clip.kind, source, clip.ease, clip.params, target)
            anim.begin()
            self._active[key] = _Active(anim, anim.mobject)
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
        dst.pixel_array = src.pixel_array
        dst.set_opacity(1)


def _multiply_opacity(sub: m.Mobject, factor: float) -> None:
    if isinstance(sub, m.VMobject):
        for attr in ("fill_rgbas", "stroke_rgbas", "background_stroke_rgbas"):
            rgbas = getattr(sub, attr, None)
            if rgbas is not None and len(rgbas):
                rgbas[:, 3] *= factor
    elif isinstance(sub, m.ImageMobject):
        sub.set_opacity(factor)
