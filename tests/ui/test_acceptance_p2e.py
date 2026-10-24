"""P2e acceptance: one equation turns into another, term by term (ADR 0020).

Two equations written through the UI, both split into terms, joined by
Turn into > TransformMatchingTex from the timeline: matching terms fly to their
new places, scrubbing shows exactly what playing shows, and the export shows
exactly what the editor shows.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random
import uuid

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action, timeline_menu, type_latex, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.latex, pytest.mark.slow]  # starts real processes


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def add_equation(window, qt_app, latex: str) -> str:
    count = len(window.project.roots())
    menu_action(window.layers.library_menu, "MathTex").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == count + 1)
    layer_id = window.project.roots()[-1].id
    type_latex(window, qt_app, latex)
    window.layers.select(layer_id)
    menu_action(window.layers.part_button.menu(), "Split into terms").trigger()
    wait_until(qt_app, lambda: len(window.project.children(layer_id)) == 4)  # 3 terms + the tag
    return layer_id


def test_an_equation_turns_into_another(window, qt_app, tmp_path) -> None:
    tag = uuid.uuid4().hex[:4]  # fresh LaTeX: the worker really builds it
    menu_action(window.menuBar(), "File", "New").trigger()
    one = add_equation(window, qt_app, rf"a^2 + b^2 = c^2 + \text{{{tag}}}")
    menu_action(timeline_menu(window, one, 0.0), "Add clip", "Appear / disappear", "Write").trigger()
    two = add_equation(window, qt_app, rf"a^2 = c^2 - b^2 + \text{{{tag}}}")
    window.selection.select_layer(two)
    window.properties.fields["base.position"].commit((0.0, -1.5))
    wait_until(qt_app, lambda: window.project.layer(two).base.position == (0.0, -1.5))

    # Turn into > TransformMatchingTex, offered for objects with parts, listing TeX targets
    menu = timeline_menu(window, one, 2.0)
    targets = [
        a.text() for a in menu_action(menu, "Add clip", "Turn into", "TransformMatchingTex").menu().actions()
    ]
    assert targets == [window.project.layer(two).label]
    menu_action(menu, "Add clip", "Turn into", "TransformMatchingTex", targets[0]).trigger()
    clip = next(c for c in window.project.layer(one).clips if c.to_layer == two)
    assert clip.kind == "TransformMatchingTex"
    assert window.project.lifetime(two)[0] == pytest.approx(clip.end)

    # during the morph the first equation is one morphing object; afterwards the second, with its terms
    middle = (clip.start + clip.end) / 2
    assert [i for i, _ in window.evaluator.frame_layers(middle)] == [one]
    after = [i for i, _ in window.evaluator.frame_layers(clip.end + 0.5)]
    assert after[0] == two and len(after) == 5  # the object (its + and =) and its 4 parts

    # scrubbing in any order shows what playing in order shows
    project = window.project
    camera = make_camera(project.canvas)
    times = [i / project.canvas.fps for i in range(0, int(project.canvas.duration * project.canvas.fps), 2)]
    played = {t: render_frame(camera, window.evaluator.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(4).shuffle(shuffled)
    for t in shuffled:
        assert np.array_equal(render_frame(camera, window.evaluator.frame(t)), played[t]), t

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p2e.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    all_times = frame_times(project.canvas)
    for t in (clip.start + 0.25, middle, clip.end - 0.1, clip.end + 0.5):
        i = min(range(len(all_times)), key=lambda k: abs(all_times[k] - t))
        expected = render_frame(camera, window.evaluator.frame(all_times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, t
