"""Lumen fields and sections (P17.4a): collapsing, the colour field, the slider, the keyframe diamond,
and the panels building and painting in both themes."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel

from manim_studio.core.model.schema import Layer, Project, Spec
from manim_studio.ui.panels.layers_panel import LayersPanel
from manim_studio.ui.panels.properties_panel import PropertiesPanel
from manim_studio.ui.session.build_service import BuildService
from manim_studio.ui.session.document import Document
from manim_studio.ui.style import theme
from manim_studio.ui.style.fields import ColorField, KeyToggle, Section, SliderField
from qt_support import FakeWorker
from support import CANVAS

pytestmark = pytest.mark.ui


def test_a_section_collapses_and_says_so(qt_app) -> None:
    section = Section("Transform")
    section.add_widget(QLabel("x"))
    section.show()
    seen = []
    section.toggled.connect(seen.append)
    assert not section.is_collapsed() and section.body.isVisible()
    section.caret.click()
    assert section.is_collapsed() and not section.body.isVisible() and seen == [True]
    section.title.clicked.emit()  # the title opens it too
    assert not section.is_collapsed() and section.body.isVisible() and seen == [True, False]
    section.close()


def test_the_colour_field_shows_a_swatch_and_its_hex(qt_app) -> None:
    commits = []
    field = ColorField(commits.append)
    field.set_value("#ff0000")
    assert field.button.text() == "#ff0000" and field.button.colour == "#ff0000"
    field.set_value(None)
    assert field.button.text() == "Default" and field.button.colour is None
    field.reset_button.click()
    assert commits == []  # already the default
    field.set_value("#00ff00")
    field.reset_button.click()
    assert commits == [None]


def test_the_slider_commits_from_the_keyboard_and_shows_percent(qt_app) -> None:
    commits = []
    field = SliderField(commits.append)
    field.set_value(0.5)
    assert field.widget.value() == pytest.approx(0.5) and field.widget.readout.text() == "50%"
    assert commits == []  # showing never commits
    field.widget.slider.setValue(field.widget.slider.value() + 100)
    assert commits == [pytest.approx(0.6)] and field.widget.readout.text() == "60%"


def test_the_key_diamond_is_a_toggle(qt_app) -> None:
    commits = []
    field = KeyToggle(commits.append, "Keyframes for scale")
    field.set_value(True)
    assert field.widget.isChecked() and commits == []
    field.widget.setChecked(False)
    assert commits == [False]


def test_pending_values_are_italic_without_a_colour_of_their_own(qt_app) -> None:
    field = ColorField(lambda v: None)
    field.set_value("#123456", pending=True)
    assert field.widget.property("pending") is True and "italic" in field.widget.styleSheet()
    assert "#" not in field.widget.styleSheet()  # the colour comes from the theme's pending rule
    field.set_value("#123456")
    assert field.widget.property("pending") is False and field.widget.styleSheet() == ""


@pytest.mark.parametrize("name", ["paper", "ink"])
def test_the_panels_build_and_paint_in_both_themes(qt_app, name) -> None:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="eq", spec=Spec(type="MathTex", params={"text": "x^2"})),
            Layer(id="code", spec=Spec(type="Code", params={"code": "x = 1"})),
            Layer(id="ball", spec=Spec(type="Circle")),
        ],
    )
    builds = BuildService(Document(project), FakeWorker())
    layers, properties = LayersPanel(builds), PropertiesPanel(builds)
    try:
        theme.set_theme(qt_app, name)
        for widget in (layers, properties):
            widget.resize(320, 700)
            widget.show()
        properties.show_layer("ball")
        QApplication.processEvents()
        assert not layers.grab().isNull() and not properties.grab().isNull()
        assert properties.sections["Transform"].isVisible()
    finally:
        theme.set_theme(qt_app, "ink")
        layers.close()
        properties.close()
