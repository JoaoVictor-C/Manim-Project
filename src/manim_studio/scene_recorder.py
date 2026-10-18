"""Records what a Manim scene does, for the scene importer (P10.3, ADR 0053).

It runs user code, so it never runs inside the editor (ADR 0019). Entry points:

* ``python -m manim_studio.scene_recorder --cache-dir DIR`` - a single-use *warm spare*:
  imports Manim, prints ``{"ready": true}``, reads ONE job (a JSON line
  ``{"file": ..., "scene": ... or null, "output": ...}``) from stdin, records the scene, writes
  the recording (JSON) to ``output`` and prints ``{"done": true}`` or
  ``{"error": "...", "line": n}``. With ``--file`` (and ``--scene``, ``--output``) the job is
  taken from the arguments instead (the ``import`` command).
* ``record(source, filename, scene)`` - the same in this process (tests).

The scene is really played - ``add``, ``remove``, ``play`` and ``wait`` run as in Manim, so every
mobject is in exactly the state later code sees - but nothing is drawn and no file is written:
a renderer that only keeps the clock replaces Manim's, and each ``play`` advances once, to its end
(Manim's ``skip_animations``). What is recorded is plain data (``core/scene_import.py`` turns it
into layers and clips without Manim):

* ``states``: every distinct drawn piece (a leaf of ``family_members_with_points()``), as a
  shape piece (``adapter.piece_data``: points, colours, widths);
* ``steps``: in time order - ``frame`` (what is drawn, in drawing order, when it changed between
  plays), ``add`` (objects the code added), ``play`` (each animation with its start, run time,
  the Studio clip kind, ease and params it maps to, and its target as it was when it began and
  ended; what is drawn before, during and after), ``wait``, ``sound``, ``subcaption``;
* ``candidates``: objects that a built-in Studio object rebuilds exactly (verified here, with
  Manim: the same pieces, points within ``TOLERANCE``, the same colours);
* ``problems``: what cannot become layers and clips (updaters, cameras, custom animations...),
  with the line of the user's code.
"""

from __future__ import annotations

import argparse
import builtins
import contextlib
import hashlib
import inspect
import json
import logging
import math
import os
import sys
import time
import traceback
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

VERSION = 1
TIME_LIMIT = 60.0  # seconds a recording may take before the editor stops it
TOLERANCE = 1e-6  # Manim units: a rebuilt object's points must be this close
COLOUR_TOLERANCE = 1e-9

# Manim animation class -> the Studio clip kind it is (schema.CLIP_KIND_INFO).
KINDS: dict[str, str] = {
    "Create": "Create",
    "Uncreate": "Uncreate",
    "Write": "Write",
    "Unwrite": "Unwrite",
    "DrawBorderThenFill": "DrawBorderThenFill",
    "FadeIn": "FadeIn",
    "FadeOut": "FadeOut",
    "GrowFromCenter": "GrowFromCenter",
    "SpinInFromNothing": "SpinInFromNothing",
    "GrowFromEdge": "GrowFromEdge",
    "SpiralIn": "SpiralIn",
    "AddTextLetterByLetter": "AddTextLetterByLetter",
    "RemoveTextLetterByLetter": "RemoveTextLetterByLetter",
    "ShrinkToCenter": "ShrinkToCenter",
    "Indicate": "Indicate",
    "Wiggle": "Wiggle",
    "ApplyWave": "ApplyWave",
    "Circumscribe": "Circumscribe",
    "Flash": "Flash",
    "FocusOn": "FocusOn",
    "Transform": "Transform",
    "ReplacementTransform": "Transform",
    "TransformFromCopy": "Transform",
    "ClockwiseTransform": "ClockwiseTransform",
    "CounterclockwiseTransform": "CounterclockwiseTransform",
    "FadeTransform": "FadeTransform",
    "FadeTransformPieces": "FadeTransformPieces",
    "TransformMatchingShapes": "TransformMatchingShapes",
}
MORPHS = frozenset(
    {
        "Transform",
        "ReplacementTransform",
        "TransformFromCopy",
        "ClockwiseTransform",
        "CounterclockwiseTransform",
        "FadeTransform",
        "FadeTransformPieces",
        "TransformMatchingShapes",
    }
)
# Animations that turn an object into a changed copy of itself, interpolating its points in a
# straight line: keyframes when the change is a move, a uniform scale or a fade (the importer checks).
SELF_MOVES = frozenset(
    {
        "_MethodAnimation",  # mobject.animate....
        "MoveToTarget",
        "ApplyMethod",
        "ApplyFunction",
        "ApplyMatrix",
        "ApplyPointwiseFunction",
        "ScaleInPlace",
        "FadeToColor",
        "Restore",
    }
)
ROTATIONS = frozenset({"Rotate", "Rotating"})
LEAFWISE = frozenset({"Create", "Uncreate", "DrawBorderThenFill", "FadeIn", "FadeOut"})
GROUPS = frozenset({"AnimationGroup", "Succession", "LaggedStart", "LaggedStartMap"})
TARGET_ARG = {"Flash": "point", "FocusOn": "focus_point", "Circumscribe": "mobject"}
# Keyword arguments that are not clip params: timing, the ease, Manim's own bookkeeping.
NOT_PARAMS = frozenset(
    {
        "self",
        "run_time",
        "rate_func",
        "name",
        "use_override",
        "suspend_mobject_updating",
        "lag_ratio",
        "replace_mobject_with_target_in_scene",
        "mobject",
        "mobjects",
        "vmobject",
        "target_mobject",
        "point",
        "focus_point",
        "text",
        "shapes",
        "kwargs",
        "args",
    }
)
SHAPE_CLASSES = {"Rectangle": "rectangle", "Circle": "circle"}  # Circumscribe's shape choice
# Built-in Studio types an object may be rebuilt as (verified), and the params that carry its size.
CANDIDATE_TYPES = {
    "Circle": ("radius",),
    "Dot": ("radius",),
    "Square": ("side_length",),
    "Rectangle": ("width", "height"),
    "Triangle": (),
    "Star": ("outer_radius",),
    "Line": (),
    "Arrow": (),
    "Text": (),
    "MathTex": (),
    "Tex": (),
}
CAMERA_SCENES = ("MovingCameraScene", "ThreeDScene", "ZoomedScene", "VectorScene", "SpecialThreeDScene")
SAMPLES = [i / 20 for i in range(-5, 26)]  # where two eases are compared: a little past each end


class RecordError(Exception):
    """The scene could not be recorded; ``line`` is in the user's file (None if unknown)."""

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


# -- entry points ---------------------------------------------------------------------------------


def record_file(path: str | Path, scene: str | None = None, sample_fps: int | None = None) -> dict:
    """Record the scene ``scene`` (or the file's only scene) of the Python file at ``path``."""
    path = Path(path).resolve()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RecordError(f"cannot read {path.name}: {exc}") from exc
    return record(source, str(path), scene, sample_fps)


