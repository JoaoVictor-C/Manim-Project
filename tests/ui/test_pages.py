"""Workspace pages (P6b.1, ADR 0041): one instance of each shared view, moved between pages;
unused views parked (never floating); splitter sizes kept per page; the page bar, View > Pages
and Shift+number; panels hidden from View stay hidden on every page."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSplitter, QWidget

from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.pages import Page, Shared
from ui.test_acceptance_v1 import menu_action

pytestmark = pytest.mark.ui


class ViewerOnly(Page):
    """A page that shows only the viewer beside a page-specific label."""

    name = "viewer"
    title = "Viewer"
    icon = "animate"
    shown = 0

    def build(self) -> QWidget:
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(QLabel("page tools"))
        return self.split

    def place(self, shared: Shared) -> None:
        self.split.insertWidget(1, shared.viewer)

    def on_show(self) -> None:
        self.shown += 1


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180), layers=[Layer(id="c", spec=Spec(type="Circle"))]
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.load(path)
    yield win
    win.close()


def test_compose_is_the_default_page_with_every_shared_view(window) -> None:
    assert window.page == "compose" and next(iter(window.pages.pages)) == "compose"
    compose = window.pages.pages["compose"].widget
    for view in (window.viewer, window.timeline, window.layers, window.properties):
        assert compose.isAncestorOf(view) and view.isVisible()
    assert window.pages.bar.tabText(0) == "Compose" and not window.pages.bar.tabIcon(0).isNull()


def test_switching_pages_moves_the_views_and_parks_the_rest(window, qt_app) -> None:
    extra = ViewerOnly(window)
    window.pages.add(extra)
    window.show_page("viewer")
    qt_app.processEvents()
    assert window.page == "viewer" and extra.shown == 1
    assert extra.widget.isAncestorOf(window.viewer) and window.viewer.isVisible()
    for view in (window.timeline, window.layers, window.properties):
        assert view.parentWidget() is window.pages.parking and not view.isVisible()
        assert not view.isWindow()  # parked, never a floating window
    window.seek(0.5)  # the one canvas still draws on the other page
    assert window.canvas.isVisible()
    window.show_page("compose")
    qt_app.processEvents()
    assert window.pages.pages["compose"].widget.isAncestorOf(window.timeline) and window.timeline.isVisible()
    assert window.pages.bar.currentIndex() == 0


def test_the_page_bar_switches_pages(window, qt_app) -> None:
    window.pages.add(ViewerOnly(window))
    window.pages.bar.setCurrentIndex(window.pages.bar.count() - 1)  # the page just added
    assert window.page == "viewer"
    window.pages.bar.setCurrentIndex(0)
    assert window.page == "compose"
    with pytest.raises(KeyError):
        window.show_page("nowhere")


def test_view_pages_has_a_shortcut_per_page(window) -> None:
    action = menu_action(window.menuBar(), "View", "Pages", "Compose")
    assert action.shortcut().toString() == "Shift+1"


def test_splitter_sizes_are_kept_per_page(window, qt_app) -> None:
    window.pages.add(ViewerOnly(window))
    compose = window.pages.pages["compose"]
    compose.outer.setSizes([300, 600, 300])
    compose.centre.setSizes([500, 200])
    qt_app.processEvents()
    before = (compose.outer.sizes(), compose.centre.sizes())
    window.show_page("viewer")
    window.show_page("compose")
    qt_app.processEvents()
    assert (compose.outer.sizes(), compose.centre.sizes()) == before


def test_hidden_panels_stay_hidden_on_every_page(window, qt_app) -> None:
    window.pages.add(ViewerOnly(window))
    toggle = menu_action(window.menuBar(), "View", "Properties")
    toggle.setChecked(False)
    assert not window.properties.isVisible()
    window.show_page("viewer")
    window.show_page("compose")
    assert not window.properties.isVisible() and window.layers.isVisible()
    toggle.setChecked(True)
    assert window.properties.isVisible()
