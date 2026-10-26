"""SVG layers and media files in the editor (P3e.2, ADR 0027).

Media > SVG asks for a file, Properties re-picks it with an SVG filter, a file
changed on disk is redrawn when the editor is re-activated or on Reload Media,
and media that cannot be drawn are named in the status bar.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from acceptance.test_acceptance_v1 import menu_action
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.style.fields import PathField

pytestmark = pytest.mark.ui

SQUARE = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="40" height="40" fill="#f97316"/></svg>'
BAR = '<svg xmlns="http://www.w3.org/2000/svg"><rect y="15" width="80" height="10" fill="#22d3ee"/></svg>'


def open_window(qt_app, tmp_path, *layers: Layer) -> MainWindow:
    project = Project(canvas=Canvas(width_px=640, height_px=360, fps=30, duration=2.0), layers=list(layers))
    path = tmp_path / "media.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    return win


@pytest.fixture
def drawing(tmp_path):
    path = tmp_path / "logo.svg"
    path.write_text(SQUARE, encoding="utf-8")
    return path


@pytest.fixture
def window(qt_app, tmp_path, drawing):
    win = open_window(
        qt_app, tmp_path, Layer(id="logo", spec=Spec(type="SVGMobject", params={"path": str(drawing)}))
    )
    yield win
    win.close()


def canvas_frame(window) -> np.ndarray:
    return render_frame(make_camera(window.project.canvas), window.evaluator.frame(window.t))


def test_the_library_adds_an_svg_from_a_file(window, qt_app, drawing) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    window.layers.choose_svg = lambda: ""
    menu_action(window.layers.library_menu, "SVG").trigger()
    assert window.project.layers == []  # cancelled: nothing added
    window.layers.choose_svg = lambda: str(drawing)
    menu_action(window.layers.library_menu, "SVG").trigger()
    (layer,) = window.project.layers
    assert layer.spec.type == "SVGMobject" and layer.spec.params == {"path": str(drawing)}
    assert window.selection.layer_id == layer.id


def test_properties_show_the_file_and_the_height(window, qt_app, tmp_path) -> None:
    window.selection.set("logo")
    fields = window.properties.fields
    assert isinstance(fields["params.path"], PathField)
    assert "*.svg" in fields["params.path"]._filter
    fields["params.height"].commit(3.0)
    assert window.project.layer("logo").spec.params["height"] == 3.0
    (mob,) = window.evaluator.frame(0.5)
    assert mob.height == pytest.approx(3.0)
    other = tmp_path / "bar.svg"
    other.write_text(BAR, encoding="utf-8")
    window.properties.fields["params.path"].commit(str(other))  # re-pick
    assert window.project.layer("logo").spec.params["path"] == str(other)
    (mob,) = window.evaluator.frame(0.5)
    assert mob.width / mob.height == pytest.approx(8.0, rel=0.05)


def test_coming_back_to_the_editor_redraws_a_changed_file(window, qt_app, drawing) -> None:
    before = canvas_frame(window)
    drawing.write_text(BAR, encoding="utf-8")  # saved in another program
    window._on_application_state(Qt.ApplicationState.ApplicationActive)
    assert not np.array_equal(canvas_frame(window), before)
    assert window.evaluator.check_media() == set()  # already up to date


def test_reload_media_says_what_happened(window, qt_app, drawing) -> None:
    menu_action(window.menuBar(), "View", "Reload Media").trigger()
    assert window.statusBar().currentMessage() == "Media reloaded (0 changed)"
    drawing.unlink()
    menu_action(window.menuBar(), "View", "Reload Media").trigger()
    assert window.statusBar().currentMessage() == "Missing media: logo (logo.svg - file not found)"


def test_opening_a_project_with_a_missing_file_says_so(qt_app, tmp_path) -> None:
    gone = Layer(
        id="pic", name="Photo", spec=Spec(type="ImageMobject", params={"path": str(tmp_path / "x.png")})
    )
    win = open_window(qt_app, tmp_path, gone)
    try:
        assert win.statusBar().currentMessage() == "Missing media: Photo (x.png - file not found)"
        win.statusBar().clearMessage()
        win._on_application_state(Qt.ApplicationState.ApplicationActive)
        assert win.statusBar().currentMessage() == ""  # the same problem is not repeated
    finally:
        win.close()
