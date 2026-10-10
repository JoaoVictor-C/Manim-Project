"""P3e acceptance: bring in an SVG and draw it on (ADR 0027).

An SVG from Media > SVG, a DrawBorderThenFill clip from the timeline: the
drawing keeps its colours, scrubbing shows what playing shows; the file saved
again in another program is redrawn when the editor is re-activated; deleted,
it turns into a placeholder with a message; and the export shows what the
editor shows.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random

import av
import manim as m
import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from manim_studio.core.evaluator import Evaluator
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action, timeline_menu, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # the export starts a real process

LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 100">
  <circle cx="35" cy="50" r="30" fill="#f97316" stroke="#fde68a" stroke-width="3"/>
  <rect x="70" y="20" width="45" height="60" fill="#22d3ee"/>
</svg>"""
REDRAWN = LOGO.replace("#22d3ee", "#a3e635").replace('width="45"', 'width="30"')


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def colours(mob: m.Mobject) -> set[str]:
    return {sub.get_fill_color().to_hex().lower() for sub in mob.family_members_with_points()}


def test_bring_in_an_svg_and_draw_it_on(window, qt_app, tmp_path) -> None:
    logo = tmp_path / "logo.svg"
    logo.write_text(LOGO, encoding="utf-8")
    menu_action(window.menuBar(), "File", "New").trigger()
    window.layers.choose_svg = lambda: str(logo)
    menu_action(window.layers.library_menu, "SVG").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 1)
    layer_id = window.project.roots()[0].id
    menu_action(
        timeline_menu(window, layer_id, 0.0), "Add clip", "Appear / disappear", "DrawBorderThenFill"
    ).trigger()
    clip = window.project.layer(layer_id).clips[0]
    assert clip.kind == "DrawBorderThenFill"

    evaluator = window.evaluator
    (drawn,) = evaluator.frame(clip.end + 0.5)
    assert {"#f97316", "#22d3ee"} <= colours(drawn)  # the file's own colours
    project = window.project
    camera = make_camera(project.canvas)
    blank = render_frame(camera, [])
    assert np.array_equal(render_frame(camera, evaluator.frame(0.0)), blank)  # not drawn yet
    assert (
        np.abs(
            render_frame(camera, evaluator.frame(clip.start + clip.duration / 2)).astype(int) - blank
        ).max()
        > 50
    )

    # scrubbing in any order shows what playing in order shows
    times = [i / project.canvas.fps for i in range(0, int(project.canvas.duration * project.canvas.fps), 2)]
    played = {t: render_frame(camera, evaluator.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(9).shuffle(shuffled)
    for t in shuffled:
        assert np.array_equal(render_frame(camera, evaluator.frame(t)), played[t]), t

    # saved again in another program: redrawn when the editor is active again
    logo.write_text(REDRAWN, encoding="utf-8")
    window._on_application_state(Qt.ApplicationState.ApplicationActive)
    (drawn,) = evaluator.frame(clip.end + 0.5)
    assert "#a3e635" in colours(drawn) and "#22d3ee" not in colours(drawn)
    fresh = Evaluator(window.project)
    for t in (clip.start + 0.3, clip.end + 0.5):  # in the clip and after it: all from the new file
        assert np.array_equal(
            render_frame(camera, evaluator.frame(t)), render_frame(camera, fresh.frame(t))
        ), t

    # deleted: a placeholder and a message, never an error
    hidden = tmp_path / "away.svg"
    logo.rename(hidden)
    window._on_application_state(Qt.ApplicationState.ApplicationActive)
    (drawn,) = evaluator.frame(clip.end + 0.5)
    assert isinstance(drawn, m.DashedVMobject)
    name = window.project.layer(layer_id).name or layer_id
    assert window.statusBar().currentMessage() == f"Missing media: {name} (logo.svg - file not found)"
    hidden.rename(logo)
    window._on_application_state(Qt.ApplicationState.ApplicationActive)

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p3e.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    all_times = frame_times(project.canvas)
    for t in (clip.start + 0.4, clip.end + 0.5):
        i = min(range(len(all_times)), key=lambda k: abs(all_times[k] - t))
        expected = render_frame(camera, evaluator.frame(all_times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, t
