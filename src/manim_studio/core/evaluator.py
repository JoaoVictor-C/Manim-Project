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

A code layer (ADR 0019) is not evaluated at all: its frames were rendered by
real Manim into ``code_cache``, and ``t`` picks one (a placeholder until then).

An object with part layers (ADR 0012) is evaluated as one tree: its build holds
every part's glyphs, a checkpoint is the whole object after a set of finished
clips of the tree, a clip animates only its layer's glyphs, and each layer
draws the glyphs it owns through its transform composed with its ancestors'.

Edits are applied with ``invalidate`` / ``apply`` and an edit kind (ADR 0008,
ADR 0013): timing and transform edits keep every cache, clip and spec edits drop
the affected layers' caches (a whole tree for a layer in one).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import manim as m
import numpy as np

from ..logging_config import get_logger
from . import adapter, parts
from .code_cache import CodeCache, cache_key
from .code_frame import CodeFrame
from .edits import Edit, EditKind
from .schema import CODE_TYPES, Clip, Keyframe, Layer, Project, Spec, Transform2D, infer_lifetime

log = get_logger(__name__)

ClipKey = tuple[str, str]  # (layer id, clip id)
_MAX_TREE_STATES = 256  # per evaluator; timing drags create new finished-clip orders


@dataclass
class _Active:
    anim: m.Animation
    drawn: m.Mobject
    baked: tuple[Transform2D, Transform2D] | None = None  # morphs: world transforms at start/end
    leaves: list[m.Mobject] = field(default_factory=list)  # tree clips: the working copy's glyphs


@dataclass(frozen=True)
class _Tree:
    """An object with parts, resolved against its build (ADR 0012)."""

    spec: Spec  # what the root is built from (its spec plus marker spans)
    members: tuple[str, ...]  # root, then resolved parts (parents first)
    regions: dict[str, tuple[int, ...]]  # member -> glyph indices it animates
    owned: dict[str, tuple[int, ...]]  # member -> glyph indices it draws
    centres: dict[str, np.ndarray]  # part -> rest centre of its glyphs (its pivot)


