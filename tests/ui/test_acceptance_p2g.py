"""P2g acceptance: circle a term, recolour the circle, fade a title in from the left (ADR 0022).

An equation written and split into terms through the UI; *Circumscribe* added to
its b^2 term from the timeline and recoloured in Properties; a title faded in
moving right. Scrubbing shows exactly what playing shows, and the export shows
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
from ui.test_acceptance_p2e import add_equation
from ui.test_acceptance_v1 import menu_action, timeline_menu, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.latex, pytest.mark.slow]  # starts real processes

CYAN = "#22d3ee"


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_circle_a_term_and_fade_a_title_in_from_the_left(window, qt_app, tmp_path) -> None:
    tag = uuid.uuid4().hex[:4]  # fresh LaTeX: the worker really builds it
    menu_action(window.menuBar(), "File", "New").trigger()
    eq = add_equation(window, qt_app, rf"a^2 + b^2 = c^2 + \text{{{tag}}}")
    menu_action(timeline_menu(window, eq, 0.0), "Add clip", "Appear / disappear", "Write").trigger()
    b2 = next(layer.id for layer in window.project.children(eq) if layer.part.tex == "b^2")

    # Circumscribe from the timeline, on the term; recoloured in Properties
    menu_action(timeline_menu(window, b2, 1.5), "Add clip", "Emphasis", "Circumscribe").trigger()
    circle = next(c for c in window.project.layer(b2).clips if c.kind == "Circumscribe")
    window.selection.set(b2, circle.id)
    qt_app.processEvents()
    window.properties.fields["clip.params.color"].commit(CYAN)
    wait_until(qt_app, lambda: window.project.layer(b2).clips[0].params == {"color": CYAN})

    # a title fading in, moving right: it comes from the left
    menu_action(window.layers.library_menu, "Text").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 2)  # Text waits for its first build
    title = window.project.roots()[-1].id
    window.selection.select_layer(title)
    qt_app.processEvents()
    window.properties.fields["params.text"].commit("Pythagoras")
    window.properties.fields["base.position"].commit((0.0, 2.5))
    wait_until(qt_app, lambda: window.project.layer(title).spec.params.get("text") == "Pythagoras")
    menu_action(timeline_menu(window, title, 0.0), "Add clip", "Appear / disappear", "FadeIn").trigger()
    fade = window.project.layer(title).clips[0]
    window.selection.set(title, fade.id)
    qt_app.processEvents()
    window.properties.fields["clip.params.shift"].commit("RIGHT")
    wait_until(qt_app, lambda: window.project.layer(title).clips[0].params == {"shift": "RIGHT"})

    evaluator = window.evaluator
    middle = (circle.start + circle.end) / 2
    drawn = dict(evaluator.frame_layers(middle))[b2]
    assert len(drawn.family_members_with_points()) > 2  # the term's two glyphs and the frame around them
    early = dict(evaluator.frame_layers(fade.start + 0.2 * fade.duration))[title].get_center()[0]
    assert early < -0.3  # still left of its place
    assert dict(evaluator.frame_layers(fade.end + 0.1))[title].get_center()[0] == pytest.approx(0.0, abs=1e-6)

    # scrubbing in any order shows what playing in order shows
    project = window.project
    camera = make_camera(project.canvas)
    times = [i / project.canvas.fps for i in range(0, int(project.canvas.duration * project.canvas.fps), 2)]
    played = {t: render_frame(camera, evaluator.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(7).shuffle(shuffled)
    for t in shuffled:
        assert np.array_equal(render_frame(camera, evaluator.frame(t)), played[t]), t

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p2g.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    all_times = frame_times(project.canvas)
    for t in (fade.start + 0.3, middle, circle.end - 0.1):
        i = min(range(len(all_times)), key=lambda k: abs(all_times[k] - t))
        expected = render_frame(camera, evaluator.frame(all_times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, t