def record(source: str, filename: str, scene: str | None = None, sample_fps: int | None = None) -> dict:
    """Run ``source`` (named ``filename`` in tracebacks) and record its scene ``scene``.

    ``sample_fps`` (tests) also plays every animation frame by frame at that rate and keeps what
    is drawn at each frame (``samples``), as Manim would draw it.
    """
    import manim as m

    folder = str(Path(filename).parent)
    cwd, path = os.getcwd(), list(sys.path)
    recorder = _Recorder(filename, sample_fps)
    try:
        if os.path.isdir(folder):
            os.chdir(folder)  # files the scene opens are found where the scene is
            sys.path.insert(0, folder)
        with m.tempconfig({}), _patched(recorder):
            namespace = _run_module(source, filename)
            scene_class = _pick_scene(namespace, scene)
            recorder.read_config()
            m.config.disable_caching = True
            m.config.write_to_movie = False
            m.config.save_last_frame = False
            m.config.progress_bar = "none"
            m.config.preview = False
            if sample_fps:
                m.config.frame_rate = sample_fps
            recorder.run(scene_class)
    finally:
        os.chdir(cwd)
        sys.path[:] = path
    return recorder.result()


def _run_module(source: str, filename: str) -> dict:
    namespace: dict[str, Any] = {
        "__name__": "__manim_studio_import__",
        "__file__": filename,
        "__builtins__": builtins,
    }
    try:
        code = compile(source, filename, "exec")
    except SyntaxError as exc:
        raise RecordError(f"SyntaxError: {exc.msg}", exc.lineno) from exc
    try:
        exec(code, namespace)  # the user's own code, in this throwaway process (ADR 0019)
    except Exception as exc:
        raise RecordError(_message(exc), _user_line(exc, filename)) from exc
    return namespace


def _pick_scene(namespace: dict, name: str | None) -> type:
    import manim as m

    scenes = {
        value.__name__: value
        for value in namespace.values()
        if isinstance(value, type)
        and issubclass(value, m.Scene)
        and value.__module__ == namespace["__name__"]
    }
    if name is not None:
        if name not in scenes:
            found = ", ".join(sorted(scenes)) or "none"
            raise RecordError(f"the file has no scene {name!r} (found: {found})")
        return scenes[name]
    if len(scenes) != 1:
        found = ", ".join(sorted(scenes)) or "none"
        raise RecordError(f"choose the scene to import (found: {found})")
    return next(iter(scenes.values()))


def _message(exc: BaseException) -> str:
    lines = [line for line in str(exc).splitlines() if line.strip()]
    return f"{type(exc).__name__}: {lines[0] if lines else ''}".rstrip(": ")[:300]


def _user_line(exc: BaseException, filename: str) -> int | None:
    lines = [f.lineno for f in traceback.extract_tb(exc.__traceback__) if f.filename == filename]
    return lines[-1] if lines else None


@contextmanager
def _patched(recorder: _Recorder):
    """Remember each animation's own arguments and where updaters are added, then put Manim back."""
    from manim import Mobject
    from manim.animation.animation import Animation

    original_new = Animation.__dict__["__new__"]
    original_add_updater = Mobject.add_updater

    def new(cls, *args, **kwargs):
        anim = original_new.__func__(cls, *args, **kwargs)
        if isinstance(anim, Animation) and "_studio_call" not in anim.__dict__:
            anim.__dict__["_studio_call"] = (args, dict(kwargs))
        return anim

    def add_updater(self, *args, **kwargs):
        recorder.updater_lines.setdefault(id(self), recorder.line())
        return original_add_updater(self, *args, **kwargs)

    Animation.__new__ = staticmethod(new)
    Mobject.add_updater = add_updater
    try:
        yield
    finally:
        Animation.__new__ = original_new
        Mobject.add_updater = original_add_updater


# -- the recorder ---------------------------------------------------------------------------------


