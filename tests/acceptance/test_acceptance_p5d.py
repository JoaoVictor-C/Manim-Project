"""P5d acceptance: a scene built in the editor (axes with a graph, a circle with clips, a square, a
connector between them, a sound, a subtitle) is duplicated, copied and pasted through the Edit
menu - the copies draw exactly like the originals where they are placed - then saved, edited,
"crashed" (the recovery copy written by the timer is left behind by an owner that no longer
runs) and restored in a fresh window, equal to the project before the crash (ADR 0038).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import numpy as np
import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import menu_action, timeline_menu, wait_until
from core.model.test_recovery import dead_pid
from manim_studio.core.model import recovery
from manim_studio.core.model.schema import Project
from manim_studio.core.sound import audio
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.shell import autosave

pytestmark = [pytest.mark.ui, pytest.mark.slow, pytest.mark.latex]  # LaTeX axes; a real sound


def add(window, qt_app, label: str, position: tuple[float, float] | None = None) -> str:
    count = len(window.project.layers)
    menu_action(window.layers.library_menu, label).trigger()
    wait_until(qt_app, lambda: len(window.project.layers) > count, timeout=60)
    layer_id = window.selection.layer_id
    if position is not None:
        window.properties.fields["base.position"].commit(position)
    return layer_id


def edit(window, name: str) -> None:
    menu_action(window.menuBar(), "Edit", name).trigger()


def points(window, layer_id: str, t: float) -> np.ndarray:
    """Every point the object (with its parts and child objects) is drawn with at ``t``."""
    window.seek(t)
    drawn = window.evaluator.object_frame(layer_id, t)
    return np.vstack([mob.points for _owner, top in drawn for mob in top.family_members_with_points()])


def assert_drawn_alike(window, original: str, copy: str, offset=(0.0, 0.0), times=(0.25, 2.3)) -> None:
    for t in times:
        a, b = points(window, original, t), points(window, copy, t)
        assert a.shape == b.shape, (original, copy, t)
        assert np.allclose(b, a + np.array([*offset, 0.0]), atol=1e-6), (original, copy, t)


def test_copies_draw_like_their_originals_and_a_crash_is_recovered(qt_app, tmp_path, monkeypatch) -> None:
    folder = tmp_path / "recovery"
    monkeypatch.setenv(autosave.RECOVERY_ENV, str(folder))
    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 5.0}
    window.document.replace(
        window.project.model_copy(update={"canvas": window.project.canvas.model_copy(update=small)})
    )

    # -- the scene, through the editor's own menus
    axes = add(window, qt_app, "Axes", (-3.0, 1.0))
    window.properties.fields["base.scale"].commit(0.4)
    window.layers.ask_expression = lambda: "sin(x)"
    window.layers.add_graph()
    graph = window.selection.layer_id
    assert window.project.layer(graph).parent_id == axes
    circle = add(window, qt_app, "Circle", (-4.0, -2.0))
    menu_action(timeline_menu(window, circle, 0.0), "Add clip", "Appear / disappear", "FadeIn").trigger()
    menu_action(timeline_menu(window, circle, 2.0), "Add clip", "Emphasis", "Indicate").trigger()
    square = add(window, qt_app, "Square", (4.0, -2.0))
    link = add(window, qt_app, "Connector")
    assert window.project.layer(link).spec.params["target"] == square
    sound = tmp_path / "beep.wav"
    t = np.arange(audio.RATE) / audio.RATE
    audio.write_wav(np.stack([0.3 * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32), sound)
    window.ask_audio_path = lambda: str(sound)
    window.seek(0.5)
    menu_action(window.menuBar(), "File", "Import Audio...").trigger()
    window.seek(0.2)
    edit(window, "Add Subtitle")
    saved = tmp_path / "scene.json"
    window.path = saved
    window.save()

    # -- duplicate: the circle's copy, moved up, draws like the circle moved up
    window.selection.set(circle)
    edit(window, "Duplicate")
    circle_copy = window.selection.layer_id
    assert circle_copy != circle
    assert window.project.layer(circle_copy).clips == window.project.layer(circle).clips
    window.properties.fields["base.position"].commit((-4.0, 1.0))
    assert_drawn_alike(window, circle, circle_copy, offset=(0.0, 3.0))

    # -- copy the axes with their graph, paste above the square, move it right
    window.selection.set(axes)
    edit(window, "Copy")
    window.selection.set(square)
    edit(window, "Paste")
    axes_copy = window.selection.layer_id
    roots = [x.id for x in window.project.roots()]
    assert roots.index(axes_copy) == roots.index(square) + 1
    (graph_copy,) = window.project.children(axes_copy)
    assert graph_copy.spec == window.project.layer(graph).spec
    window.properties.fields["base.position"].commit((-2.0, 1.0))
    assert_drawn_alike(window, axes, axes_copy, offset=(1.0, 0.0))

    # -- the connector: a pasted copy joins the same objects
    window.selection.set(link)
    edit(window, "Copy")
    edit(window, "Paste")
    link_copy = window.selection.layer_id
    assert_drawn_alike(window, link, link_copy)

    # -- a clip, the sound and the subtitle at the playhead
    window.selection.set(circle, window.project.layer(circle).clips[0].id)
    edit(window, "Copy")
    window.selection.set(square)
    window.seek(2.0)
    edit(window, "Paste")
    (pasted_clip,) = window.project.layer(square).clips
    assert (pasted_clip.kind, pasted_clip.start) == ("FadeIn", 2.0)
    window.selection.set_audio(window.project.audio[0].id)
    edit(window, "Copy")
    window.seek(3.0)
    edit(window, "Paste")
    assert [a.start for a in window.project.audio] == [0.5, 3.0]
    window.selection.set_subtitle(window.project.subtitles[0].id)
    edit(window, "Copy")
    window.seek(3.5)
    edit(window, "Paste")
    assert [c.start for c in window.project.subtitles] == [0.2, 3.5]
    steps = window.document.undo_stack.count()
    window.document.undo_stack.undo()  # each paste is one step
    assert [c.start for c in window.project.subtitles] == [0.2]
    window.document.undo_stack.redo()
    assert window.document.undo_stack.count() == steps

    # -- the timer's recovery copy, then a crash: the owner is gone, the copy stays
    window.autosave.tick()
    entry = window.autosave.written
    before_crash = window.project
    assert recovery.read_project(entry) == before_crash
    meta = json.loads(entry.meta_file.read_text(encoding="utf-8"))
    entry.meta_file.write_text(json.dumps({**meta, "pid": dead_pid()}), encoding="utf-8")
    window.autosave.timer.stop()
    monkeypatch.setattr(window.autosave, "discard", lambda: None)  # a crash deletes nothing
    window.close()

    # -- start again: the work is offered back and restored as unsaved changes to scene.json
    monkeypatch.setattr(MainWindow, "ask_recover", lambda self, entries: "restore")
    fresh = MainWindow()
    try:
        fresh.show()
        assert fresh.check_recovery()
        assert fresh.project == before_crash and fresh.path == saved
        assert not fresh.document.undo_stack.isClean() and fresh.windowTitle().endswith("scene.json *")
        assert_drawn_alike(fresh, circle, circle_copy, offset=(0.0, 3.0))
        fresh.save()
        assert Project.model_validate_json(saved.read_text(encoding="utf-8")) == before_crash
        assert list(folder.glob("*.json")) == []  # nothing left to recover
    finally:
        fresh.close()
