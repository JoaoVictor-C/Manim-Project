"""One-way export to Manim Python (ADR 0010, ADR 0031).

``to_python(project)`` writes either **readable** code - one variable per layer
and ``self.play`` / ``self.wait`` in time order, needing only Manim - or, when
the project uses something plain Manim code cannot reproduce exactly, an
**exact** scene that plays the project through this package's evaluator
(``manim_scene.StudioScene``) and says why in its header. The video export
never depends on either.
"""

from __future__ import annotations

import inspect
import json
import keyword
import math
import re
from dataclasses import dataclass, field

import manim as m
import numpy as np

from .. import plugins
from . import adapter, audio
from .evaluator import layer_transform
from .schema import (
    CODE_TYPES,
    CONNECTOR_TYPES,
    DIRECTIONS,
    GROUPS_ONE_OBJECT,
    NUMBER_TYPES,
    TEXT_TYPES,
    TRACE_TYPES,
    Clip,
    Easing,
    Layer,
    Project,
    clip_params,
    infer_lifetime,
)

EPS = 1e-9
STAR: dict = {}
exec("from manim import *", STAR)  # what a generated file can name without a prefix
HELPERS = {"clamped", "cubic_bezier", "Keyed", "KeyedClip", "multiply_opacity", "curve_point"}
RESERVED = set(STAR) | set(dir(__builtins__)) | {"self", "np", "math"} | HELPERS


@dataclass
class PythonExport:
    code: str
    readable: bool
    problems: list[str] = field(default_factory=list)


def to_python(
    project: Project, scene_name: str = "StudioExport", code_cache_dir: str | None = None
) -> PythonExport:
    """The project as a Manim scene file: readable when it can be, exact otherwise."""
    problems = readable_problems(project)
    if problems:
        return PythonExport(_exact(project, scene_name, problems, code_cache_dir), False, problems)
    code = _Readable(project, scene_name).code()
    compile(code, "<export>", "exec")  # a broken file is never written
    return PythonExport(code, True, [])


def subcaptions(project: Project) -> list[str]:
    """``add_subcaption`` calls: Manim writes the subtitles as an .srt beside its video (ADR 0035)."""
    return [
        f"self.add_subcaption({cue.text.strip()!r}, "
        f"duration={_num(cue.end - cue.start)}, offset={_num(cue.start)})"
        for cue in project.subtitles
        if cue.text.strip()
    ]


def class_name(stem: str) -> str:
    """A scene class name from a file name: 'my intro' -> 'MyIntro'."""
    words = re.findall(r"[A-Za-z0-9]+", stem)
    name = "".join(w[:1].upper() + w[1:] for w in words) or "StudioExport"
    return name if name[0].isalpha() else f"Scene{name}"


# -- what readable code cannot express --------------------------------------------------------------


def readable_problems(project: Project) -> list[str]:
    """Why the project cannot be written as plain ``self.play`` code (empty: it can)."""
    out: list[str] = []
    morph_targets = {c.to_layer for layer in project.layers for c in layer.clips if c.to_layer}

    def name(layer: Layer) -> str:
        return layer.name or layer.id

    groups = {layer.id for layer in project.layers if layer.is_group}
    for layer in project.layers:
        if layer.is_group or layer.parent_id in groups:  # ADR 0050
            out.append(f"{name(layer)}: {GROUPS_ONE_OBJECT}")
            continue
        if layer.parent_id is not None:
            out.append(f"{name(layer)}: parts and objects on axes are evaluated as one object")
            continue
        if layer.spec.type in CODE_TYPES:
            out.append(f"{name(layer)}: code layers are rendered by the editor")
        if _keyed(layer):  # drawn through the Keyed helper, which applies the transform after the clips
            out += [f"{name(layer)}: {why}" for why in _keyed_problems(project, layer)]
        base = layer.base
        turned = base.rotation != 0 or base.scale != 1 or tuple(base.anchor) != (0.0, 0.0)
        if layer.clips and turned and not _drawn_by_keyed(project, layer):
            out.append(f"{name(layer)}: clips on a turned or scaled object animate before its transform")
        if any(c.info.category == "motion" and c.params.get("rotate") == "along" for c in layer.clips):
            out.append(f"{name(layer)}: turning along a path")
        if layer.id in morph_targets and (layer.lifetime.in_ is not None or layer.lifetime.out is not None):
            out.append(f"{name(layer)}: a morph target with its own lifetime")
        if layer.spec.type in plugins.TYPES:
            out.append(f"{name(layer)}: a plugin object")
        elif layer.spec.type in TRACE_TYPES or layer.spec.type in plugins.SIMULATIONS:
            out.append(f"{name(layer)}: a simulated layer")
        elif layer.spec.type in CONNECTOR_TYPES:
            out += [f"{name(layer)}: {why}" for why in _connector_problems(project, layer)]
        elif adapter.build_problem(layer.spec) is not None:
            out.append(f"{name(layer)}: {adapter.build_problem(layer.spec)}")
    for clip in project.audio:  # Manim's add_sound places and gains a whole file (ADR 0034)
        label = clip.name or clip.id
        why = audio.problem(clip)
        length = audio.probe(clip.path)
        if why is not None:
            out.append(f"{label}: {why}")
        elif clip.offset > EPS or length is None or abs(clip.duration - length) > 1e-3:
            out.append(f"{label}: a trimmed sound")
        if clip.fade_in > 0 or clip.fade_out > 0:
            out.append(f"{label}: a faded sound")
        if clip.end > project.canvas.duration + EPS:
            out.append(f"{label}: a sound longer than the scene")
    if project.subtitles and project.subtitle_style.burn_in:  # ADR 0035: drawn by the editor
        out.append("subtitles: burned into the frames")
    clusters = _clusters(project)
    for t, layer_id, _ in _lifetime_events(project):
        if any(start + EPS < t < end - EPS for start, end, _ in clusters):
            out.append(f"{name(project.layer(layer_id))}: appears or disappears during other animations")
    for start, _end, members in clusters:
        for i, (layer, clip) in enumerate(members):
            earlier = [c for lay, c in members[:i] if lay.id == layer.id]
            if clip.kind == "Wiggle" and earlier and clip.start > start + EPS:
                out.append(f"{name(layer)}: Wiggle after another clip of the same object in one group")
    return list(dict.fromkeys(out))