class _Recorder:
    def __init__(self, filename: str, sample_fps: int | None = None) -> None:
        import manim as m

        self.filename = filename
        self.sample_fps = sample_fps
        self.manim_dir = str(Path(m.__file__).parent)
        self.keep: list[Any] = []  # every mobject named: their ids stay unique for the whole run
        self.leaf_names: dict[int, str] = {}
        self.object_names: dict[int, str] = {}
        self.objects: dict[str, dict] = {}
        self.watched: dict[int, Any] = {}  # objects the code added or animated
        self.states: dict[str, dict] = {}
        self.state_names: dict[bytes, str] = {}
        self.bad_states: dict[bytes, str] = {}
        self.candidates: dict[str, dict | None] = {}
        self.steps: list[dict] = []
        self.samples: list[dict] = []
        self.problems: list[dict] = []
        self.notes: list[str] = []
        self._problem_keys: set[str] = set()
        self.updater_lines: dict[int, int | None] = {}
        self.time = 0.0
        self.last_draw: list | None = None
        self.play_start = 0.0
        self.canvas: dict[str, Any] = {}
        self.scene_name = ""
        self.background = None

    # -- the scene -----------------------------------------------------------------------------

    def read_config(self) -> None:
        """The canvas the scene's own config (``config.pixel_width = ...`` in the file) asks for."""
        import manim as m

        config = m.config
        fps = float(config.frame_rate)
        self.canvas = {
            "width_px": int(config.pixel_width),
            "height_px": int(config.pixel_height),
            "fps": max(1, round(fps)),
            "background": m.ManimColor(config.background_color).to_hex(),
            "frame_height": float(config.frame_height),
        }
        if abs(fps - round(fps)) > 1e-9:
            self.notes.append(f"the scene's frame rate {fps:g} is rounded to {round(fps)} frames per second")
        expected = config.frame_height * config.pixel_width / config.pixel_height
        if abs(config.frame_width - expected) > 1e-6:
            self.notes.append(
                f"the scene's frame is {config.frame_width:g} units wide, not {expected:g} "
                "(its pixel shape): Manim Studio keeps the pixel shape"
            )

    def run(self, scene_class: type) -> None:
        import manim as m

        self.scene_name = scene_class.__name__
        for name in CAMERA_SCENES:
            base = getattr(m, name, None)
            if base is not None and issubclass(scene_class, base):
                self.problem(f"{scene_class.__name__} is a {name}: its camera is not the editor's", None)
        recorder = self
        camera = inspect.signature(scene_class.__init__).parameters.get("camera_class")
        camera_class = camera.default if camera is not None and isinstance(camera.default, type) else None
        renderer = _renderer_class()(
            recorder, camera_class=camera_class, skip_animations=self.sample_fps is None
        )

        class Recorded(scene_class):  # Manim's own add/play/wait run; these only watch them
            def add(self, *mobjects):
                recorder.on_add(mobjects)
                return super().add(*mobjects)

            def remove(self, *mobjects):
                recorder.on_remove(mobjects)
                return super().remove(*mobjects)

            def add_sound(self, sound_file, time_offset=0, gain=None, **kwargs):
                recorder.on_sound(sound_file, time_offset, gain)

            def add_subcaption(self, content, duration=1, offset=0):
                recorder.on_subcaption(content, duration, offset)

        Recorded.__name__ = Recorded.__qualname__ = scene_class.__name__
        Recorded.__module__ = scene_class.__module__
        try:
            scene = Recorded(renderer=renderer)
            self.background = m.ManimColor(scene.camera.background_color).to_hex()
            scene.setup()
            scene.construct()
            scene.tear_down()
        except RecordError:
            raise
        except Exception as exc:
            raise RecordError(_message(exc), _user_line(exc, self.filename)) from exc
        self.emit_frame(scene)
        if self.background is not None:
            end = m.ManimColor(scene.camera.background_color).to_hex()
            if end != self.background:
                self.problem("the background colour changes during the scene", None)
            self.canvas["background"] = self.background

    def result(self) -> dict:
        return {
            "version": VERSION,
            "file": self.filename,
            "scene": self.scene_name,
            "canvas": self.canvas,
            "duration": self.time,
            "states": self.states,
            "objects": self.objects,
            "candidates": [c for c in self.candidates.values() if c is not None],
            "steps": self.steps,
            "problems": self.problems,
            "notes": self.notes,
            **({"samples": self.samples} if self.sample_fps else {}),
        }

    # -- naming ------------------------------------------------------------------------------------

    def line(self) -> int | None:
        """The line of the user's file running now (its innermost frame)."""
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code.co_filename == self.filename:
                return frame.f_lineno
            frame = frame.f_back
        return None

    def problem(self, what: str, line: int | None) -> None:
        key = f"{line}:{what}"
        if key not in self._problem_keys:
            self._problem_keys.add(key)
            self.problems.append({"line": line, "what": what})

    def leaf(self, mob) -> str:
        name = self.leaf_names.get(id(mob))
        if name is None:
            name = self.leaf_names[id(mob)] = f"p{len(self.leaf_names) + 1}"
            self.keep.append(mob)
        return name

    def object(self, mob, line: int | None = None) -> str:
        name = self.object_names.get(id(mob))
        if name is None:
            name = self.object_names[id(mob)] = f"o{len(self.object_names) + 1}"
            self.keep.append(mob)
            self.objects[name] = {"class": type(mob).__name__, "line": line, "name": self.variable(mob)}
        return name

    def variable(self, mob) -> str | None:
        """The name the user's code gives ``mob`` (a local variable of its running function)."""
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code.co_filename == self.filename:
                for key, value in frame.f_locals.items():
                    if value is mob and key != "self" and not key.startswith("_"):
                        return key
            frame = frame.f_back
        return None

    def state(self, leaf) -> str:
        """The name of what ``leaf`` draws now (one name per distinct piece)."""
        import numpy as np

        digest = hashlib.blake2b(digest_size=16)
        arrays = [leaf.points]
        for attr in ("fill_rgbas", "stroke_rgbas", "background_stroke_rgbas", "sheen_direction"):
            arrays.append(getattr(leaf, attr, None))
        for array in arrays:
            if array is None:
                digest.update(b"-")
                continue
            array = np.ascontiguousarray(array, dtype=float)
            digest.update(repr(array.shape).encode())
            digest.update(array.tobytes())
        extra = (
            type(leaf).__name__,
            getattr(leaf, "stroke_width", None),
            getattr(leaf, "background_stroke_width", None),
            getattr(leaf, "sheen_factor", None),
            str(getattr(leaf, "joint_type", None)),
            str(getattr(leaf, "cap_style", None)),
            getattr(leaf, "z_index", 0),
            getattr(leaf, "shade_in_3d", False),
        )
        digest.update(repr(extra).encode())
        key = digest.digest()
        name = self.state_names.get(key)
        if name is not None:
            return name
        from .core import adapter

        name = f"s{len(self.state_names) + 1}"
        try:
            self.states[name] = adapter.piece_data(leaf)
        except ValueError as exc:
            self.problem(f"a {type(leaf).__name__} cannot become a layer: {exc}", self.line())
            self.states[name] = {
                "points": [[0.0, 0.0]],
                "fill": [0, 0, 0, 0],
                "stroke": [0, 0, 0, 0],
                "stroke_width": 0.0,
            }
        self.state_names[key] = name
        return name

    def pairs(self, mob) -> list[list[str]]:
        """``[leaf, state]`` for each drawn piece of ``mob``, in drawing order."""
        return [[self.leaf(x), self.state(x)] for x in mob.family_members_with_points()]

    def observe(self, mob, line: int | None = None) -> dict:
        """An object as it is now: its name, its pieces, and a built-in object that rebuilds it."""
        name = self.object(mob, line)
        pairs = self.pairs(mob)
        self.candidate(mob, pairs)
        return {"object": name, "leaves": pairs}

    def candidate(self, mob, pairs: list[list[str]]) -> None:
        """Find the built-in object rebuilding ``mob`` (and each member of a group: one animated on
        its own becomes a layer of its own)."""
        import manim as m

        key = "|".join(f"{a}:{b}" for a, b in pairs)
        if pairs and key not in self.candidates:
            self.candidates[key] = _candidate(mob, pairs)
        if type(mob) in (m.VGroup, m.Group):
            for sub in mob.submobjects:
                self.candidate(sub, self.pairs(sub))

    def draw(self, scene) -> list[list[str]]:
        """What Manim draws now, in its drawing order (the z-index sort included)."""
        from manim.utils.family import extract_mobject_family_members
        from manim.utils.iterables import list_update

        mobjects = extract_mobject_family_members(
            list_update(scene.mobjects, scene.foreground_mobjects),
            use_z_index=scene.renderer.camera.use_z_index,
            only_those_with_points=True,
        )
        return [[self.leaf(x), self.state(x)] for x in mobjects]

    def check(self, scene) -> None:
        """Updaters make every frame depend on the one before: they cannot become clips."""
        if scene.updaters:
            self.problem(
                "the scene has updaters (self.add_updater): frames depend on the frames before", None
            )
        for top in scene.mobjects:
            for mob in top.get_family():
                if mob.updaters:
                    line = self.updater_lines.get(id(mob))
                    self.problem(
                        f"a {type(mob).__name__} has updaters (add_updater, always_redraw): it is redrawn "
                        "from the frames before",
                        line,
                    )

    def watch(self, mob) -> None:
        self.watched.setdefault(id(mob), mob)

    def emit_frame(self, scene) -> None:
        """What is drawn now, when it changed since the last step (code between plays)."""
        self.check(scene)
        draw = self.draw(scene)
        if draw != self.last_draw:
            self.steps.append({"type": "frame", "t": self.time, "draw": draw})
            self.last_draw = draw
        drawn = {leaf for leaf, _ in draw}
        for mob in list(self.watched.values()):  # a changed object may still be a built-in one
            leaves = mob.family_members_with_points()
            if leaves and all(self.leaf_names.get(id(x)) in drawn for x in leaves):
                self.observe(mob)

    # -- what the scene does -----------------------------------------------------------------

    def from_user(self) -> bool:
        """Was the scene method running now called by the user's code (not by Manim itself)?"""
        frame = sys._getframe(3)  # this, on_add, Recorded.add, the caller
        name = frame.f_code.co_filename if frame is not None else ""
        return not name.startswith(self.manim_dir) and name != __file__

    def on_add(self, mobjects) -> None:
        from manim import Mobject

        if not self.from_user():
            return
        line = self.line()
        seen = []
        for mob in mobjects:
            if isinstance(mob, Mobject):
                seen.append(self.observe(mob, line))
                self.watch(mob)
        self.steps.append({"type": "add", "t": self.time, "line": line, "objects": seen})

    def on_remove(self, mobjects) -> None:
        from manim import Mobject

        if not self.from_user():
            return
        line = self.line()
        seen = [self.observe(mob, line) for mob in mobjects if isinstance(mob, Mobject)]
        self.steps.append({"type": "remove", "t": self.time, "line": line, "objects": seen})

    def on_sound(self, sound_file, time_offset, gain) -> None:
        path = Path(str(sound_file))
        if not path.is_absolute():
            path = Path(self.filename).parent / path
        self.steps.append(
            {
                "type": "sound",
                "t": self.time + float(time_offset),
                "path": str(path),
                "gain": float(gain or 0.0),
                "exists": path.is_file(),
                "line": self.line(),
            }
        )

    def on_subcaption(self, content, duration, offset) -> None:
        self.steps.append(
            {
                "type": "subcaption",
                "t": self.time + float(offset),
                "duration": float(duration),
                "text": str(content),
                "line": self.line(),
            }
        )

    def play(self, renderer, scene, args, kwargs) -> None:
        import manim as m

        line = self.line()
        self.emit_frame(scene)
        scene.compile_animation_data(*args, **kwargs)
        animations = list(scene.animations)
        duration = float(scene.duration)
        start = self.time
        if len(animations) == 1 and type(animations[0]) is m.Wait:
            if not getattr(animations[0], "is_static_wait", False):  # updaters move things: run them
                scene.begin_animations()
                self.play_start = start
                scene.play_internal()
            elif self.sample_fps:
                self.samples.append(self.picture(scene, start))
            self.advance(renderer, duration)
            self.steps.append({"type": "wait", "t": start, "duration": duration, "line": line})
            renderer.num_plays += 1
            self.emit_frame(scene)
            return
        self.check(scene)
        leaves: list[dict] = []
        for anim in animations:
            self.flatten(anim, 0.0, float(anim.run_time), 0.0, leaves, line)
        before = self.draw(scene)
        scene.begin_animations()
        during = [leaf for leaf, _ in self.draw(scene)]
        self.play_start = start
        scene.play_internal()
        self.advance(renderer, duration)
        after = self.draw(scene)
        self.steps.append(
            {
                "type": "play",
                "t": start,
                "duration": duration,
                "line": line,
                "animations": leaves,
                "before": before,
                "during": during,
                "after": after,
            }
        )
        self.last_draw = after
        renderer.num_plays += 1

    def advance(self, renderer, duration: float) -> None:
        renderer.time += duration
        self.time = renderer.time

    def sample(self, scene, t: float) -> None:
        if self.sample_fps:
            self.samples.append(self.picture(scene, self.play_start + t))

    def picture(self, scene, t: float) -> dict:
        """A frame as Manim draws it (tests): its pieces and its pixels (a numpy array, not JSON)."""
        from manim.utils.iterables import list_update

        camera = scene.renderer.camera
        camera.reset()
        camera.capture_mobjects(list_update(scene.mobjects, scene.foreground_mobjects))
        return {"t": t, "draw": self.draw(scene), "pixels": camera.pixel_array.copy()}

    # -- animations ------------------------------------------------------------------------------

    def flatten(self, anim, offset: float, duration: float, begin: float, out: list, line) -> None:
        """Each animation inside groups, with its own start and run time inside the play."""
        import manim as m

        name = type(anim).__name__
        if type(anim) is m.Wait:
            return
        if name in GROUPS and getattr(m, name, None) is type(anim):
            if not _same_function(anim.rate_func, m.rate_functions.linear):
                self.problem(f"a {name} with its own rate function (the animations inside are warped)", line)
            ends = anim.max_end_time
            factor = duration / ends if ends > 0 else 0.0
            succession = isinstance(anim, m.Succession)
            for row in anim.anims_with_timings:
                sub, s, e = row["anim"], float(row["start"]), float(row["end"])
                at = offset + s * factor
                self.flatten(sub, at, (e - s) * factor, at if succession else begin, out, line)
            return
        out.append(self.leaf_animation(anim, offset, duration, begin, line))

    def leaf_animation(self, anim, start: float, duration: float, begin: float, line) -> dict:
        import manim as m
        from manim.animation.transform import _MethodAnimation

        cls = type(anim)
        name = cls.__name__
        known = getattr(m, name, None) is cls or (name == "_MethodAnimation" and cls is _MethodAnimation)
        record: dict[str, Any] = {
            "class": "animate" if name == "_MethodAnimation" else name,
            "start": start,
            "duration": duration,
            "begin": begin,
            "line": line,
            "problems": [],
        }
        problems = record["problems"]
        args, kwargs = anim.__dict__.get("_studio_call", ((), {}))
        bound = _bind(cls, args, kwargs)
        if not known:
            problems.append(f"{name} is a custom animation: Manim Studio cannot redo what it does")
            record["kind"] = None
        elif name in KINDS:
            record["kind"] = KINDS[name]
        elif name in SELF_MOVES:
            record["kind"] = "keys"
        elif name in ROTATIONS:
            record["kind"] = "rotate"
        else:
            problems.append(f"{name} is not an animation Manim Studio has")
            record["kind"] = None
        target = anim.mobject
        if name in TARGET_ARG:
            target = bound.get(TARGET_ARG[name])
        elif name in MORPHS:
            target = bound.get("mobject")
        to = bound.get("target_mobject") if name in MORPHS else None
        if not isinstance(target, m.Mobject):
            problems.append(f"{name} acts on a point, not an object")
            target = None
        elif isinstance(target, m.ValueTracker):
            problems.append("a ValueTracker is animated: its value drives other objects frame by frame")
            target = None
        if name in MORPHS and not isinstance(to, m.Mobject):
            problems.append(f"{name} has no object to turn into")
            to = None
        if target is not None:
            record["target"] = self.object(target, line)
            self.watch(target)
        if to is not None:
            record["to"] = self.object(to, line)
            self.watch(to)
        if name == "TransformFromCopy":
            record["copy"] = True
        if record["kind"] in KINDS.values() and target is not None:
            self.convert(anim, record, bound, kwargs, target, to)
        elif record["kind"] == "keys":
            self.keyed(anim, record)
        elif record["kind"] == "rotate":
            self.rotation(anim, record)
        self.hook(anim, record, target, to)
        for what in problems:
            self.problem(what, line)
        return record

    def convert(self, anim, record: dict, bound: dict, kwargs: dict, target, to) -> None:
        """The clip's params and ease, checked against the animation Studio would make."""
        from .core.schema import CLIP_KIND_INFO, Easing, clip_params

        kind = record["kind"]
        problems = record["problems"]
        registered = {p.name: p for p in clip_params(kind)}
        params: dict[str, Any] = {}
        for key, value in bound.items():
            if key in NOT_PARAMS or value is None:
                continue
            converted, why = _param(key, value, registered.get(key))
            if why is not None:
                problems.append(f"{record['class']}'s {key}: {why}")
            elif converted is not None:
                params[key] = converted
        if record["class"] in ("FadeIn", "FadeOut") and ("scale" in params or "target_position" in bound):
            record["leafwise"] = False
        if record["class"] == "Wiggle" and len(target.family_members_with_points()) > 1:
            problems.append(
                "Wiggle on several pieces turns each about a centre that moves as the others turn: "
                "Manim Studio turns them about a fixed one"
            )
        given = kwargs.get("rate_func")
        tries = [(_ease_of(given) if given is not None else None, given is not None)]
        tries.append((_ease_of(anim.rate_func), True))
        info = CLIP_KIND_INFO[kind]
        chosen = None
        for ease, explicit in tries:
            if explicit and ease is None:
                continue
            probe = self.probe(kind, ease, params, target, to)
            if probe is None:
                continue
            if _same_rate(anim, probe, info.clamps_alpha):
                chosen = (ease, probe)
                break
        if chosen is None:
            problems.append(f"{record['class']}'s rate function cannot be written as a Studio ease")
            return
        ease, probe = chosen
        if info.clamps_alpha and _overshoots(anim.rate_func):
            problems.append(
                f"{record['class']}'s ease goes past its ends: Manim Studio keeps content and emphasis "
                "clips within them"
            )
        if not math.isclose(float(probe.lag_ratio), float(anim.lag_ratio), abs_tol=1e-12):
            params["lag_ratio"] = float(anim.lag_ratio)
        record["params"] = params
        record["ease"] = Easing(**ease).model_dump(exclude_none=True) if ease is not None else None
        record["lag_ratio"] = float(anim.lag_ratio)
        # Each piece of the target animated on its own, by lag_ratio (Animation.get_sub_alpha): the
        # clip can be split over parts of a group, each part timed as in the whole.
        reverse = getattr(anim, "reverse", False)
        leafwise = record["class"] in LEAFWISE or (record["class"] == "Write" and not reverse)
        record["leafwise"] = record.get("leafwise", True) and leafwise and _clamps_input(anim.rate_func)
        if record.get("copy") and not _symmetric(anim.rate_func):
            problems.append("TransformFromCopy with an ease that is not symmetric plays it backwards")
        if kind == "Write" and reverse:
            problems.append("Write(reverse=True) is not a Studio clip")

    def probe(self, kind: str, ease: dict | None, params: dict, target, to):
        """The animation Studio makes for this clip (not begun), or None when it cannot be made."""
        from .core import adapter
        from .core.schema import Easing

        try:
            return adapter.make_animation(
                kind,
                target.copy(),
                Easing(**ease) if ease is not None else None,
                params,
                to.copy() if to is not None else None,
            )
        except Exception:  # params Manim refuses: reported as not convertible
            return None

    def keyed(self, anim, record: dict) -> None:
        problems = record["problems"]
        if getattr(anim, "path_arc", 0):
            problems.append(f"{record['class']} moves along arcs (path_arc): keys move in straight lines")
        if getattr(anim, "path_arc_centers", None) is not None:
            problems.append(f"{record['class']} moves along circles: keys move in straight lines")
        if anim.lag_ratio:
            problems.append(f"{record['class']} with a lag_ratio moves its pieces one after another")
        if anim.reverse_rate_function:
            problems.append(f"{record['class']} with a reversed rate function")
        ease = _ease_of(anim.rate_func)
        if ease is None:
            problems.append(f"{record['class']}'s rate function cannot be written as a Studio ease")
        record["ease"] = ease

    def rotation(self, anim, record: dict) -> None:
        import numpy as np

        problems = record["problems"]
        axis = np.asarray(anim.axis, dtype=float)
        if np.linalg.norm(axis[:2]) > 1e-9 or axis[2] == 0:
            problems.append(f"{record['class']} turns about an axis other than OUT: the scene is flat")
        else:
            record["angle"] = math.degrees(float(anim.angle)) * (1.0 if axis[2] > 0 else -1.0)
        if anim.lag_ratio:
            problems.append(f"{record['class']} with a lag_ratio turns its pieces one after another")
        if anim.reverse_rate_function:
            problems.append(f"{record['class']} with a reversed rate function")
        ease = _ease_of(anim.rate_func)
        if ease is None:
            problems.append(f"{record['class']}'s rate function cannot be written as a Studio ease")
        record["ease"] = ease

    def hook(self, anim, record: dict, target, to) -> None:
        """Snapshot the target when the animation really begins and ends (in a Succession, when
        its turn comes)."""
        own_begin, own_finish = anim.begin, anim.finish
        recorder = self

        def begin():
            if target is not None:
                record["at_begin"] = recorder.observe(target)["leaves"]
                record["flat"] = _flat(target)
                if record.get("kind") == "rotate":
                    record["about"] = _about(anim, target)
            if to is not None:
                record["to_at_begin"] = recorder.observe(to)["leaves"]
                record["to_flat"] = _flat(to)
            own_begin()

        def finish():
            own_finish()
            if target is not None:
                record["at_finish"] = recorder.pairs(target)
                record["finish_flat"] = _flat(target)
            if to is not None:
                record["to_at_finish"] = recorder.pairs(to)
                record["to_finish_flat"] = _flat(to)

        anim.begin, anim.finish = begin, finish