class Evaluator:
    def __init__(self, project: Project, code_cache: CodeCache | None = None) -> None:
        self.project = project
        self._code_cache = code_cache
        self._base: dict[str, m.Mobject] = {}
        self._checkpoints: dict[tuple[str, str], m.Mobject] = {}
        self._active: dict[tuple, _Active] = {}
        self._proxies: dict[str, m.Mobject] = {}
        self._trees: dict[str, _Tree] = {}
        self._tree_states: dict[tuple[str, tuple[ClipKey, ...]], m.Mobject] = {}
        self._index()

    def _index(self) -> None:
        self._morph_into: dict[str, tuple[Layer, Clip]] = {}
        self._layers: dict[str, Layer] = {layer.id: layer for layer in self.project.layers}
        self._has_parts = {layer.parent_id for layer in self.project.layers if layer.parent_id}
        for layer in self.project.layers:
            for clip in layer.clips:
                if clip.to_layer:
                    self._morph_into[clip.to_layer] = (layer, clip)

    # -- public ----------------------------------------------------------------

    def missing_checkpoints(self) -> list[tuple[Layer, int | tuple[ClipKey, ...]]]:
        """Checkpoints not yet computed, in dependency order.

        An editor computes one per idle tick (each costs at most ~25 ms) so the
        first frame after a clip ends never stalls playback. Items are passed
        back to ``compute_checkpoint`` as they are.
        """
        missing: list[tuple[Layer, int | tuple[ClipKey, ...]]] = []
        for layer in self.project.layers:
            if layer.parent_id is not None:
                continue
            if layer.id in self._has_parts:
                for finished in self._tree_milestones(layer):
                    if finished and (layer.id, finished) not in self._tree_states:
                        missing.append((layer, finished))
                continue
            for index, clip in enumerate(layer.clips, start=1):
                if clip.info.category == "morph":
                    break  # the layer hands off to its morph target here
                if (layer.id, clip.id) not in self._checkpoints:
                    missing.append((layer, index))
        return missing

    def compute_checkpoint(self, layer: Layer, index: int | tuple[ClipKey, ...]) -> None:
        if isinstance(index, tuple):
            self._tree_state(layer, index)
        else:
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
          re-begun lazily when those transforms differ (``_morph_at``). In a
          tree, caches are keyed by the order of finished clips, so a retimed
          clip simply finds other entries.
        * ``clip`` / ``spec``: the layers' checkpoints, active clips and proxies,
          plus morph partners (a morph reads both ends) and whole trees; ``spec``
          also rebuilds the base object when what it is built from changed.
        """
        if kind in ("timing", "transform"):
            self.project = project
            self._index()
            log.debug("invalidate %s %s: caches kept", kind, layer_ids)
            return
        old_project = self.project
        old_partners = {
            layer.id: {c.to_layer for c in layer.clips if c.to_layer} for layer in old_project.layers
        }
        old_builds = {root.id: parts.build_spec(old_project, root.id) for root in old_project.roots()}
        self.project = project
        self._index()
        affected = set(layer_ids)
        for layer_id in layer_ids:
            affected |= old_partners.get(layer_id, set())
            if layer_id in self._morph_into:
                affected.add(self._morph_into[layer_id][0].id)
        for layer in project.layers:
            if any(c.to_layer in affected for c in layer.clips):
                affected.add(layer.id)
        for tree_project in (old_project, project):  # a layer in a tree affects the whole tree
            ids = {layer.id for layer in tree_project.layers}
            for layer_id in [i for i in affected if i in ids]:
                root = tree_project.root_of(layer_id)
                affected |= {root.id} | {d.id for d in tree_project.descendants(root.id)}
        for cache in (self._checkpoints, self._active):
            for key in [k for k in cache if k[0] in affected]:
                del cache[key]
        for key in [k for k in self._tree_states if k[0] in affected]:
            del self._tree_states[key]
        log.debug("invalidate %s -> affected %s", layer_ids, affected)
        new_builds = {root.id: parts.build_spec(project, root.id) for root in project.roots()}
        for layer_id in affected:
            self._proxies.pop(layer_id, None)
            self._trees.pop(layer_id, None)
            if old_builds.get(layer_id) != new_builds.get(layer_id):
                self._base.pop(layer_id, None)

    def frame(self, t: float) -> list[m.Mobject]:
        """World-space mobjects to draw at time ``t``, back to front.

        The returned mobjects are shared render buffers: draw them before the
        next call, and never mutate them.
        """
        return [mob for _, mob in self.frame_layers(t)]

    def frame_layers(self, t: float) -> list[tuple[str, m.Mobject]]:
        """``frame(t)`` with the id of the layer each mobject belongs to.

        A morph in progress is drawn by (and belongs to) its source layer; an
        object with parts yields itself (the glyphs no part owns), then its parts.
        The same buffer rules apply: use the result before the next evaluation
        and never keep it (canvas hit-testing and outlines, ADR 0016).
        """
        out: list[tuple[str, m.Mobject]] = []
        for layer in self.project.layers:
            if layer.parent_id is not None:
                continue  # drawn with its object
            if layer.id in self._has_parts:
                out.extend(self._tree_at(layer, t))
                continue
            mob = self._layer_at(layer, t)
            if mob is not None:
                out.append((layer.id, mob))
        return out

    # -- lifetime --------------------------------------------------------------

    def lifetime(self, layer: Layer) -> tuple[float, float]:
        morph_in = self._morph_into.get(layer.id)
        start, end = infer_lifetime(layer, morph_in[1] if morph_in else None)
        if layer.parent_id is not None:  # clamped to the parent's (ADR 0012)
            parent_start, parent_end = self.lifetime(self._layers[layer.parent_id])
            start, end = max(start, parent_start), min(end, parent_end)
        return start, end

    # -- local state (clips) ---------------------------------------------------

    def _base_mobject(self, layer: Layer) -> m.Mobject:
        if layer.id not in self._base:
            spec = self._tree(layer).spec if layer.id in self._has_parts else layer.spec
            self._base[layer.id] = adapter.build_mobject(spec)
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
        if layer.spec.type in CODE_TYPES:
            return self._code_at(layer, t, start)
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

    # -- code layers (ADR 0019) ------------------------------------------------

    @property
    def code_cache(self) -> CodeCache:
        if self._code_cache is None:
            self._code_cache = CodeCache(adapter.cache_dir() / "code")
        return self._code_cache

    def code_key(self, layer: Layer) -> str:
        return code_key(self.project, layer)

    def _code_at(self, layer: Layer, t: float, start: float) -> m.Mobject | None:
        """The cached frame at ``t`` (the last one held), or a placeholder before it is rendered."""
        clip = self.code_cache.open(self.code_key(layer))
        if clip is None:
            return self._to_world(_code_placeholder(), layer, t)
        crop = clip.crop(math.floor((t - start) * clip.fps + 1e-6))
        if crop is None:
            return None  # an empty frame: nothing drawn
        tr = self.transform_at(layer, t)
        a, b = _affine(tr)
        return CodeFrame(crop, self.project.canvas, a, b, tr.opacity)

    # -- objects with parts (ADR 0012) -----------------------------------------

    def _tree(self, root: Layer) -> _Tree:
        tree = self._trees.get(root.id)
        if tree is not None:
            return tree
        resolution = parts.resolve(self.project, root.id)
        spec = parts.build_spec(self.project, root.id, resolution)
        if root.id not in self._base:
            self._base[root.id] = adapter.build_mobject(spec)
        leaves = self._base[root.id].family_members_with_points()
        regions = {root.id: tuple(range(len(leaves)))}
        if resolution.order:
            regions.update(zip(resolution.order, adapter.part_regions(spec), strict=True))
        members = (root.id, *(d.id for d in self.project.descendants(root.id) if d.id in regions))
        owned = {}
        for member in members:
            taken = {
                i for other in members if self._layers[other].parent_id == member for i in regions[other]
            }
            owned[member] = tuple(i for i in regions[member] if i not in taken)
        centres = {
            member: m.VGroup(*(leaves[i] for i in regions[member])).get_center()
            if regions[member]
            else np.zeros(3)
            for member in members[1:]
        }
        tree = _Tree(spec, members, regions, owned, centres)
        self._trees[root.id] = tree
        return tree

    def _tree_clips(self, root: Layer, tree: _Tree) -> list[tuple[Layer, Clip]]:
        """Clips of the tree's layers that animate glyphs, by start time (then tree order)."""
        order = {member: i for i, member in enumerate(tree.members)}
        clips = [
            (self._layers[member], clip)
            for member in tree.members
            if tree.regions[member]
            for clip in self._layers[member].clips
        ]
        return sorted(clips, key=lambda lc: (lc[1].start, order[lc[0].id]))

    def _tree_milestones(self, root: Layer) -> list[tuple[ClipKey, ...]]:
        """The finished-clip orders playback reaches (at each clip end and clip start)."""
        clips = self._tree_clips(root, self._tree(root))
        times = sorted({c.end for _, c in clips} | {c.start for _, c in clips})
        out = []
        for t in times:
            finished = tuple((layer.id, c.id) for layer, c in clips if c.end <= t)
            if finished not in out:
                out.append(finished)
        return out

    def _tree_state(self, root: Layer, finished: tuple[ClipKey, ...]) -> m.Mobject:
        """The whole object after ``finished`` clips, applied in that order (never mutate it)."""
        if not finished:
            return self._base_mobject(root)
        key = (root.id, finished)
        if key not in self._tree_states:
            work = self._tree_state(root, finished[:-1]).copy()
            layer_id, clip_id = finished[-1]
            layer = self._layers[layer_id]
            clip = next(c for c in layer.clips if c.id == clip_id)
            anim = self._tree_animation(root, work, layer, clip)
            anim.begin()
            anim.finish()
            if len(self._tree_states) >= _MAX_TREE_STATES:
                self._tree_states.pop(next(iter(self._tree_states)))
            self._tree_states[key] = work
        return self._tree_states[key]

    def _tree_animation(self, root: Layer, work: m.Mobject, layer: Layer, clip: Clip) -> m.Animation:
        """``clip`` acting on ``layer``'s glyphs inside ``work``, a copy of the whole object."""
        if layer.id == root.id:
            target = work  # the object itself: identical to animating it without parts
        else:
            leaves = work.family_members_with_points()
            target = m.VGroup(*(leaves[i] for i in self._tree(root).regions[layer.id]))
        return adapter.make_animation(clip.kind, target, clip.ease, clip.params)

    def _tree_at(self, root: Layer, t: float) -> list[tuple[str, m.Mobject]]:
        start, end = self.lifetime(root)
        if not (start <= t < end):
            return []
        tree = self._tree(root)
        clips = self._tree_clips(root, tree)
        finished = tuple((layer.id, c.id) for layer, c in clips if c.end <= t)
        source = list(self._tree_state(root, finished).family_members_with_points())
        for layer, clip in clips:
            if not (clip.start <= t < clip.end):
                continue
            before = tuple((other.id, c.id) for other, c in clips if c.end <= clip.start)
            key = (layer.id, clip.id, before)
            active = self._active.get(key)
            if active is None:
                work = self._tree_state(root, before).copy()
                anim = self._tree_animation(root, work, layer, clip)
                anim.begin()
                active = _Active(anim, work, leaves=work.family_members_with_points())
                self._active[key] = active
            active.anim.interpolate((t - clip.start) / clip.duration)
            for i in tree.regions[layer.id]:
                source[i] = active.leaves[i]
        out = []
        for member in tree.members:
            layer = self._layers[member]
            glyphs = tree.owned[member]
            if not glyphs:
                continue
            if member != root.id:
                member_start, member_end = self.lifetime(layer)
                if not (member_start <= t < member_end):
                    continue
            local = m.VGroup(*(source[i] for i in glyphs))
            out.append((member, self._project_local(local, member, *self._member_affine(tree, layer, t))))
        return out

    def _member_affine(self, tree: _Tree, layer: Layer, t: float) -> tuple[np.ndarray, np.ndarray, float]:
        """World affine (A, b) and opacity of a tree member: ancestors' transforms, then its own."""
        chain = [layer]
        while chain[-1].parent_id is not None:
            chain.append(self._layers[chain[-1].parent_id])
        a, b, opacity = np.eye(2), np.zeros(2), 1.0
        for node in reversed(chain):  # root first
            tr = self.transform_at(node, t)
            a_node, b_node = _affine(tr, tree.centres.get(node.id))
            a, b = a @ a_node, a @ b_node + b
            opacity *= tr.opacity
        return a, b, opacity

    # -- layer transform (keyframes) -------------------------------------------

    def transform_at(self, layer: Layer, t: float) -> Transform2D:
        return layer_transform(layer, t)

    def layer_frame(self, layer: Layer, t: float) -> tuple[np.ndarray, float, np.ndarray]:
        """Where a layer's gizmo lives: its pivot and rotation in world space, and the
        map from a world-space move to a change of its own ``position``.

        An object pivots on its position. A part pivots on its rest centre moved by
        its own position, carried by its ancestors' transforms (ADR 0012).
        """
        tr = self.transform_at(layer, t)
        if layer.parent_id is None:
            return np.array(tr.position, dtype=float), tr.rotation, np.eye(2)
        root = self.project.root_of(layer.id)
        tree = self._tree(root)
        parent = self._layers[layer.parent_id]
        a, b, _ = self._member_affine(tree, parent, t)
        centre = tree.centres.get(layer.id, np.zeros(3))[:2]
        anchor = a @ (centre + np.array(tr.position, dtype=float)) + b
        ancestors = self.project.ancestors(layer.id)
        rotation = tr.rotation + sum(self.transform_at(x, t).rotation for x in ancestors)
        return anchor, rotation, np.linalg.pinv(a)  # pinv: a parent scaled to 0 must not raise

    def _to_world(self, local: m.Mobject, layer: Layer, t: float) -> m.Mobject:
        """Apply the keyframed layer transform without touching ``local``."""
        tr = self.transform_at(layer, t)
        if tr == _IDENTITY:
            return local
        a, b = _affine(tr)
        return self._project_local(local, layer.id, a, b, tr.opacity)

    def _project_local(self, local: m.Mobject, key: str, a: np.ndarray, b: np.ndarray, opacity: float):
        """``local`` mapped by ``p -> a p + b`` with ``opacity`` applied, on a scratch proxy.

        The proxy (one per layer) is fully overwritten on every call, so it is
        only valid until the next ``frame()``.
        """
        if opacity == 1 and np.array_equal(a, _EYE) and not b.any():
            return local
        proxy = self._proxies.get(key)
        if proxy is None or not _same_structure(proxy, local):
            proxy = local.copy()
            self._proxies[key] = proxy
        matrix = np.array([[a[0, 0], a[0, 1], 0.0], [a[1, 0], a[1, 1], 0.0], [0.0, 0.0, 1.0]])
        offset = np.array([b[0], b[1], 0.0])
        for dst, src in zip(proxy.get_family(), local.get_family(), strict=True):
            _copy_drawable_state(dst, src)
            if len(src.points):
                dst.points = src.points @ matrix.T + offset
            if opacity != 1:
                _multiply_opacity(dst, opacity)
        return proxy