def _keyed(layer: Layer) -> bool:
    return any(layer.tracks.values())


def _drawn_by_keyed(project: Project, layer: Layer) -> bool:
    """Is the layer drawn through the ``Keyed`` helper: a keyed layer, or one whose spotlight
    (FocusOn) must close on the object's own origin, as the editor's does, when nothing stops it."""
    if _keyed(layer):
        return True
    if layer.parent_id is not None or not any(c.kind == "FocusOn" for c in layer.clips):
        return False
    ends = {
        x.spec.params.get(n)
        for x in project.layers
        if x.spec and x.spec.type in CONNECTOR_TYPES
        for n in ("source", "target")
    }
    return layer.id not in ends and not _keyed_problems(project, layer)


def _keyed_problems(project: Project, layer: Layer) -> list[str]:
    """Why a keyframed layer cannot be drawn by the ``Keyed`` helper (G3a, ADR 0046): its drawing is
    a copy made at every frame, so nothing else may hold on to the object itself."""
    out = []
    if layer.spec.type in CONNECTOR_TYPES:
        out.append("a keyframed connector")
    if any(c.info.category == "motion" for c in layer.clips):  # its path would be in moving units
        out.append("a keyframed object moving along a path")
    if any(c.to_layer == layer.id for x in project.layers for c in x.clips):
        out.append("a morph into a keyframed object")
    for start, _end, members in _clusters(project):  # a morph takes the drawing when its play starts
        if any(lay.id == layer.id and c.to_layer and c.start > start + EPS for lay, c in members):
            out.append("a keyframed object morphing during other animations")
    return out


def _connector_problems(project: Project, layer: Layer) -> list[str]:
    """Why a connector cannot be ``always_redraw(lambda: Line(a.get_center(), b.get_center()))``
    (ADR 0036): Manim's line runs between the drawings' centres and is drawn all the time."""
    out = []
    params = layer.spec.params
    if params.get("ends", "edges") != "centres":
        out.append("a connector ending at the edges of its objects")
    if any(tuple(params.get(n) or (0.0, 0.0))[:2] != (0.0, 0.0) for n in ("source_offset", "target_offset")):
        out.append("a connector from points off the centres")
    base = layer.base
    if tuple(base.position) != (0.0, 0.0) or base.scale != 1 or base.rotation != 0 or base.opacity != 1:
        out.append("a moved, turned, scaled or faded connector")
    morphing = {c.to_layer for x in project.layers for c in x.clips if c.to_layer}
    morphing |= {x.id for x in project.layers if any(c.to_layer for c in x.clips)}
    start, end = infer_lifetime(layer)
    for target_id in (params.get("source"), params.get("target")):
        target = project.layer(target_id)
        if target_id in morphing:
            out.append("a connector to a morphing object")
        if _keyed(target):  # its drawing is redrawn after the connector reads it
            out.append("a connector to a keyframed object")
        target_start, target_end = infer_lifetime(target)
        if target_start > start + EPS or target_end < end - EPS:
            out.append("a connector to an object that is not drawn all the time")
    return list(dict.fromkeys(out))


def _clusters(project: Project) -> list[tuple[float, float, list[tuple[Layer, Clip]]]]:
    """Clips grouped where they overlap in time: each group plays as one ``self.play``."""
    clips = sorted(((layer, c) for layer in project.layers for c in layer.clips), key=lambda lc: lc[1].start)
    groups: list[tuple[float, float, list[tuple[Layer, Clip]]]] = []
    for layer, clip in clips:
        if groups and clip.start < groups[-1][1] - EPS:
            start, end, members = groups[-1]
            groups[-1] = (start, max(end, clip.end), [*members, (layer, clip)])
        else:
            groups.append((clip.start, clip.end, [(layer, clip)]))
    return groups