def _renderer_class():
    from manim.renderer.cairo_renderer import CairoRenderer

    class RecordingRenderer(CairoRenderer):
        """Keeps the clock and hands plays to the recorder: nothing is drawn or written."""

        def __init__(self, recorder: _Recorder, **kwargs) -> None:
            super().__init__(**kwargs)
            self.recorder = recorder

        def init_scene(self, scene, session_spec, file_writer_settings) -> None:
            self.file_writer = _NullWriter()

        def play(self, scene, *args, **kwargs) -> None:
            self.recorder.play(self, scene, args, kwargs)

        def update_frame(self, *args, **kwargs) -> None:
            pass

        def render(self, scene, time, moving_mobjects=None) -> None:
            self.recorder.sample(scene, time)

        def add_frame(self, *args, **kwargs) -> None:
            pass

        def freeze_current_frame(self, duration: float) -> None:
            pass

        def save_static_frame_data(self, scene, static_mobjects):
            self.static_image = None

        def update_skipping_status(self) -> None:
            pass

        def scene_finished(self, scene) -> None:
            pass

    return RecordingRenderer


class _NullWriter:
    """Stands in for Manim's file writer: sections, sounds and subcaptions go nowhere."""

    def __init__(self) -> None:
        self.subcaptions: list = []
        self.sections: list = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


