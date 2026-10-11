"""P5b acceptance: a number that counts and an arrow between two objects, made in the editor,
rendered ahead after an object moves, exported as a video, and written as a readable Manim
scene (centre to centre) or an exact one (ending at the edges) that Manim renders the same
(ADR 0036).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_p4a import assert_matches_editor, manim_render
from ui.test_acceptance_p4b import live, shown
from ui.test_acceptance_v1 import menu_action, timeline_menu, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.slow, pytest.mark.latex]  # real processes; Manim renders


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_PREVIEW", "1")
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def add(window, qt_app, type_name: str, position: tuple[float, float]) -> str:
    count = len(window.project.layers)
    menu_action(window.layers.library_menu, type_name).trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == count + 1, timeout=60)
    layer_id = window.project.layers[-1].id
    window.properties.fields["base.position"].commit(position)
    return layer_id


def test_a_count_and_a_connector_to_a_video_and_manim_files(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 3.0}
    window.document.replace(
        window.project.model_copy(update={"canvas": window.project.canvas.model_copy(update=small)})
    )
    circle = add(window, qt_app, "Circle", (-4.0, -1.0))
    square = add(window, qt_app, "Square", (3.0, -1.0))
    menu_action(timeline_menu(window, square, 0.0), "Add clip", "Appear / disappear", "FadeIn").trigger()
    fade = window.project.layer(square).clips[0]
    window.selection.set(square, fade.id)
    window.properties.fields["clip.params.shift"].commit("UP")  # it rises into place

    number = add(window, qt_app, "Number", (-1.0, 2.5))
    window.properties.fields["params.unit"].commit(r"\%")
    menu_action(timeline_menu(window, number, 0.5), "Add clip", "Emphasis", "ChangeDecimalToValue").trigger()
    count = window.project.layer(number).clips[0]
    window.selection.set(number, count.id)
    window.properties.fields["clip.params.target_number"].commit(75.0)

    window.selection.set(square)  # an arrow from the circle (the object before it) to the square
    menu_action(window.layers.library_menu, "Connector").trigger()
    link = window.project.layers[-1].id
    assert window.project.layer(link).spec.params == {"source": circle, "target": square}
    window.properties.fields["params.tips"].commit("end")
    window.properties.fields["params.ends"].commit("centres")

    # centre to centre: a readable scene that Manim renders as the editor shows it
    readable = tmp_path / "count.py"
    window.ask_python_path = lambda start: str(readable)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    code = readable.read_text(encoding="utf-8")
    assert "always_redraw(lambda: Arrow(" in code and "ChangeDecimalToValue(" in code, code
    assert_matches_editor(window, manim_render(readable, "Count"))

    # ending at the edges, after the square moves: frames rendered ahead follow it
    window.selection.set(link)
    window.properties.fields["params.ends"].commit("edges")
    window.selection.set(square)
    window.properties.fields["base.position"].commit((2.5, 0.5))
    ahead = window.render_ahead
    wait_until(qt_app, lambda: ahead is not None and len(ahead.store) == ahead.store.total, timeout=180)
    for t in (0.2, 1.0, 2.5):
        window.seek(t)
        assert window.canvas.from_cache and np.array_equal(shown(window), live(window, t)), t
    end = dict(window.evaluator.frame_layers(2.5))[link].get_end()
    assert end[0] == pytest.approx(1.4, abs=0.02)  # the square's left side less the gap, not its centre

    # the export process and the exact Python scene draw the same
    window.show_export_dialog()
    dialog = window.export_dialog
    video = tmp_path / "count.mp4"
    dialog.path.setText(str(video))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(video)) as container:
        assert_matches_editor(window, [f.to_ndarray(format="rgb24") for f in container.decode(video=0)])
    exact = tmp_path / "edges.py"
    window.ask_python_path = lambda start: str(exact)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    assert "ending at the edges" in window.statusBar().currentMessage()
    assert_matches_editor(window, manim_render(exact, "Edges"))