def _lifetime_events(project: Project) -> list[tuple[float, str, str]]:
    """(time, layer, 'add' | 'remove') that no clip does by itself."""
    targets = {c.to_layer for layer in project.layers for c in layer.clips if c.to_layer}
    out = []
    for layer in project.layers:
        if layer.parent_id is not None or layer.id in targets:
            continue  # a morph target appears through its morph
        start, end = infer_lifetime(layer)
        introduced = bool(layer.clips) and layer.clips[0].info.introducer and layer.lifetime.in_ is None
        if not introduced:
            out.append((start, layer.id, "add"))
        if layer.lifetime.out is not None and math.isfinite(end):
            out.append((end, layer.id, "remove"))
    return out


# -- readable code ------------------------------------------------------------------------------------

# Written into a readable file that has keyframed layers (G3a, ADR 0046). The editor draws a layer
# as its clips leave the object, then moved, scaled, turned and faded by its keys; Manim's ``.animate``
# would cut a turn as a chord and could not overlap a clip, so the file keeps the keys as data and
# draws a copy of the object through them at every frame. Manim adds whatever an animation plays on
# to the scene, so a keyed layer's clips play through ``KeyedClip``, which keeps the object itself out.
_KEYED_HELPER = '''\
class Keyed(Group):
    """A keyframed layer, drawn as the editor draws it.

    ``source`` is the object the layer's clips animate; it is never added to the scene. At every
    frame the scene shows a copy of it scaled and turned about ``anchor``, then moved and faded, by
    the layer's transform at that frame's time: the editor applies a layer's transform after its
    clips. A keyed property is a list of keys ``(time, value, ease)``, each ease shaping the move to
    the next key (the keys of a curved path add their in and out tangents); the others are constants.
    """

    def __init__(
        self, scene, source, anchor=(0.0, 0.0), position=(0.0, 0.0), scale=1.0, rotation=0.0, opacity=1.0
    ):
        super().__init__()
        self.scene, self.source, self.anchor = scene, source, anchor
        self.keys = {"position": position, "scale": scale, "rotation": rotation, "opacity": opacity}
        self.overlays = []  # what an overlay clip (Flash) draws besides the object, while it plays
        fps = config.frame_rate
        # A dt updater, so Manim redraws it in waits too, at the frame's own time on the frame grid.
        self.add_updater(lambda drawing, dt: drawing.draw(round(scene.renderer.time * fps) / fps))

    def draw(self, t):
        # Manim lists what it draws when a play begins, so the last drawing is emptied, not dropped.
        for drawing in self.submobjects:
            for part in drawing.get_family():
                part.points = np.zeros((0, 3))
        self.submobjects = [self.at(t)]

    def at(self, t):
        """A copy of the source (and its overlays) through the layer's transform at ``t``."""
        drawing = self.source.copy()
        if self.overlays:
            drawing = Group(drawing, *(overlay.copy() for overlay in self.overlays))
            drawing.set_z_index(self.source.z_index)
        (x, y), scale, opacity = self.value("position", t), self.value("scale", t), self.value("opacity", t)
        angle = self.value("rotation", t) * DEGREES
        c, s = np.cos(angle) * scale, np.sin(angle) * scale
        matrix = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
        pivot = np.array([*self.anchor, 0.0])
        shift = np.array([x, y, 0.0]) + pivot - matrix @ pivot
        for part in drawing.get_family():
            if len(part.points):
                part.points = part.points @ matrix.T + shift
            if opacity != 1:
                multiply_opacity(part, opacity)
        return drawing

    def value(self, name, t):
        """A property at ``t``: held before the first key and after the last, eased in between."""
        keys = self.keys[name]
        if not isinstance(keys, list):
            return keys
        if t <= keys[0][0]:
            return keys[0][1]
        if t >= keys[-1][0]:
            return keys[-1][1]
        for k0, k1 in zip(keys, keys[1:]):
            if k0[0] <= t < k1[0]:
                u = k0[2]((t - k0[0]) / (k1[0] - k0[0]))
                if len(k0) > 3 and (k0[4] is not None or k1[3] is not None):  # a curved path
                    return curve_point(k0[1], k0[4], k1[3], k1[1], u)
                if isinstance(k0[1], tuple):
                    return tuple(a + (b - a) * u for a, b in zip(k0[1], k1[1]))
                return k0[1] + (k1[1] - k0[1]) * u
        return keys[-1][1]

    def clip(self, animation):
        """``animation``, acting on the source, as a clip of this layer."""
        return KeyedClip(animation, self)

    def still(self, t):
        """The drawing at ``t``, taking this one's place in the scene: a morph starts from it."""
        self.scene.remove(self)
        return self.at(t)


class KeyedClip(Animation):
    """A clip of a keyframed layer: ``animation`` acts on the layer's source and the drawing follows
    it - added to the scene by an introducer, taken away by a remover. An overlay (Flash) is drawn
    with the object while it plays."""

    def __init__(self, animation, drawing):
        self.animation, self.drawing = animation, drawing
        own = animation.mobject is drawing.source  # not an overlay, whose removal is its own
        super().__init__(
            Mobject(),  # a stand-in: the source stays out of the scene, the drawing redraws itself
            run_time=animation.run_time,
            rate_func=linear,
            introducer=own and animation.is_introducer(),
            remover=own and animation.is_remover(),
        )

    def _setup_scene(self, scene):
        if self.is_introducer():
            scene.add(self.drawing)

    def begin(self):
        if isinstance(self.animation, Succession):  # sets up its parts as they start: none in the scene
            self.animation.scene = None
        self.animation.begin()
        if self.animation.mobject is not self.drawing.source:
            self.drawing.overlays.append(self.animation.mobject)

    def update_mobjects(self, dt):
        pass  # the editor never runs an animation's own updaters (FocusOn's spotlight stays put)

    def interpolate(self, alpha):
        self.animation.interpolate(alpha)

    def finish(self):
        self.animation.finish()
        self.drawing.overlays = [m for m in self.drawing.overlays if m is not self.animation.mobject]

    def clean_up_from_scene(self, scene):
        self.animation.clean_up_from_scene(scene)
        scene.remove(self.mobject)
        if self.is_remover():
            scene.remove(self.drawing)


def multiply_opacity(part, factor):
    """``part``'s opacity times ``factor``, from what it is now (as the editor fades a layer)."""
    if isinstance(part, VMobject):
        for rgbas in (part.fill_rgbas, part.stroke_rgbas, part.background_stroke_rgbas):
            if rgbas is not None and len(rgbas):
                rgbas[:, 3] *= factor
    elif isinstance(part, ImageMobject):
        part.pixel_array[:, :, 3] = (part.pixel_array[:, :, 3] * factor).astype(np.uint8)'''

