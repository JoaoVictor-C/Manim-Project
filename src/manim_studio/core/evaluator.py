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

An image or SVG layer (ADR 0027) is built from its file as it was when the
layer was first drawn; ``check_media`` notices files changed on disk since and
rebuilds those layers. A file that cannot be drawn shows a dashed placeholder.

A code layer (ADR 0019) is not evaluated at all: its frames were rendered by
real Manim into ``code_cache``, and ``t`` picks one (a placeholder until then).

A simulated layer (ADR 0033) - a traced path or a plugin simulation - has no
clips: it advances once per canvas frame. Its state at a frame is replayed from
the nearest kept state (a simulation keeps one every 30 steps, a trace keeps
every point), keyed by everything it is computed from, so edits need no
invalidation. Sampling a trace evaluates its target at earlier times, which
reuses the target's drawing buffers; it always ends at the frame's own time, so
a target drawn before its trace in the same frame is left in that frame's state.

An object with part layers (ADR 0012) or child objects (ADR 0029) is evaluated
as one tree: its build holds every member's glyphs, a checkpoint is the whole
object after a set of finished clips of the tree, a clip animates only its
layer's glyphs (the root's: all of them), and each layer draws the glyphs it
owns through its transform composed with its ancestors'. A child object can
morph: while it does, the hand-off draws instead of its glyphs.

Edits are applied with ``invalidate`` / ``apply`` and an edit kind (ADR 0008,
ADR 0013): timing and transform edits keep every cache, clip and spec edits drop
the affected layers' caches (a whole tree for a layer in one).
"""

from __future__ import annotations

import copy
import itertools
import math
from dataclasses import dataclass, field

import manim as m
import numpy as np

from .. import plugins
from ..logging_config import get_logger
from . import adapter, motion_paths, parts, subtitles
from .code_cache import CodeCache, cache_key
from .code_frame import CodeFrame
from .edits import Edit, EditKind
from .frame_cache import frame_index, on_grid
from .schema import (
    CODE_TYPES,
    CONNECTOR_TYPES,
    MEDIA_TYPES,
    TRACE_TYPES,
    Clip,
    Keyframe,
    Layer,
    Project,
    Spec,
    Transform2D,
    infer_lifetime,
)

log = get_logger(__name__)

ClipKey = tuple[str, str]  # (layer id, clip id)
_MAX_TREE_STATES = 256  # per evaluator; timing drags create new finished-clip orders


@dataclass
class _Active:
    anim: m.Animation
    drawn: m.Mobject
    baked: tuple[Transform2D, Transform2D] | None = None  # morphs: world transforms at start/end
    leaves: list[m.Mobject] = field(default_factory=list)  # tree clips: the working copy's glyphs


@dataclass
class _Run:
    """A simulation's replay (ADR 0033): kept states by step, and the latest one."""

    key: tuple
    kept: dict[int, object]
    latest: tuple[int, object]
    drawn: tuple[int, m.Mobject] | None = None


@dataclass
class _Trace:
    """A traced path's points by grid frame from its first one (None: the target was not drawn)."""

    key: tuple
    points: list[np.ndarray | None]
    drawn: tuple[object, m.Mobject] | None = None