# -- animation details ------------------------------------------------------------------------------


def _bind(cls: type, args: tuple, kwargs: dict) -> dict[str, Any]:
    """The animation's arguments by name (positional ones too), ``**kwargs`` spread out."""
    try:
        bound = inspect.signature(cls.__init__).bind(None, *args, **kwargs)
    except (TypeError, ValueError):
        return dict(kwargs)
    out: dict[str, Any] = {}
    params = inspect.signature(cls.__init__).parameters
    for key, value in bound.arguments.items():
        kind = params[key].kind
        if kind is inspect.Parameter.VAR_KEYWORD:
            out.update(value)
        elif kind is inspect.Parameter.VAR_POSITIONAL:
            if len(value) == 1:
                out.setdefault("mobject", value[0])
        else:
            out[key] = value
    return out


def _param(key: str, value: Any, registered) -> tuple[Any, str | None]:
    """``(the clip param's value, None)``, or ``(None, why it cannot be one)``."""
    import manim as m
    import numpy as np

    from .core.schema import DIRECTIONS

    if registered is not None and registered.kind == "direction":
        vector = np.asarray(value, dtype=float).reshape(-1)
        if len(vector) not in (2, 3) or not np.isfinite(vector).all() or (len(vector) == 3 and vector[2]):
            return None, "not a direction in the plane"
        for name in DIRECTIONS:
            if np.allclose(vector[:2], np.asarray(getattr(m, name), dtype=float)[:2], atol=1e-12):
                return name, None
        return [float(vector[0]), float(vector[1])], None
    if registered is not None and registered.kind == "choice" and key == "shape":
        name = getattr(value, "__name__", None)
        if name in SHAPE_CLASSES and getattr(m, name) is value:
            return SHAPE_CLASSES[name], None
        return None, "only Rectangle and Circle"
    if isinstance(value, m.ManimColor) or (registered is not None and registered.kind == "color"):
        try:
            colour = m.ManimColor(value)
        except Exception:
            return None, "not a colour"
        hexed = colour.to_hex()
        if not np.allclose(m.ManimColor(hexed).to_rgba(), colour.to_rgba(), atol=COLOUR_TOLERANCE):
            return None, "a colour #rrggbb cannot hold exactly"
        return hexed, None
    if isinstance(value, (bool, str)):
        return value, None
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            return None, "not a finite number"
        return (int(value) if isinstance(value, (int, np.integer)) else number), None
    if isinstance(value, m.Mobject):
        return None, "another object (only the animated object and its target can be layers)"
    if callable(value):
        return None, "a function"
    return None, "a point or a value Manim Studio cannot keep in a clip"