_CURVE_HELPER = '''\
def curve_point(p0, out0, in1, p1, u):
    """The position at eased time ``u`` on a curved path from ``p0`` to ``p1``: the cubic Bezier
    through the keys' tangents, walked by length; past either end it goes on along that end."""
    a, b = np.array(p0, dtype=float), np.array(p1, dtype=float)
    c0, c1 = a + np.array(out0 or (0.0, 0.0)), b + np.array(in1 or (0.0, 0.0))

    def bezier(s):
        s = np.asarray(s, dtype=float)[..., None]
        return (1 - s) ** 3 * a + 3 * (1 - s) ** 2 * s * c0 + 3 * (1 - s) * s**2 * c1 + s**3 * b

    samples = np.linspace(0.0, 1.0, 128)
    lengths = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(bezier(samples), axis=0), axis=1))])
    total = lengths[-1]
    if total <= 0:
        return (float(a[0]), float(a[1]))
    if u < 0 or u > 1:  # an overshoot keeps going in the direction of travel
        end = u > 1
        direction = np.zeros(2)
        for vector in [b - c1, b - c0, b - a] if end else [c0 - a, c1 - a, b - a]:
            if np.linalg.norm(vector) > 1e-12:
                direction = vector / np.linalg.norm(vector)
                break
        x, y = (b if end else a) + direction * ((u - 1) if end else u) * total
        return (float(x), float(y))
    x, y = bezier(np.interp(u * total, lengths, samples))
    return (float(x), float(y))'''