@dataclass(frozen=True)
class _Tree:
    """An object with parts or child objects, resolved against its build (ADR 0012, 0029)."""

    spec: Spec  # what the root is built from (its spec plus marker spans)
    members: tuple[str, ...]  # root, then resolved parts (parents first) or child objects
    regions: dict[str, tuple[int, ...]]  # member -> glyph indices it animates
    owned: dict[str, tuple[int, ...]]  # member -> glyph indices it draws
    centres: dict[str, np.ndarray]  # part -> rest centre of its glyphs (its pivot); none for children
    drawn: dict[str, tuple[int, ...]] | None = None  # owned glyphs not inside another owned glyph

    def draws(self, member: str) -> tuple[int, ...]:
        """The glyphs to put in a member's drawn group: an axis line carries its ticks, so the ticks
        are not added again (a morph aligns the group's structure, ADR 0029)."""
        return self.owned[member] if self.drawn is None else self.drawn[member]


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
        self._media: dict[str, str] = {}  # media layer -> the file signature its build is from
        self._runs: dict[str, _Run] = {}  # simulations (ADR 0033)
        self._traces: dict[str, _Trace] = {}  # traced paths (ADR 0033)
        self._connectors: dict[str, tuple[object, m.Mobject]] = {}  # the last drawing of each (ADR 0036)
        self._sim_errors: dict[str, str] = {}  # simulations that failed while stepping
        self._index()

    def _index(self) -> None:
        self._morph_into: dict[str, tuple[Layer, Clip]] = {}
        self._layers: dict[str, Layer] = {layer.id: layer for layer in self.project.layers}
        # Roots evaluated as trees: with parts (ADR 0012) or child objects (ADR 0029).
        self._trees_of = {
            self.project.root_of(layer.id).id for layer in self.project.layers if layer.parent_id is not None
        }
        for layer in self.project.layers:
            for clip in layer.clips:
                if clip.to_layer:
                    self._morph_into[clip.to_layer] = (layer, clip)
        self._simulated = {  # drawn frame by frame (ADR 0033)
            layer.id
            for layer in self.project.layers
            if layer.spec is not None
            and layer.parent_id is None
            and (layer.spec.type in TRACE_TYPES or layer.spec.type in plugins.SIMULATIONS)
        }
        self._signatures: dict[str, str] = {}  # what a traced layer is evaluated from, per project

    # -- public ----------------------------------------------------------------

    def missing_checkpoints(self) -> list[tuple[Layer, int | tuple[ClipKey, ...]]]:
        """Checkpoints not yet computed, in dependency order.

        An editor computes one per idle tick (each costs at most ~25 ms) so the
        first frame after a clip ends never stalls playback. Items are passed
        back to ``compute_checkpoint`` as they are.
        """
        missing: list[tuple[Layer, int | tuple[ClipKey, ...]]] = []
        for layer in self.project.layers:
            if layer.is_part:
                continue
            if layer.id in self._trees_of:
                for finished in self._tree_milestones(layer):
                    if finished and self._tree_key(layer, finished) not in self._tree_states:
                        missing.append((layer, finished))
                continue
            for index, clip in enumerate(layer.clips, start=1):
                if clip.info.category == "morph":
                    break  # the layer hands off to its morph target here
                if (layer.id, clip.id, self._path_sigs(layer, index)) not in self._checkpoints:
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
        old_builds = _builds(old_project)
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
        new_builds = _builds(project)
        for layer_id in affected:
            self._proxies.pop(layer_id, None)
            self._trees.pop(layer_id, None)
            if old_builds.get(layer_id) != new_builds.get(layer_id):
                self._base.pop(layer_id, None)
                self._media.pop(layer_id, None)

    def check_media(self) -> set[str]:
        """Re-read the media files on disk (ADR 0027): layers whose file changed since they
        were built are rebuilt, like a spec edit. Returns their ids."""
        changed = {
            layer.id
            for layer in self.project.layers
            if layer.id in self._media and adapter.media_signature(layer.spec) != self._media[layer.id]
        }
        if changed:
            self.invalidate(self.project, changed, "spec")
            for layer_id in changed:  # the spec is the same: drop the builds explicitly
                self._base.pop(layer_id, None)
                self._media.pop(layer_id, None)
            log.info("media changed on disk: %s", sorted(changed))
        return changed

    def build_errors(self) -> dict[str, str]:
        """Layers that show a placeholder, and why: unreadable media (ADR 0027), a failing or
        missing plugin (ADR 0032)."""
        out = {}
        for layer in self.project.layers:
            if layer.spec is None or layer.parent_id is not None:
                continue
            problem = adapter.build_problem(layer.spec, self._media_signature(layer))
            problem = problem or self._sim_errors.get(layer.id)  # a step failed later (ADR 0033)
            if problem is not None:
                out[layer.id] = problem
        return out

    def _media_signature(self, layer: Layer) -> str | None:
        """The file signature this layer is drawn from (stat-ed once, then kept until
        ``check_media`` or an edit of the layer); None for non-media layers."""
        if layer.spec is None or layer.spec.type not in MEDIA_TYPES:  # parts have no spec
            return None
        if layer.id not in self._media:
            self._media[layer.id] = adapter.media_signature(layer.spec)
        return self._media[layer.id]

    def frame(self, t: float) -> list[m.Mobject]:
        """World-space mobjects to draw at time ``t``, back to front.

        The returned mobjects are shared render buffers: draw them before the
        next call, and never mutate them.
        """
        return [*(mob for _, mob in self.frame_layers(t)), *self.overlay(t)]

    def overlay(self, t: float) -> list[m.Mobject]:
        """What is drawn over every layer at ``t``: the subtitle, when burned in (ADR 0035).
        Same buffer rules as ``frame``."""
        style = self.project.subtitle_style
        cue = subtitles.visible(self.project, t) if style.burn_in else None
        built = adapter.subtitle_mobject(cue.text, style) if cue is not None else None
        if built is None:
            return []
        alpha = subtitles.opacity(cue, style, t)
        return [self._project_local(built, "subtitle", _EYE, np.zeros(2), alpha)]

    def frame_layers(self, t: float) -> list[tuple[str, m.Mobject]]:
        """``frame(t)`` with the id of the layer each mobject belongs to.

        A morph in progress is drawn by (and belongs to) its source layer; an
        object with parts yields itself (the glyphs no part owns), then its parts.
        The same buffer rules apply: use the result before the next evaluation
        and never keep it (canvas hit-testing and outlines, ADR 0016).
        """
        out: list[tuple[str, m.Mobject]] = []
        for layer in self.project.layers:
            if layer.parent_id is None:  # parts and child objects are drawn with their object
                out.extend(self._object_at(layer, t))
        return out

    def object_frame(self, layer_id: str, t: float) -> list[tuple[str, m.Mobject]]:
        """The pairs ``frame_layers(t)`` yields for the object ``layer_id`` belongs to (its
        root, parts and child objects), evaluating nothing else: the selection outline over
        a cached frame (ADR 0028). The same buffer rules apply."""
        return self._object_at(self.project.root_of(layer_id), t)

    def _object_at(self, root: Layer, t: float) -> list[tuple[str, m.Mobject]]:
        if root.id in self._trees_of:  # its parts or child objects too (ADR 0012, 0029)
            return self._tree_at(root, t)
        mob = self._layer_at(root, t)
        return [(root.id, mob)] if mob is not None else []

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
        if layer.id in self._trees_of:
            self._tree(layer)  # builds the whole object
        if layer.id not in self._base:
            if layer.is_child:  # a child object alone, built against its parent (a path, ADR 0025)
                parent = self._layers[layer.parent_id].spec
                built = adapter.build_child(parent, layer.spec, self.project.referenced_graphs(layer))
            else:
                built = adapter.build_mobject(layer.spec, self._media_signature(layer))
            self._base[layer.id] = built
        return self._base[layer.id]

    def _state_before(self, layer: Layer, index: int) -> m.Mobject:
        """Local state right before clip ``index`` starts (never mutate it)."""
        if index == 0:
            return self._base_mobject(layer)
        prev = layer.clips[index - 1]
        key = (layer.id, prev.id, self._path_sigs(layer, index))  # a moved path re-runs (ADR 0025)
        if key not in self._checkpoints:
            working = self._state_before(layer, index - 1).copy()
            anim = adapter.make_animation(
                prev.kind, working, prev.ease, prev.params, self._path_target(layer, prev)
            )
            anim.begin()
            anim.finish()
            # An overlay (Flash lines, a Circumscribe frame) leaves the object as it was (ADR 0022).
            self._checkpoints[key] = working if prev.info.overlay else anim.mobject
        return self._checkpoints[key]

    def _layer_at(self, layer: Layer, t: float) -> m.Mobject | None:
        start, end = self.lifetime(layer)
        if not (start <= t < end):  # the lifetime gates everything, clips included
            return None
        if layer.spec.type in CODE_TYPES:
            return self._code_at(layer, t, start)
        if layer.id in self._simulated:  # no clips: drawn frame by frame (ADR 0033)
            local = (
                self._trace_drawing(layer, t)
                if layer.spec.type in TRACE_TYPES
                else self._sim_drawing(layer, t)
            )
            return self._to_world(local, layer, t)
        if layer.spec.type in CONNECTOR_TYPES:  # no clips: drawn between its layers (ADR 0036)
            return self._to_world(self._connector_drawing(layer, t), layer, t)
        morph = self._member_morph(layer, t)
        if morph is not None:
            return morph
        return self._to_world(self._clip_state_at(layer, t), layer, t)

    def _clip_state_at(self, layer: Layer, t: float) -> m.Mobject:
        """A plain object's local drawing at ``t`` (clips applied, not its transform), outside morphs."""
        for index, clip in enumerate(layer.clips):
            if clip.start <= t < clip.end:
                active = self._activate(layer, index, clip)
                active.anim.interpolate((t - clip.start) / clip.duration)
                return active.drawn
        return self._state_before(layer, sum(1 for clip in layer.clips if clip.end <= t))

    def _alive(self, layer: Layer, t: float) -> bool:
        start, end = self.lifetime(layer)
        return start <= t < end

    # -- simulated layers (ADR 0033) -------------------------------------------

    def _first_frame(self, layer: Layer) -> int:
        """The grid frame a simulated layer starts on: the first at or after its lifetime start."""
        return math.ceil(self.lifetime(layer)[0] * self.project.canvas.fps - 1e-6)

    def _sim_state(self, layer: Layer, steps: int) -> object:
        """A simulation's state after ``steps`` steps, replayed from the nearest kept state."""
        sim = plugins.SIMULATIONS[layer.spec.type]
        fps = self.project.canvas.fps
        params = adapter.plugin_params(layer.spec, sim.params)
        key = (layer.spec.model_dump_json(), fps, self._first_frame(layer))
        run = self._runs.get(layer.id)
        if run is None or run.key != key:
            state = sim.start(dict(params))
            run = _Run(key, {0: state}, (0, state))
            self._runs[layer.id] = run
        base = max(i for i in run.kept if i <= steps)
        if run.latest[0] <= steps and run.latest[0] > base:
            base, state = run.latest
        else:
            state = run.kept[base]
        for i in range(base + 1, steps + 1):
            state = sim.step(copy.deepcopy(state), 1 / fps, dict(params))  # steps may mutate their input
            if i % adapter.SIMULATION_CHECKPOINT == 0:
                run.kept[i] = state
        run.latest = (steps, state)
        return state

    def _sim_steps(self, layer: Layer, t: float) -> int:
        return max(0, frame_index(t, self.project.canvas.fps) - self._first_frame(layer))

    def _sim_drawing(self, layer: Layer, t: float) -> m.Mobject:
        """A simulation's drawing at ``t``: its state on the last grid frame, or the placeholder."""
        if adapter.simulation_problem(layer.spec) is not None or layer.id in self._sim_errors:
            return self._base_placeholder(layer)
        steps = self._sim_steps(layer, t)
        try:
            state = self._sim_state(layer, steps)
            run = self._runs[layer.id]
            if run.drawn is None or run.drawn[0] != steps:
                sim = plugins.SIMULATIONS[layer.spec.type]
                params = adapter.plugin_params(layer.spec, sim.params)
                drawing = sim.draw(copy.deepcopy(state), dict(params))
                run.drawn = (steps, adapter.simulation_drawing(layer.spec, drawing))
        except Exception as exc:  # a broken plugin must never break a frame (ADR 0032)
            log.warning("simulation %s failed: %s", layer.id, exc)
            self._sim_errors[layer.id] = (
                f"the {layer.spec.type} simulation failed: {type(exc).__name__}: {exc}"
            )
            return self._base_placeholder(layer)
        return run.drawn[1]

    def _base_placeholder(self, layer: Layer) -> m.Mobject:
        key = f"placeholder:{layer.id}"
        if key not in self._base:
            self._base[key] = adapter.build_mobject(Spec(type="?"))  # the dashed placeholder (ADR 0027)
        return self._base[key]

    def _sim_point(self, layer: Layer, t: float) -> np.ndarray:
        """What a trace follows on a simulation, in its units: ``point(state)``, else the drawing's centre."""
        sim = plugins.SIMULATIONS[layer.spec.type]
        if sim.point is None or adapter.simulation_problem(layer.spec) is not None:
            return self._sim_drawing(layer, t).get_center()[:2]
        try:
            state = self._sim_state(layer, self._sim_steps(layer, t))
            params = adapter.plugin_params(layer.spec, sim.params)
            return np.array(sim.point(copy.deepcopy(state), dict(params)), dtype=float)[:2]
        except Exception as exc:
            self._sim_errors[layer.id] = (
                f"the {layer.spec.type} simulation failed: {type(exc).__name__}: {exc}"
            )
            return self._base_placeholder(layer).get_center()[:2]

    def _traced_point(self, target: Layer, t: float, offset: np.ndarray) -> np.ndarray | None:
        """Where a trace of ``target`` is at ``t`` in world units, or None when it is not drawn."""
        root = self.project.root_of(target.id)
        if root.id in self._trees_of:  # a part or child object, or an object that has them
            drawn = dict(self._tree_at(root, t)).get(target.id)
            if drawn is None or not drawn.family_members_with_points():
                return None
            a = (
                self._member_affine(self._tree(root), target, t)[0]
                if target.id in self._tree(root).members
                else np.eye(2)
            )
            return drawn.get_center()[:2] + a @ offset
        if not self._alive(target, t):
            return None
        a, b = self._world_affine(target, t)
        if target.id in self._simulated:
            return a @ (self._sim_point(target, t) + offset) + b
        morph = self._member_morph(target, t)
        if morph is not None:  # handed off: the morph's centre
            return morph.get_center()[:2] + a @ offset
        local = self._clip_state_at(target, t)
        if not local.family_members_with_points():
            return None
        return a @ (local.get_center()[:2] + offset) + b

    # -- connectors (ADR 0036) --------------------------------------------------

    def _connector_end(
        self, target: Layer, t: float, offset: np.ndarray
    ) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray]] | None:
        """Where a connector meets ``target`` at ``t`` and the box of its drawing (world units), or
        None when it is not drawn. The point is the box's centre moved by ``offset`` (turned and
        scaled with the layer); a simulation's is its traced point (ADR 0033)."""
        root = self.project.root_of(target.id)
        drawn = [mob for owner, mob in self._object_at(root, t) if target.id in (root.id, owner)]
        points = [sub.points[:, :2] for mob in drawn for sub in mob.family_members_with_points()]
        if not points:
            return None
        every = np.vstack(points)
        box = (every.min(axis=0), every.max(axis=0))
        if target.id in self._simulated:
            point = self._traced_point(target, t, offset)
            return (point, box) if point is not None else None
        if root.id in self._trees_of and target.id != root.id:
            a = self._member_affine(self._tree(root), target, t)[0]
        else:
            a = self._world_affine(target, t)[0]
        return (box[0] + box[1]) / 2 + a @ offset, box

    def _connector_drawing(self, layer: Layer, t: float) -> m.Mobject:
        """A connector at ``t`` (world units): a line or arrow between its layers' points, ending at
        their boxes (``edges``) or at the points, shortened by its gap; nothing while either layer
        is not drawn. The last drawing is kept while its ends and spec stay the same."""
        spec = layer.spec
        ends = []
        for name in ("source", "target"):
            param = next(p for p in adapter.MOBJECT_PARAMS["Connector"] if p.name == f"{name}_offset")
            offset = np.array(adapter.param_value(spec, param)[:2], dtype=float)
            ends.append(self._connector_end(self._layers[spec.params[name]], t, offset))
        line = None
        if ends[0] is not None and ends[1] is not None:
            (p, p_box), (q, q_box) = ends
            line = adapter.connector_ends(p, q, p_box, q_box, spec.params.get("ends", "edges"))
        token = (spec.model_dump_json(), None if line is None else tuple(np.concatenate(line)))
        kept = self._connectors.get(layer.id)
        if kept is None or kept[0] != token:
            drawing = m.VMobject() if line is None else adapter.connector_mobject(*line, spec)
            kept = (token, drawing)
            self._connectors[layer.id] = kept
        return kept[1]

    def _signature(self, layer_id: str) -> str:
        """Everything layer ``layer_id`` is evaluated from: its object, morph partners and path
        layers, transitively (a trace of it is re-sampled when any of them changes)."""
        if layer_id not in self._signatures:
            seen: set[str] = set()
            todo = [layer_id]
            while todo:
                current = todo.pop()
                if current in seen or current not in self._layers:
                    continue
                seen.add(current)
                root = self.project.root_of(current)
                tree = [root, *self.project.descendants(root.id)]
                todo.extend(x.id for x in tree)
                for x in tree:
                    for clip in x.clips:
                        todo.extend(i for i in (clip.to_layer, clip.params.get("path")) if isinstance(i, str))
                    if x.id in self._morph_into:
                        todo.append(self._morph_into[x.id][0].id)
            self._signatures[layer_id] = "|".join(
                self._layers[i].model_dump_json() + f"@{self._media_signature(self._layers[i])}"
                for i in sorted(seen)
            )
        return self._signatures[layer_id]

    def _trace_points(self, layer: Layer, last: int) -> list[np.ndarray | None]:
        """A trace's points on grid frames ``first..last`` (sampled once, then kept)."""
        fps = self.project.canvas.fps
        target_id = layer.spec.params["target"]
        first = self._first_frame(layer)
        key = (layer.spec.model_dump_json(), fps, first, self._signature(target_id))
        trace = self._traces.get(layer.id)
        if trace is None or trace.key != key:
            trace = _Trace(key, [])
            self._traces[layer.id] = trace
        offset = np.array(
            adapter.param_value(layer.spec, adapter.MOBJECT_PARAMS["TracedPath"][1])[:2], dtype=float
        )
        target = self._layers[target_id]
        for index in range(first + len(trace.points), last + 1):
            trace.points.append(self._traced_point(target, index / fps, offset))
        return trace.points[: max(0, last - first + 1)]

    def _trace_drawing(self, layer: Layer, t: float) -> m.Mobject:
        """A traced path at ``t`` (world units): its points on the grid frames so far (the last
        ``dissipate`` seconds of them), and the live point between frames."""
        fps = self.project.canvas.fps
        last = frame_index(t, fps)
        points = self._trace_points(layer, last)
        first = self._first_frame(layer)
        dissipate = float(layer.spec.params.get("dissipate") or 0.0)
        if dissipate > 0:
            points = points[max(0, len(points) - 1 - round(dissipate * fps)) :]
        live = None
        if not on_grid(t, fps) or last < first:
            target = self._layers[layer.spec.params["target"]]
            offset = np.array(
                adapter.param_value(layer.spec, adapter.MOBJECT_PARAMS["TracedPath"][1])[:2], dtype=float
            )
            live = self._traced_point(target, t, offset)
        if last < first:
            points = []
        trace = self._traces[layer.id]
        token = (trace.key, last, None if live is None else tuple(live))
        if trace.drawn is None or trace.drawn[0] != token:
            runs: list[list[np.ndarray]] = [[]]
            for point in [*points, live] if live is not None else points:
                if point is None:
                    runs.append([])
                else:
                    runs[-1].append(np.array([point[0], point[1], 0.0]))
            trace.drawn = (token, adapter.trace_mobject([r for r in runs if r], layer.spec.style))
        return trace.drawn[1]

    def _activate(self, layer: Layer, index: int, clip: Clip) -> _Active:
        key = (layer.id, clip.id, self._path_sigs(layer, index + 1))
        if key not in self._active:
            working = self._state_before(layer, index).copy()
            anim = adapter.make_animation(
                clip.kind, working, clip.ease, clip.params, self._path_target(layer, clip)
            )
            anim.begin()
            drawn = m.Group(working, anim.mobject) if clip.info.overlay else anim.mobject  # ADR 0022
            self._active[key] = _Active(anim, drawn)
        return self._active[key]

    def _morph_at(self, layer: Layer, index: int, clip: Clip, alpha: float) -> m.Mobject:
        """Morphs are world-space hand-offs: A at clip start -> B at clip end (ADR 0005).

        Either end may be an object with parts, drawn as its whole tree (ADR 0020).
        The begun animation bakes both ends, so it is reused only while their
        signatures are unchanged (ADR 0013): moving a morph whose partners are
        static or settled costs no new ``begin()``.
        """
        key = (layer.id, clip.id)
        target_layer = self._layers[clip.to_layer]
        baked = (self._end_signature(layer, clip.start), self._end_signature(target_layer, clip.end))
        cached = self._active.get(key)
        if cached is None or cached.baked != baked:
            source = self._end_groups(layer, clip.start, index)
            target = self._end_groups(target_layer, clip.end, None)
            if clip.kind == "TransformMatchingTex":
                source_mob, target_mob = adapter.keyed_pieces(source, target)
            else:
                source_mob, target_mob = _compose(source), _compose(target)
            anim = adapter.make_animation(clip.kind, source_mob, clip.ease, clip.params, target_mob)
            anim.begin()
            self._active[key] = _Active(anim, anim.mobject, baked)
        active = self._active[key]
        active.anim.interpolate(alpha)
        return active.drawn

    def _end_groups(self, layer: Layer, t: float, index: int | None) -> list[tuple[str | None, m.Mobject]]:
        """One end of a morph in world space, as ``(part TeX or None, glyphs)`` copies.

        An object with parts gives one group per drawn member; any other layer
        one group: its state before clip ``index`` (the source) or its base
        object (a target, which appears when the morph ends). Copies: drawings
        are shared buffers and the animation mutates its inputs.
        """
        if layer.id in self._trees_of:
            groups = []
            for member, mob in self._tree_members_at(layer, t, morphs=False):
                part = self._layers[member].part
                groups.append((part.tex if part is not None else None, mob.copy()))
            return groups
        if layer.is_child and not layer.is_part:  # a child object as its tree draws it (ADR 0029)
            root = self.project.root_of(layer.id)
            members = self._tree_members_at(root, t, morphs=False)
            drawn = [mob.copy() for member, mob in members if member == layer.id]
            return [(None, drawn[0] if drawn else m.VGroup())]
        local = self._state_before(layer, index) if index is not None else self._base_mobject(layer)
        return [(None, self._to_world(local, layer, t).copy())]

    def _end_signature(self, layer: Layer, t: float):
        """What one end of a morph depends on besides edits that drop caches anyway."""
        if layer.is_child and not layer.is_part:  # drawn by its tree: depends on all of it (ADR 0029)
            layer = self.project.root_of(layer.id)
        if layer.id not in self._trees_of:
            paths = self._path_sigs(layer, sum(1 for c in layer.clips if c.end <= t))  # ADR 0025
            return self.transform_at(layer, t), paths
        tree = self._tree(layer)
        finished = tuple((lay.id, c.id) for lay, c in self._tree_clips(layer, tree) if c.end <= t)
        members = tuple((member, self.transform_at(self._layers[member], t)) for member in tree.members)
        return finished, members, self._tree_paths(layer, finished)

    # -- paths (ADR 0025) ------------------------------------------------------

    def _world_affine(self, layer: Layer, t: float) -> tuple[np.ndarray, np.ndarray]:
        """``p -> a p + b`` from a root's or child object's local units to world at ``t``."""
        a, b = _affine(self.transform_at(layer, t))
        if layer.is_child and not layer.is_part:
            pa, pb = _affine(self.transform_at(self._layers[layer.parent_id], t))
            a, b = pa @ a, pa @ b + pb
        return a, b

    def _path_signature(self, layer: Layer, clip: Clip) -> str:
        """What a path clip's run depends on: both layers' transforms at its start, the path's build
        (its file's signature too, for an SVG: ADR 0027)."""
        path = self._layers[clip.params["path"]]
        chain = [layer, path] + ([self._layers[path.parent_id]] if path.is_child else [])
        transforms = [self.transform_at(x, clip.start).model_dump_json() for x in chain]
        builds = [f"{x.spec.model_dump_json()}@{self._media_signature(x)}" for x in chain[1:]]
        return "|".join(transforms + builds)

    def _path_sigs(self, layer: Layer, count: int) -> tuple[str, ...]:
        """Signatures of the path clips among the layer's first ``count`` clips (cache keys)."""
        return tuple(
            self._path_signature(layer, c) for c in layer.clips[:count] if c.info.category == "motion"
        )

    def _path_target(self, layer: Layer, clip: Clip) -> m.Mobject | None:
        """A motion clip's path in the mover's local units, from the path layer's rest shape
        in world at the clip's start (never its clip state: no recursion between layers)."""
        if clip.info.category != "motion":
            return None
        path_layer = self._layers[clip.params["path"]]
        signature = self._media_signature(path_layer)
        if adapter.build_problem(path_layer.spec, signature) is not None:
            # A drawing that cannot be built: go to its placeholder's centre and stay (ADR 0027, 0032).
            path = m.VectorizedPoint(self._base_mobject(path_layer).get_center())
        else:
            path = adapter.longest_path(self._base_mobject(path_layer)).copy()
        a_path, b_path = self._world_affine(path_layer, clip.start)
        a_mover, b_mover = self._world_affine(layer, clip.start)
        inverse = np.linalg.pinv(a_mover)  # a mover scaled to 0 must not raise
        linear, offset = inverse @ a_path, inverse @ (b_path - b_mover)
        matrix = np.array(
            [[linear[0, 0], linear[0, 1], 0.0], [linear[1, 0], linear[1, 1], 0.0], [0.0, 0.0, 1.0]]
        )
        for sub in path.family_members_with_points():
            sub.points = sub.points @ matrix.T + np.array([offset[0], offset[1], 0.0])
        return path

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
        children = [x for x in self.project.layers if x.parent_id == root.id and not x.is_part]
        if children:
            tree = self._child_tree(root, children)
            self._trees[root.id] = tree
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

    def _child_tree(self, root: Layer, children: list[Layer]) -> _Tree:
        """An object and its child objects (ADR 0029): the root's build, then each child's built
        against it; a child owns its slice of the glyphs and pivots as before (no rest centre)."""
        if root.id not in self._base:
            builds = [adapter.build_mobject(root.spec, self._media_signature(root))]
            builds += [
                adapter.build_child(root.spec, child.spec, self.project.referenced_graphs(child))
                for child in children
            ]
            vector = all(isinstance(b, m.VMobject) for b in builds)
            self._base[root.id] = m.VGroup(*builds) if vector else m.Group(*builds)
        group = self._base[root.id]
        counts = [len(sub.family_members_with_points()) for sub in group.submobjects]
        starts = list(itertools.accumulate([0, *counts]))
        members = (root.id, *(child.id for child in children))
        owned = {member: tuple(range(starts[i], starts[i + 1])) for i, member in enumerate(members)}
        regions = {**owned, root.id: tuple(range(starts[-1]))}
        leaves = group.family_members_with_points()
        inner = {  # glyphs inside another glyph's family (an axis' ticks)
            id(sub) for leaf in leaves for sub in leaf.get_family()[1:] if len(sub.points)
        }
        drawn = {member: tuple(i for i in owned[member] if id(leaves[i]) not in inner) for member in members}
        return _Tree(root.spec, members, regions, owned, {}, drawn)

    def _tree_key(self, root: Layer, finished: tuple[ClipKey, ...]) -> tuple:
        """A tree state's cache key: the finished clips and the paths its root ran along (ADR 0025)."""
        return (root.id, finished, self._tree_paths(root, finished))

    def _tree_paths(self, root: Layer, finished: tuple[ClipKey, ...]) -> tuple[str, ...]:
        clips = {c.id: c for c in root.clips}
        return tuple(
            self._path_signature(root, clips[clip_id])
            for layer_id, clip_id in finished
            if layer_id == root.id and clips[clip_id].info.category == "motion"
        )

    def _tree_clips(self, root: Layer, tree: _Tree) -> list[tuple[Layer, Clip]]:
        """Clips of the tree's layers that animate glyphs, by start time (then tree order)."""
        order = {member: i for i, member in enumerate(tree.members)}
        clips = [
            (self._layers[member], clip)
            for member in tree.members
            if tree.regions[member]
            for clip in self._layers[member].clips
            if not clip.to_layer  # a morph takes over the whole tree (_tree_at)
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
        key = self._tree_key(root, finished)
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
        path = self._path_target(root, clip) if layer.id == root.id else None  # roots travel (ADR 0025)
        return adapter.make_animation(clip.kind, target, clip.ease, clip.params, path)

    def _tree_at(self, root: Layer, t: float) -> list[tuple[str, m.Mobject]]:
        start, end = self.lifetime(root)
        if not (start <= t < end):
            return []
        for index, clip in enumerate(root.clips):
            if clip.to_layer and clip.start <= t < clip.end:  # the whole tree morphs (ADR 0020)
                return [(root.id, self._morph_at(root, index, clip, (t - clip.start) / clip.duration))]
        return self._tree_members_at(root, t)

    def _tree_members_at(self, root: Layer, t: float, morphs: bool = True) -> list[tuple[str, m.Mobject]]:
        """The tree's members as drawn at ``t``, ignoring the whole tree's morphs (also a morph's
        ends). A member morphing draws the hand-off instead of its glyphs, unless ``morphs`` is
        False (a morph's own ends: no morph is evaluated inside another)."""
        start, end = self.lifetime(root)
        if not (start <= t <= end):
            return []
        tree = self._tree(root)
        clips = self._tree_clips(root, tree)
        finished = tuple((layer.id, c.id) for layer, c in clips if c.end <= t)
        source = list(self._tree_state(root, finished).family_members_with_points())
        overlays: dict[str, m.Mobject] = {}  # member -> what its overlay clip draws (ADR 0022)
        for layer, clip in clips:
            if not (clip.start <= t < clip.end):
                continue
            before = tuple((other.id, c.id) for other, c in clips if c.end <= clip.start)
            key = (layer.id, clip.id, before, self._tree_paths(root, (*before, (layer.id, clip.id))))
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
            if clip.info.overlay:
                overlays[layer.id] = active.anim.mobject
        out = []
        for member in tree.members:
            layer = self._layers[member]
            glyphs = tree.owned[member]
            if not glyphs and member not in overlays:
                continue
            if member != root.id:
                member_start, member_end = self.lifetime(layer)
                if not (member_start <= t < member_end):
                    continue
                morph = self._member_morph(layer, t) if morphs else None
                if morph is not None:  # a child object turning into another (ADR 0029)
                    out.append((member, morph))
                    continue
            local = m.VGroup(*(source[i] for i in tree.draws(member)))
            if member in overlays:
                local = m.Group(local, overlays[member])
            out.append((member, self._project_local(local, member, *self._member_affine(tree, layer, t))))
        return out

    def _member_morph(self, layer: Layer, t: float) -> m.Mobject | None:
        for index, clip in enumerate(layer.clips):
            if clip.to_layer and clip.start <= t < clip.end:
                return self._morph_at(layer, index, clip, (t - clip.start) / clip.duration)
        return None

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

    def position_frame(self, layer: Layer, t: float) -> tuple[np.ndarray, np.ndarray]:
        """``(a, b)`` with ``world pivot = a @ position + b`` at ``t`` (the motion path, ADR 0026)."""
        anchor = np.array(self.transform_at(layer, t).anchor, dtype=float)
        if layer.parent_id is None:
            return np.eye(2), anchor
        parent = self._layers[layer.parent_id]
        if layer.is_part:
            tree = self._tree(self.project.root_of(layer.id))
            a, b, _ = self._member_affine(tree, parent, t)
            centre = tree.centres.get(layer.id, np.zeros(3))[:2]
            return a, a @ (centre + anchor) + b
        a, b = _affine(self.transform_at(parent, t))
        return a, a @ anchor + b

    def layer_frame(self, layer: Layer, t: float) -> tuple[np.ndarray, float, np.ndarray]:
        """Where a layer's gizmo lives: its pivot and rotation in world space, and the
        map from a world-space move to a change of its own ``position``.

        An object pivots on its anchor moved by its position. A part pivots on its
        rest centre plus its anchor, moved by its own position and carried by its
        ancestors' transforms (ADR 0012, ADR 0021).
        """
        tr = self.transform_at(layer, t)
        anchor = np.array(tr.anchor, dtype=float)
        if layer.parent_id is None:
            return anchor + np.array(tr.position, dtype=float), tr.rotation, np.eye(2)
        if not layer.is_part:  # a child object: its parent's frame carries it (ADR 0024)
            parent = self._layers[layer.parent_id]
            ptr = self.transform_at(parent, t)
            a, b = _affine(ptr)
            pivot = a @ (anchor + np.array(tr.position, dtype=float)) + b
            return pivot, tr.rotation + ptr.rotation, np.linalg.pinv(a)
        root = self.project.root_of(layer.id)
        tree = self._tree(root)
        parent = self._layers[layer.parent_id]
        a, b, _ = self._member_affine(tree, parent, t)
        centre = tree.centres.get(layer.id, np.zeros(3))[:2]
        pivot = a @ (centre + anchor + np.array(tr.position, dtype=float)) + b
        ancestors = self.project.ancestors(layer.id)
        rotation = tr.rotation + sum(self.transform_at(x, t).rotation for x in ancestors)
        return pivot, rotation, np.linalg.pinv(a)  # pinv: a parent scaled to 0 must not raise

    def _to_world(self, local: m.Mobject, layer: Layer, t: float) -> m.Mobject:
        """Apply the keyframed layer transform (and a child object's parent's) without touching ``local``."""
        tr = self.transform_at(layer, t)
        if not layer.is_child:
            if tr == _IDENTITY:
                return local
            a, b = _affine(tr)
            return self._project_local(local, layer.id, a, b, tr.opacity)
        ptr = self.transform_at(self._layers[layer.parent_id], t)  # ADR 0024: carried by its parent
        a, b = _affine(tr)
        pa, pb = _affine(ptr)
        return self._project_local(local, layer.id, pa @ a, pa @ b + pb, tr.opacity * ptr.opacity)

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


def _builds(project: Project) -> dict[str, object]:
    """What each layer's base object is built from: roots with their parts' spans and their child
    objects' specs (a graph edit rebuilds its axes' tree, ADR 0029), child objects with their
    parent's spec (an axes edit re-plots its graphs)."""
    out: dict[str, object] = {}
    for root in project.roots():
        children = tuple(x.spec for x in project.layers if x.parent_id == root.id and not x.is_part)
        out[root.id] = (parts.build_spec(project, root.id), children)
    for layer in project.layers:
        if layer.is_child and not layer.is_part:
            out[layer.id] = (
                project.layer(layer.parent_id).spec,
                layer.spec,
                project.referenced_graphs(layer),
            )
    return out


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
    return Transform2D(**values, anchor=base.anchor)  # the anchor is never keyed (ADR 0021)


def _affine(tr: Transform2D, pivot: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """``p -> a p + b``: scale and rotate about ``pivot`` + the anchor, then move.

    ``pivot`` is the origin for objects and the rest centre for parts (ADR 0012,
    ADR 0021).
    """
    angle = math.radians(tr.rotation)
    c, s = math.cos(angle) * tr.scale, math.sin(angle) * tr.scale
    a = np.array([[c, -s], [s, c]])
    b = np.array(tr.position, dtype=float)
    centre = np.array(tr.anchor, dtype=float)
    if pivot is not None:
        centre = centre + pivot[:2]
    if centre.any():
        b = b + centre - a @ centre
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
            if k0.out_tangent is not None or k1.in_tangent is not None:  # a curved path (ADR 0026)
                return motion_paths.point_at(k0.value, k0.out_tangent, k1.in_tangent, k1.value, u)
            if isinstance(k0.value, tuple):
                return tuple(a + (b - a) * u for a, b in zip(k0.value, k1.value, strict=True))
            return k0.value + (k1.value - k0.value) * u
    return track[-1].value


def _compose(groups: list[tuple[str | None, m.Mobject]]) -> m.Mobject:
    """One morph end for kinds that do not match pieces: the members as one object."""
    if len(groups) == 1:
        return groups[0][1]
    return m.VGroup(*(mob for _, mob in groups))


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
