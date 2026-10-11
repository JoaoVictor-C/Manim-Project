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
from .schema import (
    CODE_TYPES,
    DIRECTIONS,
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
RESERVED = set(STAR) | set(dir(__builtins__)) | {"self", "np", "math"}


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

    for layer in project.layers:
        if layer.parent_id is not None:
            out.append(f"{name(layer)}: parts and objects on axes are evaluated as one object")
            continue
        if layer.spec.type in CODE_TYPES:
            out.append(f"{name(layer)}: code layers are rendered by the editor")
        if layer.tracks:
            out.append(f"{name(layer)}: keyframes")
        base = layer.base
        if layer.clips and (base.rotation != 0 or base.scale != 1 or tuple(base.anchor) != (0.0, 0.0)):
            out.append(f"{name(layer)}: clips on a turned or scaled object animate before its transform")
        if any(c.info.category == "motion" and c.params.get("rotate") == "along" for c in layer.clips):
            out.append(f"{name(layer)}: turning along a path")
        if layer.id in morph_targets and (layer.lifetime.in_ is not None or layer.lifetime.out is not None):
            out.append(f"{name(layer)}: a morph target with its own lifetime")
        if layer.spec.type in plugins.TYPES:
            out.append(f"{name(layer)}: a plugin object")
        elif layer.spec.type in TRACE_TYPES or layer.spec.type in plugins.SIMULATIONS:
            out.append(f"{name(layer)}: a simulated layer")
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


class _Readable:
    def __init__(self, project: Project, scene_name: str) -> None:
        self.project = project
        self.scene_name = scene_name
        self.names = _variable_names(project)
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
            "",
        ]
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
        lines += ["", f"class {self.scene_name}(Scene):", "    def construct(self):"]
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
        for index, layer in enumerate(self.project.layers):
            var = self.names[layer.id]
            out.append(f"{var} = {_construct(layer.spec)}")
            out += [f"{var}.{call}" for call in _style_calls(layer.spec.style)]
            out.append(f"{var}.move_to(ORIGIN)")
            out += [f"{var}.{call}" for call in _transform_calls(layer)]
            out.append(f"{var}.set_z_index({index})  # the layer order")
        return out

    # timeline

    def _timeline(self) -> list[str]:
        events: list[tuple[float, int, list[str]]] = []
        for t, layer_id, what in _lifetime_events(self.project):
            order = 0 if what == "remove" else 1
            events.append((t, order, [f"self.{what}({self.names[layer_id]})"]))
        for start, end, members in _clusters(self.project):
            events.append((start, 2, self._play(start, end, members)))
        out, cursor = [], 0.0
        for t, _, lines in sorted(events, key=lambda e: (e[0], e[1])):
            if t > cursor + EPS:
                out.append(f"self.wait({_time(t - cursor)})")
                cursor = t
            out += lines
            if lines[0].startswith("self.play"):
                cursor = max(cursor, next(end for s, end, _ in _clusters(self.project) if abs(s - t) < EPS))
        if self.project.canvas.duration > cursor + EPS:
            out.append(f"self.wait({_time(self.project.canvas.duration - cursor)})")
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
        args = [var]
        info = clip.info
        if info.category == "morph":
            args.append(self.names[clip.to_layer])
        if info.category == "motion":
            args.append(self._path(clip.params["path"]))
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
        return f"{name}({', '.join([*args, *(f'{k}={v}' for k, v in kwargs.items())])})"

    def _path(self, layer_id: str) -> str:
        """The path layer's rest shape, built afresh (its own clips must not move the path)."""
        layer = self.project.layer(layer_id)
        shape = _construct(layer.spec)
        calls = [*_style_calls(layer.spec.style), "move_to(ORIGIN)", *_transform_calls(layer)]
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
    params = dict(spec.params)
    args = []
    if spec.type in TEXT_TYPES:
        args.append(repr(params.pop("text", "")))
    elif spec.type in ("ImageMobject", "SVGMobject"):
        args.append(repr(params.pop("path")))
    points = {p.name for p in adapter.MOBJECT_PARAMS.get(spec.type, ()) if p.kind == "point"}
    for key, value in params.items():
        args.append(f"{key}={_vector(value) if key in points else repr(value)}")
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


def _transform_calls(layer: Layer) -> list[str]:
    base = layer.base
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


def _time(value: float) -> str:
    """A duration: rounded to 1e-9 s, so 2.4 - 2.0 reads 0.4 (frames do not change)."""
    return _num(round(value, 9))


def _num(value: float) -> str:
    """Floats exactly (repr), written as floats: 1.0, 0.25, 14.222222222222221."""
    return repr(float(value))


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