class _Readable:
    def __init__(self, project: Project, scene_name: str) -> None:
        self.project = project
        self.scene_name = scene_name
        self.names = _variable_names(project)
        self.keyed = {layer.id for layer in project.layers if _drawn_by_keyed(project, layer)}
        self.drawings = _drawing_names(project, self.names, self.keyed)  # keyed layer -> its Keyed
        self.helpers: set[str] = set()

    def code(self) -> str:
        body = [*self._sounds(), *self._objects(), "", *self._timeline()]
        canvas = self.project.canvas
        lines = [
            '"""Generated by Manim Studio (readable form: plain Manim, ADR 0031)."""',
            "",
            "from __future__ import annotations",
            "",
            "from manim import *",
            "",
            f"config.pixel_width = {canvas.width_px}",
            f"config.pixel_height = {canvas.height_px}",
            f"config.frame_rate = {canvas.fps}",
            f"config.frame_height = {_num(canvas.frame_height)}",
            f"config.frame_width = {_num(canvas.frame_width)}",
            f"config.background_color = {canvas.background!r}",
        ]
        if self.keyed:
            lines.append(
                "config.disable_caching = True  # keyed layers read the clock, which the cache cannot see"
            )
        lines.append("")
        if self.keyed:
            lines += ["", *_KEYED_HELPER.splitlines(), ""]
        if "curve_point" in self.helpers:
            lines += ["", *_CURVE_HELPER.splitlines(), ""]
        if "clamped" in self.helpers:
            lines += [
                "",
                "def clamped(rate_func):",
                '    """The ease kept within its end states, as the editor plays content clips."""',
                "    return lambda t: min(1.0, max(0.0, rate_func(t)))",
                "",
            ]
        if "cubic_bezier" in self.helpers:
            lines += ["", *inspect.getsource(adapter.cubic_bezier).splitlines(), ""]
        camera = self.project.camera
        if camera.is_default:
            lines += ["", f"class {self.scene_name}(Scene):", "    def construct(self):"]
        else:  # the editor's turned camera (ADR 0048): Manim's ThreeDCamera at the same angles
            lines += ["", f"class {self.scene_name}(ThreeDScene):", "    def construct(self):"]
            body.insert(0, _camera_orientation(camera))
        lines += [f"        {line}" if line else "" for entry in body for line in entry.split("\n")]
        return "\n".join(lines).rstrip() + "\n"

    # sound (ADR 0034)

    def _sounds(self) -> list[str]:
        sounds = [
            f"self.add_sound({clip.path!r}, time_offset={_num(clip.start)}, gain={_num(clip.gain)})"
            for clip in self.project.audio
        ]
        return sounds + subcaptions(self.project)

    # objects

    def _objects(self) -> list[str]:
        out = []
        connectors = []
        for index, layer in enumerate(self.project.layers):
            var = self.names[layer.id]
            if layer.spec.type in CONNECTOR_TYPES:  # after the objects it reads (ADR 0036)
                connectors.append(f"{var} = {self._connector(layer, index)}")
                continue
            out.append(f"{var} = {_construct(layer.spec)}")
            out += [f"{var}.{call}" for call in _style_calls(adapter.text_style(layer.spec)[1])]
            out.append(f"{var}.move_to(ORIGIN)")
            if layer.id in self.keyed:  # its transform is drawn frame by frame, after its clips
                out.append(f"{var}.set_z_index({index})  # the layer order")
                out.append(self._keyed(layer))
                continue
            out += [f"{var}.{call}" for call in _transform_calls(layer)]
            out.append(f"{var}.set_z_index({index})  # the layer order")
        return out + connectors

    def _keyed(self, layer: Layer) -> str:
        """The layer's Keyed drawing: its keys as tables, its unkeyed transform as constants."""
        base = layer.base
        args = []
        if tuple(base.anchor) != (0.0, 0.0):
            args.append(f"anchor={_pair(base.anchor)}")
        rest = {"position": (0.0, 0.0), "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
        for prop, default in rest.items():
            track = layer.tracks.get(prop)
            if track:
                curved = any(k.curved for k in track)
                if curved:
                    self.helpers.add("curve_point")
                rows = [f"        {self._key(k, curved)}," for k in track]
                args.append("\n".join([f"{prop}=[", *rows, "    ]"]))
            elif getattr(base, prop) != default:
                value = getattr(base, prop)
                args.append(f"{prop}={_pair(value) if prop == 'position' else _num(value)}")
        var = self.names[layer.id]
        lines = [f"{self.drawings[layer.id]} = Keyed(self, {var},", *(f"    {a}," for a in args), ")"]
        return "\n".join(lines)

    def _key(self, key, curved: bool) -> str:
        """A key as ``(time, value, ease)``; a curved track's keys add their in and out tangents."""
        value = _pair(key.value) if isinstance(key.value, tuple) else _num(key.value)
        cells = [_num(key.t), value, self._ease(key.ease, clamp=False)]
        if curved:
            cells += [_pair(t) if t is not None else "None" for t in (key.in_tangent, key.out_tangent)]
        return f"({', '.join(cells)})"

    def _drawn(self, layer_id: str) -> str:
        """What the scene adds and removes for a layer: its Keyed drawing when it is keyed."""
        return self.drawings.get(layer_id, self.names[layer_id])

    def _connector(self, layer: Layer, index: int) -> str:
        """A connector redrawn between its objects' centres every frame (ADR 0036)."""
        spec = layer.spec
        cls = adapter.CONNECTOR_CLASSES[spec.params.get("tips", "none")].__name__
        a, b = (self.names[spec.params[n]] for n in ("source", "target"))
        kwargs = ", ".join(f"{k}={v!r}" for k, v in adapter.connector_kwargs(spec).items())
        line = f"{cls}({a}.get_center(), {b}.get_center(), {kwargs})"
        return f"always_redraw(lambda: {line}.set_z_index({index}))"

    # timeline

    def _timeline(self) -> list[str]:
        """Plays and waits in time order. Waits are counted in frames: Manim draws ``ceil(run_time *
        fps)`` frames for a play, so after a clip that ends between frames the wait covers exactly
        the frames left until the next event, as the editor's export draws them."""
        events: list[tuple[float, int, list[str]]] = []
        for t, layer_id, what in _lifetime_events(self.project):
            order = 0 if what == "remove" else 1
            events.append((t, order, [f"self.{what}({self._drawn(layer_id)})"]))
        clusters = _clusters(self.project)
        for start, end, members in clusters:
            events.append((start, 2, self._play(start, end, members)))
        fps = self.project.canvas.fps
        out, cursor, frames = [], 0.0, 0  # cursor: the time of the timeline; frames: those Manim drew
        for t, _, lines in sorted(events, key=lambda e: (e[0], e[1])):
            first = _first_frame(t, fps)
            if first > frames:
                out.append(_wait(first - frames, fps, t - cursor))
                frames = first
            cursor = max(cursor, t)
            out += lines
            if lines[0].startswith("self.play"):
                end = next(end for s, end, _ in clusters if abs(s - t) < EPS)
                frames += _play_frames(float(_time(end - t)), fps)
                cursor = max(cursor, end)
        total = round(self.project.canvas.duration * fps)
        if total > frames:
            out.append(_wait(total - frames, fps, self.project.canvas.duration - cursor))
        return out

    def _play(self, start: float, end: float, members: list[tuple[Layer, Clip]]) -> list[str]:
        if len(members) == 1:
            layer, clip = members[0]
            return [f"self.play({self._animation(layer, clip)}, run_time={_time(clip.duration)})"]
        # One chain per object: an AnimationGroup keeps playing finished animations at their
        # end, so two clips of one object side by side would fight; a Succession plays one.
        chains: dict[str, list[tuple[Layer, Clip]]] = {}
        for layer, clip in members:
            chains.setdefault(layer.id, []).append((layer, clip))
        parts = []
        for chain in chains.values():
            steps, cursor = [], start
            for layer, clip in chain:
                if clip.start - cursor > EPS:
                    steps.append(f"Wait({_time(clip.start - cursor)})")
                steps.append(self._animation(layer, clip, run_time=clip.duration))
                cursor = clip.end
            parts.append(steps[0] if len(steps) == 1 else f"Succession({', '.join(steps)})")
        inner = ",\n".join(f"    {p}" for p in parts)
        return [f"self.play(AnimationGroup(\n{inner},\n), run_time={_time(end - start)})"]

    def _animation(self, layer: Layer, clip: Clip, run_time: float | None = None) -> str:
        cls = adapter.ANIMATION_CLASSES[clip.kind]
        name = {"TabledMoveAlongPath": "MoveAlongPath", "KeyedTransformMatching": "TransformMatchingTex"}.get(
            cls.__name__, cls.__name__
        )
        var = self.names[layer.id]
        keyed = layer.id in self.keyed
        args = [var]
        info = clip.info
        if info.category == "morph":
            if keyed:  # a morph is a hand-off in world space: from the drawing as its play starts
                args[0] = f"{self.drawings[layer.id]}.still({_num(clip.start)})"
            args.append(self.names[clip.to_layer])
        if info.category == "motion":
            args.append(self._path(clip.params["path"], clip.start))
        kwargs: dict[str, str] = {}
        for param in clip_params(clip.kind):
            value = clip.params.get(param.name, param.default)
            if value is None or param.kind == "layer" or param.name == "rotate":
                continue
            if param.name not in clip.params and _manim_default(cls, param.name, clip.kind, value):
                continue  # Manim's own default: nothing to say
            if param.kind == "direction":
                kwargs[param.name] = value if value in DIRECTIONS else _vector(value)
            elif param.kind == "choice" and param.name == "shape":
                kwargs[param.name] = adapter.SHAPES[value].__name__
            else:
                kwargs[param.name] = repr(value)
        registered = {p.name for p in clip_params(clip.kind)}
        for key, value in clip.params.items():
            if key not in registered:
                kwargs[key] = repr(value)
        if clip.kind == "Wiggle":  # the editor pins the pivot to where the object starts
            kwargs["scale_about_point"] = kwargs["rotate_about_point"] = f"{var}.get_center()"
        replaces = issubclass(cls, (m.ReplacementTransform, m.FadeTransform)) or not issubclass(
            cls, m.Transform
        )
        if info.category == "morph" and not replaces:  # the target, not the source, stays drawn
            kwargs["replace_mobject_with_target_in_scene"] = "True"
        if clip.ease is not None:
            kwargs["rate_func"] = self._ease(clip.ease, info.clamps_alpha)
        if run_time is not None:
            kwargs["run_time"] = _time(run_time)
        text = f"{name}({', '.join([*args, *(f'{k}={v}' for k, v in kwargs.items())])})"
        if keyed and info.category != "morph":  # it acts on the object; the drawing follows
            return f"{self.drawings[layer.id]}.clip({text})"
        return text

    def _path(self, layer_id: str, at: float) -> str:
        """The path layer's rest shape where it is at ``at``, built afresh (its own clips must not
        move the path; its keys place it as the clip starts, as the editor reads it)."""
        layer = self.project.layer(layer_id)
        shape = _construct(layer.spec)
        style = adapter.text_style(layer.spec)[1]
        calls = [*_style_calls(style), "move_to(ORIGIN)", *_transform_calls(layer, at)]
        built = f"{shape}.{'.'.join(calls)}"
        if layer.spec.type == "SVGMobject" or layer.spec.type in TEXT_TYPES:  # its longest path (ADR 0027)
            return f"max({built}.family_members_with_points(), key=lambda p: p.get_arc_length())"
        return built

    def _ease(self, ease: Easing, clamp: bool) -> str:
        if ease.bezier is not None:
            self.helpers.add("cubic_bezier")
            text = f"cubic_bezier({', '.join(_num(v) for v in ease.bezier)})"
            func = adapter.rate_func(ease)
        else:
            name = ease.name or "linear"
            text = name if name in STAR else f"rate_functions.{name}"  # ease_* are not star-exported
            func = adapter.rate_func(ease)
        samples = [func(i / 200) for i in range(201)]
        if clamp and (min(samples) < -EPS or max(samples) > 1 + EPS):
            self.helpers.add("clamped")
            return f"clamped({text})"
        return text


def _manim_default(cls: type, name: str, kind: str, value) -> bool:
    """Is ``value`` (converted as the editor converts it) what Manim uses when it is not given?"""
    try:
        default = inspect.signature(cls.__init__).parameters[name].default
    except (KeyError, ValueError):
        return False
    if default is inspect.Parameter.empty:
        return False
    ours = adapter.clip_kwargs(kind, {name: value}).get(name)
    try:
        if isinstance(default, m.ManimColor):
            return m.ManimColor(ours) == default
        return bool(np.all(np.asarray(ours) == np.asarray(default)))
    except (TypeError, ValueError):
        return False


def _variable_names(project: Project) -> dict[str, str]:
    taken: set[str] = set()
    out = {}
    for layer in project.layers:
        base = re.sub(r"\W+", "_", (layer.name or layer.id).strip().lower()).strip("_") or "layer"
        if base[0].isdigit():
            base = f"layer_{base}"
        name, n = base, 2
        while name in taken or name in RESERVED or keyword.iskeyword(name):
            name, n = f"{base}_{n}", n + 1
        taken.add(name)
        out[layer.id] = name
    return out


def _drawing_names(project: Project, names: dict[str, str], keyed: set[str]) -> dict[str, str]:
    """``<name>_keyed`` for each keyed layer, unique among the layers' names."""
    taken = set(names.values())
    out = {}
    for layer in project.layers:
        if layer.id not in keyed:
            continue
        base = f"{names[layer.id]}_keyed"
        name, n = base, 2
        while name in taken or name in RESERVED:
            name, n = f"{base}_{n}", n + 1
        taken.add(name)
        out[layer.id] = name
    return out


def _construct(spec) -> str:
    """The constructor call that builds ``spec`` as the editor does (adapter._build)."""
    if spec.type == "Axes":

        def axes(name: str):
            param = next(p for p in adapter.MOBJECT_PARAMS["Axes"] if p.name == name)
            return spec.params.get(name, param.default)

        x0, x1 = (adapter._whole(v) for v in axes("x_range")[:2])
        y0, y1 = (adapter._whole(v) for v in axes("y_range")[:2])
        numbers = axes("numbers") == "yes"
        return (
            f"Axes(x_range=[{x0!r}, {x1!r}, {adapter._whole(axes('x_step'))!r}], "
            f"y_range=[{y0!r}, {y1!r}, {adapter._whole(axes('y_step'))!r}], "
            f"x_length={_num(axes('x_length'))}, y_length={_num(axes('y_length'))}, "
            f'axis_config={{"include_numbers": {numbers}}})'
        )
    if spec.type == "RightTriangle":  # not a Manim class: an outline and the mark of its right angle
        angle = float(spec.params.get("angle", 45.0))
        side = float(spec.params.get("side_length", 3.0))
        corner, end, top = (_vector(p) for p in adapter.right_triangle_points(angle, side))
        a, b, c = (_vector(p) for p in adapter.right_triangle_mark(angle, side))
        return f"VGroup(Polygon({corner}, {end}, {top}), Line({a}, {b}), Line({b}, {c})).move_to(ORIGIN)"
    params = adapter.number_kwargs(spec) if spec.type in NUMBER_TYPES else dict(spec.params)
    args = []
    if spec.type in TEXT_TYPES:
        args.append(repr(params.pop("text", "")))
    elif spec.type in ("ImageMobject", "SVGMobject"):
        args.append(repr(params.pop("path")))
    points = {p.name for p in adapter.MOBJECT_PARAMS.get(spec.type, ()) if p.kind == "point"}
    for key, value in params.items():
        args.append(f"{key}={_vector(value) if key in points else repr(value)}")
    for key, value in adapter.text_style(spec)[0].items():  # a Text's fill beside its t2c (ADR 0049)
        args.append(f"{key}={value!r}")
    return f"{spec.type}({', '.join(args)})"


def _style_calls(style: dict) -> list[str]:
    """set_fill / set_stroke as adapter._apply_style calls them (missing values are left out)."""

    def call(method: str, color: str, extra: dict[str, str]) -> str:
        args = [repr(style[color])] if style.get(color) is not None else []
        args += [f"{k}={style[v]!r}" for k, v in extra.items() if style.get(v) is not None]
        return f"{method}({', '.join(args)})"

    out = []
    if "fill" in style or "fill_opacity" in style:
        out.append(call("set_fill", "fill", {"opacity": "fill_opacity"}))
    if "stroke" in style or "stroke_width" in style or "stroke_opacity" in style:
        out.append(call("set_stroke", "stroke", {"width": "stroke_width", "opacity": "stroke_opacity"}))
    return out


def _transform_calls(layer: Layer, at: float | None = None) -> list[str]:
    """The layer's transform as calls: its base, or its keyed transform at ``at``."""
    base = layer.base if at is None else layer_transform(layer, at)
    pivot = _vector(base.anchor)
    out = []
    if base.scale != 1:
        out.append(f"scale({_num(base.scale)}, about_point={pivot})")
    if base.rotation != 0:
        out.append(f"rotate({_num(base.rotation)} * DEGREES, about_point={pivot})")
    if tuple(base.position) != (0.0, 0.0):
        out.append(f"shift({_vector(base.position)})")
    if base.opacity != 1:
        out.append(f"fade({_num(1 - base.opacity)})")
    return out


def _vector(value) -> str:
    x, y = (float(v) for v in list(value)[:2])
    return f"[{_num(x)}, {_num(y)}, 0.0]"


def _pair(value) -> str:
    x, y = (float(v) for v in list(value)[:2])
    return f"({_num(x)}, {_num(y)})"


def _first_frame(t: float, fps: int) -> int:
    """The first frame the editor draws at or after ``t``."""
    return math.ceil(t * fps - 1e-6)


def _play_frames(run_time: float, fps: int) -> int:
    """How many frames Manim draws for a play of ``run_time`` seconds (Scene.get_time_progression)."""
    return len(np.arange(0, run_time, 1 / fps))


def _wait(frames: int, fps: int, nominal: float) -> str:
    """``self.wait`` for exactly ``frames`` frames, whether Manim holds one frame (``int(run_time /
    dt)`` of them) or draws them one by one (``np.arange(0, run_time, dt)``): the timeline's own
    interval when it does, else the nearest time that does (said in a comment)."""
    dt = 1 / fps
    nominal = round(nominal, 9)
    value = next((v for v in (nominal, frames / fps, frames * dt) if v > 0 and v / dt == frames), None)
    if value is None:
        value = frames / fps
        for _ in range(64):  # a few ulps away, w / dt is exactly the count
            value = float(np.nextafter(value, math.inf if value / dt < frames else 0.0))
            if value / dt == frames:
                break
    if value == nominal:
        return f"self.wait({_num(value)})"
    return f"self.wait({_num(value)})  # {frames} frames at {fps} fps"


def _time(value: float) -> str:
    """A duration: rounded to 1e-9 s, so 2.4 - 2.0 reads 0.4 (frames do not change)."""
    return _num(round(value, 9))


def _num(value: float) -> str:
    """Floats exactly (repr), written as floats: 1.0, 0.25, 14.222222222222221."""
    return repr(float(value))


def _camera_orientation(camera) -> str:
    """``set_camera_orientation`` with the angles as the editor applies them (``value * DEGREES``)."""
    angles = ", ".join(
        f"{name}={_num(getattr(camera, name))} * DEGREES" for name in ("phi", "theta", "gamma")
    )
    return f"self.set_camera_orientation({angles})"


# -- exact code -----------------------------------------------------------------------------------------


def _exact(project: Project, scene_name: str, problems: list[str], code_cache_dir: str | None) -> str:
    reasons = "\n".join(f"#   - {p}" for p in problems)
    data = json.dumps(json.loads(project.model_dump_json(by_alias=True)), indent=1)
    if "'''" in data:
        data = data.replace("'''", "\\'\\'\\'")
    cache = f"\n    code_cache_dir = {code_cache_dir!r}" if code_cache_dir else ""
    return (
        '"""Generated by Manim Studio (exact form, ADR 0031).\n\n'
        "Plays the project through Manim Studio's evaluator, so it needs the manim_studio\n"
        "package installed. Render with: manim render <this file> " + scene_name + '\n"""\n\n'
        "# Not written as plain self.play code because:\n" + reasons + "\n\n"
        "from manim_studio.manim_scene import StudioScene, configure\n\n"
        f"PROJECT = r'''{data}'''\n\n"
        "configure(PROJECT)\n\n\n"
        f"class {scene_name}(StudioScene):\n"
        f"    project_json = PROJECT{cache}\n"
    )