@lru_cache(maxsize=1)
def _rate_names() -> dict[int, str]:
    from manim.utils import rate_functions

    return {
        id(getattr(rate_functions, name)): name
        for name in dir(rate_functions)
        if not name.startswith("_") and callable(getattr(rate_functions, name)) and name != "unit_interval"
    }


def _ease_of(func) -> dict | None:
    """A Studio ease (``{"name": ...}`` or ``{"bezier": [...]}``) that is ``func``, or None."""
    if func is None:
        return None
    name = _rate_names().get(id(func))
    if name is not None:
        return {"name": name}
    qualname = getattr(func, "__qualname__", "")
    cells = _cells(func)
    if qualname.endswith("cubic_bezier.<locals>.func") and {"x1", "y1", "x2", "y2"} <= set(cells):
        return {"bezier": [float(cells[k]) for k in ("x1", "y1", "x2", "y2")]}
    if qualname.endswith("clamped.<locals>.<lambda>") and "rate_func" in cells:
        return _ease_of(cells["rate_func"])  # the readable export's helper: Studio clamps anyway
    return None


def _cells(func) -> dict[str, Any]:
    code, closure = getattr(func, "__code__", None), getattr(func, "__closure__", None)
    if code is None or not closure:
        return {}
    out = {}
    for name, cell in zip(code.co_freevars, closure, strict=False):
        with contextlib.suppress(ValueError):  # an empty cell
            out[name] = cell.cell_contents
    return out


def _same_function(a, b) -> bool:
    try:
        return all(abs(float(a(x)) - float(b(x))) < 1e-9 for x in SAMPLES)
    except Exception:
        return False


def _same_rate(original, probe, clamped: bool) -> bool:
    """Do the two animations ease alike (Studio clamps content clips' ends: so is the original)?"""
    if bool(original.reverse_rate_function) != bool(probe.reverse_rate_function):
        return False
    try:
        for x in SAMPLES:
            a = float(original.rate_func(x))
            if clamped:
                a = min(1.0, max(0.0, a))
            if abs(a - float(probe.rate_func(x))) > 1e-9:
                return False
    except Exception:
        return False
    return True


def _overshoots(func) -> bool:
    try:
        values = [float(func(i / 200)) for i in range(201)]
    except Exception:
        return True
    return min(values) < -1e-9 or max(values) > 1 + 1e-9


def _clamps_input(func) -> bool:
    """Does ``func`` hold its ends outside [0, 1] (as Manim's ``unit_interval`` eases do)? A clip
    split over parts of a group then times each part as the whole would."""
    try:
        return all(abs(float(func(x)) - float(func(0.0))) < 1e-12 for x in (-0.5, -0.1)) and all(
            abs(float(func(x)) - float(func(1.0))) < 1e-12 for x in (1.1, 1.5)
        )
    except Exception:
        return False


def _symmetric(func) -> bool:
    try:
        return all(abs(float(func(x)) - (1 - float(func(1 - x)))) < 1e-9 for x in SAMPLES)
    except Exception:
        return False