def code_key(project: Project, layer: Layer) -> str:
    """The cache entry a code layer's frames live under (its code + what the render depends on)."""
    canvas = project.canvas
    code = str(layer.spec.params.get("code", ""))
    return cache_key(
        code, canvas.width_px, canvas.height_px, canvas.fps, canvas.frame_height, adapter.MANIM_VERSION
    )


def layer_transform(layer: Layer, t: float) -> Transform2D:
    """The layer's transform at ``t``: each property from its keyframes, else the base."""
    base = layer.base
    values = {
        name: _sample(layer.tracks.get(name), t, getattr(base, name))
        for name in ("position", "scale", "rotation", "opacity")
    }
    return Transform2D(**values)


def _affine(tr: Transform2D, pivot: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """``p -> a p + b``: scale and rotate about ``pivot`` (the origin for objects), then move."""
    angle = math.radians(tr.rotation)
    c, s = math.cos(angle) * tr.scale, math.sin(angle) * tr.scale
    a = np.array([[c, -s], [s, c]])
    b = np.array(tr.position, dtype=float)
    if pivot is not None:
        b = b + pivot[:2] - a @ pivot[:2]
    return a, b


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
_EYE = np.eye(2)
_PLACEHOLDER: list[m.Mobject] = []


def _code_placeholder() -> m.Mobject:
    """A dashed box standing in for a code layer whose frames are not rendered (yet)."""
    if not _PLACEHOLDER:
        box = m.DashedVMobject(m.Rectangle(width=4.0, height=2.25), num_dashes=48)
        box.set_stroke(m.ManimColor("#94a3b8"), width=3, opacity=0.9)
        _PLACEHOLDER.append(box)
    return _PLACEHOLDER[0]


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
