"""Exported scenes that play a project exactly through Manim (ADR 0031).

A file written by File > Export Python... in its *exact* form embeds the
project and subclasses ``StudioScene``; ``manim render file.py Name`` then draws,
at every frame, what the editor's evaluator draws at that frame's time::

    from manim_studio.manim_scene import StudioScene, configure

    PROJECT = r'''{...}'''
    configure(PROJECT)

    class Intro(StudioScene):
        project_json = PROJECT

Two Manim details matter (B43): the holder's updater takes ``dt`` - a plain
updater makes Manim freeze the ``wait`` into one repeated frame - and reads the
frame's time from ``self.renderer.time``. Code layers' frames are plain
mobjects Manim's camera skips, so the camera is taught to let them paint
themselves.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import manim as m

from .core.code import python_object
from .core.code.code_cache import CodeCache
from .core.code.code_frame import CodeFrame
from .core.engine.evaluator import Evaluator
from .core.model.schema import Project
from .core.sound import audio
from .render.preview import StudioThreeDCamera, keep_in_frame, orient


def configure(project_json: str) -> Project:
    """Set Manim's output to the project's canvas: pixel size, frame rate, frame, background.

    The file is Python the user runs: its Python objects' code runs too (ADR 0051)."""
    python_object.trust_everything()
    project = Project.model_validate_json(project_json)
    canvas = project.canvas
    m.config.pixel_width, m.config.pixel_height = canvas.width_px, canvas.height_px
    m.config.frame_rate = canvas.fps
    m.config.frame_height, m.config.frame_width = canvas.frame_height, canvas.frame_width
    m.config.background_color = m.ManimColor(canvas.background)
    return project


def teach_code_frames(camera: m.Camera) -> None:
    """Let ``camera`` paint code layers' frames (ADR 0019) where they are in the drawing order.

    Manim 0.22 rebuilds ``display_funcs`` inside ``type_or_raise`` on every call,
    so the CodeFrame painter is added back after each call.
    """

    def paint(batch, _pixel_array) -> None:
        for frame in batch:
            frame.paint(camera)

    original = camera.type_or_raise

    def type_or_raise(mobject: m.Mobject):
        kind = CodeFrame if isinstance(mobject, CodeFrame) else original(mobject)
        if not hasattr(camera, "display_funcs"):
            original(m.VMobject())  # builds the table
        camera.display_funcs[CodeFrame] = paint
        return kind

    camera.type_or_raise = type_or_raise


class StudioScene(m.Scene):
    """Plays ``project_json`` frame by frame through the editor's evaluator."""

    project_json: str = ""
    code_cache_dir: str | None = None  # where the editor kept the code layers' frames

    def __init__(self, *args, **kwargs) -> None:
        camera = Project.model_validate_json(self.project_json).camera if self.project_json else None
        if camera is not None and not camera.is_default:  # the editor's turned camera (ADR 0048)
            kwargs.setdefault("camera_class", StudioThreeDCamera)
        super().__init__(*args, **kwargs)

    def setup(self) -> None:
        teach_code_frames(self.renderer.camera)
        if isinstance(self.renderer.camera, m.ThreeDCamera):
            orient(self.renderer.camera, Project.model_validate_json(self.project_json).camera)

    def construct(self) -> None:
        project = Project.model_validate_json(self.project_json)
        cache = CodeCache(Path(self.code_cache_dir)) if self.code_cache_dir else None
        evaluator = Evaluator(project, cache)
        holder = m.Group()

        def show(group: m.Group, dt: float) -> None:  # dt: a time-based updater (B43)
            t = self.renderer.time
            overlay = evaluator.overlay(t)  # burned-in subtitles stay flat on the screen (ADR 0048)
            keep_in_frame(self.renderer.camera, overlay)
            group.submobjects = [*(mob for _, mob in evaluator.frame_layers(t)), *overlay]

        holder.add_updater(show)
        self.add(holder)
        for cue in project.subtitles:  # Manim writes them as an .srt beside its video (ADR 0035)
            if cue.text.strip():
                self.add_subcaption(cue.text.strip(), duration=cue.end - cue.start, offset=cue.start)
        if project.audio:  # the editor's mix (ADR 0034); add_sound reads the file at once
            with tempfile.TemporaryDirectory() as folder:
                sound = Path(folder) / "mix.wav"
                audio.write_wav(audio.mix(project), sound)
                self.add_sound(str(sound))
        self.wait(project.canvas.duration)