def _about(anim, target) -> list[float] | None:
    """The point a rotation turns about, as it begins."""
    import numpy as np

    point = getattr(anim, "about_point", None)
    if point is None:
        edge = getattr(anim, "about_edge", None)
        point = target.get_critical_point(edge) if edge is not None else target.get_center()
    point = np.asarray(point, dtype=float)
    return [float(point[0]), float(point[1])]


# -- built-in objects that rebuild a mobject exactly ------------------------------------------------


def _candidate(mob, pairs: list[list[str]]) -> dict | None:
    """A built-in Studio object (spec, base transform) that draws exactly ``mob``, or None.

    The guess comes from the object's own attributes (a circle's radius, a text's string); its
    size, turn and place are fitted to the points; every piece is then rebuilt by the adapter and
    compared: points within ``TOLERANCE``, colours and widths equal. ``structure`` says whether
    the rebuilt object also has ``mob``'s submobject tree (a Transform aligns trees)."""
    import manim as m

    name = type(mob).__name__
    if name not in CANDIDATE_TYPES or getattr(m, name, None) is not type(mob):
        return None
    try:
        return _fit(mob, name, pairs)
    except Exception:  # an object that cannot be guessed is a shape, never an error
        return None


def _fit(mob, name: str, pairs) -> dict | None:
    import numpy as np

    from .core import adapter
    from .core.schema import Spec

    leaves = mob.family_members_with_points()
    actual = [np.asarray(x.points, dtype=float) for x in leaves]
    if any(len(a) == 0 or np.abs(a[:, 2]).max() > 1e-12 for a in actual):
        return None
    params = _guess(mob, name)
    if params is None:
        return None
    built = adapter.build_mobject(Spec(type=name, params=params))
    fit = _similarity(built, actual)
    if fit is None:
        return None
    k, angle, position = fit
    sizes = CANDIDATE_TYPES[name]
    if sizes and abs(k - 1) > 1e-12:
        params = {key: (value * k if key in sizes else value) for key, value in params.items()}
        built = adapter.build_mobject(Spec(type=name, params=params))
        fit = _similarity(built, actual)
        if fit is None:
            return None
        k, angle, position = fit
    style = _style(leaves, built.family_members_with_points())
    if style is None:
        return None
    spec = Spec(type=name, params=params, style=style)
    base = {"position": [float(position[0]), float(position[1])], "rotation": math.degrees(angle), "scale": k}
    if abs(base["rotation"]) < 1e-9:
        base["rotation"] = 0.0
    if abs(base["scale"] - 1) < 1e-12:
        base["scale"] = 1.0
    rounded_spec, rounded_base = (
        _rounded(spec),
        {
            "position": [round(v, 9) for v in base["position"]],
            "rotation": round(base["rotation"], 9),
            "scale": round(base["scale"], 12),
        },
    )
    for try_spec, try_base in ((rounded_spec, rounded_base), (spec, base)):
        if _rebuilds(try_spec, try_base, leaves):
            built = adapter.build_mobject(try_spec)
            return {
                "leaves": pairs,
                "spec": try_spec.model_dump(),
                "base": try_base,
                "structure": _tree(built) == _tree(mob),
            }
    return None


def _guess(mob, name: str) -> dict | None:
    import numpy as np

    if name in ("Circle", "Dot"):
        return {"radius": float(mob.radius)}
    if name == "Square":
        return {"side_length": float(mob.side_length)}
    if name == "Rectangle":
        v = mob.get_vertices()
        return {"width": float(np.linalg.norm(v[0] - v[1])), "height": float(np.linalg.norm(v[1] - v[2]))}
    if name == "Triangle":
        return {}
    if name == "Star":
        v = np.asarray(mob.get_vertices(), dtype=float)
        if len(v) % 2:
            return None
        centre = v.mean(axis=0)
        return {"n": len(v) // 2, "outer_radius": float(np.linalg.norm(v[0] - centre))}
    if name in ("Line", "Arrow"):
        start, end = np.asarray(mob.get_start(), dtype=float), np.asarray(mob.get_end(), dtype=float)
        middle = (start + end) / 2
        params = {
            "start": [float(v) for v in (start - middle)[:2]],
            "end": [float(v) for v in (end - middle)[:2]],
        }
        if name == "Arrow":
            params["buff"] = 0.0
        return params
    if name == "Text":
        params = {"text": str(mob.original_text), "font_size": float(mob.font_size)}
        if mob.font:
            params["font"] = str(mob.font)
        if str(mob.weight) != "NORMAL":
            params["weight"] = str(mob.weight)
        if str(mob.slant) != "NORMAL":
            params["slant"] = str(mob.slant)
        if mob.t2c:
            params["t2c"] = dict(mob.t2c)
        return params
    if name in ("MathTex", "Tex"):
        return {"text": str(mob.tex_string), "font_size": float(mob.font_size)}
    return None


def _similarity(built, actual: list) -> tuple[float, float, Any] | None:
    """``(k, angle, position)`` with ``actual = k R(angle) built + position``, piece by piece, or
    None when no such map fits within ``TOLERANCE`` (or the pieces differ in number or size)."""
    import numpy as np

    source = [np.asarray(x.points, dtype=float) for x in built.family_members_with_points()]
    if len(source) != len(actual) or any(a.shape != b.shape for a, b in zip(source, actual, strict=True)):
        return None
    s = np.vstack(source)[:, :2]
    d = np.vstack(actual)[:, :2]
    ms, md = s.mean(axis=0), d.mean(axis=0)
    cs, cd = s - ms, d - md
    norm = float((cs**2).sum())
    if norm <= 0:
        return None
    dot = float((cs * cd).sum())
    cross = float((cs[:, 0] * cd[:, 1] - cs[:, 1] * cd[:, 0]).sum())
    angle = math.atan2(cross, dot)
    k = math.hypot(dot, cross) / norm
    c, sn = math.cos(angle) * k, math.sin(angle) * k
    matrix = np.array([[c, -sn], [sn, c]])
    position = md - matrix @ ms
    error = np.abs(s @ matrix.T + position - d).max()
    if error > TOLERANCE:
        return None
    return k, angle, position


def _style(actual: list, built: list) -> dict | None:
    """The Spec.style keys that turn the built pieces' colours into the actual ones (None when no
    uniform style does: several colours, a gradient, a colour #rrggbb cannot hold)."""
    import manim as m
    import numpy as np

    style: dict[str, Any] = {}
    for key, getter in (("fill", "fill_rgbas"), ("stroke", "stroke_rgbas")):
        rows = [np.asarray(getattr(x, getter), dtype=float) for x in actual]
        if any(r.shape != (1, 4) for r in rows):
            return None  # a gradient
        first = rows[0][0]
        if any(not np.allclose(r[0], first, atol=COLOUR_TOLERANCE) for r in rows):
            return None  # pieces of several colours
        mine = [np.asarray(getattr(x, getter), dtype=float) for x in built]
        uniform = all(r.shape == (1, 4) for r in mine)
        if not uniform or any(not np.allclose(r[0][:3], first[:3], atol=COLOUR_TOLERANCE) for r in mine):
            hexed = m.ManimColor(first[:3].tolist()).to_hex()
            if not np.allclose(m.ManimColor(hexed).to_rgba()[:3], first[:3], atol=COLOUR_TOLERANCE):
                return None  # not a colour #rrggbb holds exactly
            style[key] = hexed
        if not uniform or any(abs(r[0][3] - first[3]) > COLOUR_TOLERANCE for r in mine):
            style[f"{key}_opacity"] = float(first[3])
    widths = {float(x.get_stroke_width()) for x in actual}
    if len(widths) != 1:
        return None
    width = widths.pop()
    if any(abs(float(x.get_stroke_width()) - width) > 1e-12 for x in built):
        style["stroke_width"] = width
    return style


def _rebuilds(spec, base: dict, leaves: list) -> bool:
    """Does the Studio object ``spec`` placed by ``base`` draw exactly ``leaves``?"""
    import numpy as np

    from .core import adapter

    built = adapter.build_mobject(spec).family_members_with_points()
    if len(built) != len(leaves):
        return False
    angle = math.radians(base["rotation"])
    c, s = math.cos(angle) * base["scale"], math.sin(angle) * base["scale"]
    matrix = np.array([[c, -s], [s, c]])
    offset = np.asarray(base["position"], dtype=float)
    for ours, theirs in zip(built, leaves, strict=True):
        a, b = np.asarray(ours.points, dtype=float), np.asarray(theirs.points, dtype=float)
        if a.shape != b.shape or np.abs(b[:, 2]).max(initial=0) > 1e-12:
            return False
        if np.abs(a[:, :2] @ matrix.T + offset - b[:, :2]).max(initial=0) > TOLERANCE:
            return False
        mine, other = adapter.piece_data(ours), adapter.piece_data(theirs)
        mine.pop("points"), other.pop("points")
        mine.pop("z_index", None), other.pop("z_index", None)
        if set(mine) != set(other):
            return False
        for key, value in mine.items():
            if isinstance(value, list):
                if np.asarray(value, dtype=float).shape != np.asarray(other[key], dtype=float).shape:
                    return False
                if not np.allclose(value, other[key], atol=COLOUR_TOLERANCE, rtol=0):
                    return False
            elif isinstance(value, float):
                if abs(value - other[key]) > 1e-12:
                    return False
            elif value != other[key]:
                return False
    return True


def _rounded(spec):
    """``spec`` with its numbers rounded to 9 decimals (2.0000000000000004 shows as 2.0)."""
    from .core.schema import Spec

    def tidy(value):
        if isinstance(value, float):
            return round(value, 9)
        if isinstance(value, list):
            return [tidy(v) for v in value]
        return value

    return Spec(
        type=spec.type,
        params={k: tidy(v) for k, v in spec.params.items()},
        style={k: tidy(v) for k, v in spec.style.items()},
    )


def _flat(mob) -> bool:
    """Is ``mob``'s tree what a shape's is - a group of single pieces, or one piece - so that a
    Transform pairs the same pieces whichever of the two it is given (Mobject.null_point_align)?"""
    if mob.has_points():
        return not mob.submobjects
    return all(not sub.submobjects for sub in mob.submobjects)


def _tree(mob) -> tuple:
    """The shape of a submobject tree: how many children each node has, depth first."""
    return (len(mob.submobjects), tuple(_tree(sub) for sub in mob.submobjects))


# -- the process ------------------------------------------------------------------------------------


def run_recorder(
    path: str | Path, scene: str | None, cache_dir: str | Path, timeout: float = TIME_LIMIT
) -> dict:
    """Record ``path``'s scene in a new process (the user's code never runs in the caller), stopped
    after ``timeout`` seconds. Raises ``RecordError`` with the reason (and line) when it fails."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory(prefix="manim-studio-import-") as folder:
        output = Path(folder) / "recording.json"
        args = [sys.executable, "-m", "manim_studio.scene_recorder", "--cache-dir", str(cache_dir)]
        args += ["--file", str(path), "--output", str(output)] + (["--scene", scene] if scene else [])
        env = {**os.environ, "PYTHONUTF8": "1"}
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RecordError(f"the scene took longer than {timeout:g} s to play, so it was stopped") from exc
        for line in reversed(done.stdout.splitlines()):
            if line.startswith("{"):
                message = json.loads(line)
                if "error" in message:
                    raise RecordError(message["error"], message.get("line"))
                if message.get("done"):
                    return json.loads(output.read_text(encoding="utf-8"))
        error = done.stderr.strip().splitlines()[-1:] or [f"exit code {done.returncode}"]
        raise RecordError(f"the recording process failed: {error[0]}")


def _claim_stdout():
    """Keep the real stdout for the protocol; the scene's own prints go to stderr."""
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n")
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    return protocol


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m manim_studio.scene_recorder")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--file", type=Path, help="record this file at once (no job on stdin)")
    parser.add_argument("--scene", help="the scene class (default: the file's only one)")
    parser.add_argument("--output", type=Path, help="where the recording goes (default: stdout)")
    args = parser.parse_args(argv)
    protocol = _claim_stdout()
    logging.disable(logging.INFO)

    def emit(message: dict) -> None:
        protocol.write(json.dumps(message) + "\n")
        protocol.flush()

    from .core import adapter

    adapter.configure(args.cache_dir)  # imports Manim: the expensive part, done before any job
    import manim as m

    m.logger.setLevel("ERROR")
    if args.file is not None:
        job = {
            "file": str(args.file),
            "scene": args.scene,
            "output": str(args.output) if args.output else None,
        }
    else:
        emit({"ready": True})
        line = sys.stdin.readline()
        if not line.strip():
            return 0  # the editor closed: no job
        job = json.loads(line)
    started = time.perf_counter()
    try:
        recording = record_file(job["file"], job.get("scene"))
    except RecordError as error:
        emit({"error": str(error), "line": error.line})
        return 1
    except Exception as error:  # a bug here must still reach the editor as a message
        emit({"error": _message(error), "line": None})
        return 1
    recording["seconds"] = round(time.perf_counter() - started, 3)
    text = json.dumps(recording)
    if job.get("output"):
        Path(job["output"]).write_text(text, encoding="utf-8")
        emit({"done": True, "output": job["output"]})
    else:
        emit({"done": True, "recording": recording})
    return 0


if __name__ == "__main__":
    sys.exit(main())
