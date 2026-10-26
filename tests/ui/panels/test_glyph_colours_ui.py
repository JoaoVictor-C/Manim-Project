"""Colour characters... (ADR 0055): the dialog's selection and colouring, driven with real mouse and
key events, and the ways to it (Properties, Layers, Edit) - one undo step on OK, none on Cancel."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog

from manim_studio.core.model import glyph_colours as gc
from manim_studio.core.model.schema import Layer, PartKey, Project, Spec
from manim_studio.ui.panels.glyph_colours_dialog import GlyphColoursDialog
from manim_studio.ui.panels.layers_panel import LayersPanel
from manim_studio.ui.panels.properties_panel import PropertiesPanel
from manim_studio.ui.session.build_service import BuildService
from manim_studio.ui.session.document import Document
from qt_support import FakeWorker
from support import CANVAS

pytestmark = pytest.mark.ui

RED, GREEN, BLUE = "#ff0000", "#00ff00", "#0000ff"  # content: colours a user picks
NONE = Qt.KeyboardModifier.NoModifier
SHIFT, CTRL = Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.ControlModifier
EQ = r"a^2 + b^2 = c^2"


def project(**extra) -> Project:
    layers = [
        Layer(id="t", spec=Spec(type="Text", params={"text": "hello", **extra})),
        Layer(id="eq", spec=Spec(type="MathTex", params={"text": EQ})),
        Layer(id="c", spec=Spec(type="Circle")),
    ]
    return Project(canvas=CANVAS, layers=layers)


@pytest.fixture
def dialog(qt_app):
    widget = GlyphColoursDialog(project(), "t")
    widget.resize(800, 500)
    widget.show()
    qt_app.processEvents()
    yield widget
    widget.close()


def centre(dialog: GlyphColoursDialog, index: int) -> QPointF:
    return dialog.preview.glyph_rect(index).center()


def mouse(widget, kind: QEvent.Type, pos: QPointF, modifiers=NONE, buttons=Qt.MouseButton.LeftButton) -> None:
    button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    global_pos = QPointF(widget.mapToGlobal(pos.toPoint()))
    event = QMouseEvent(kind, pos, global_pos, button, buttons, modifiers)
    QApplication.sendEvent(widget, event)


def click(dialog: GlyphColoursDialog, pos: QPointF, modifiers=NONE) -> None:
    mouse(dialog.preview, QEvent.Type.MouseButtonPress, pos, modifiers)
    mouse(dialog.preview, QEvent.Type.MouseButtonRelease, pos, modifiers, Qt.MouseButton.NoButton)


def key(widget, key_code, modifiers=NONE) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key_code, modifiers))


def pixel(dialog: GlyphColoursDialog, index: int) -> QColor:
    """The painted colour at the most covered point of a glyph (on its outline, not in a hole)."""
    image = dialog.preview.grab().toImage()
    rect = dialog.preview.glyph_rect(index)
    counts: dict[str, int] = {}
    for x in range(int(rect.left()), int(rect.right())):
        for y in range(int(rect.top()), int(rect.bottom())):
            name = image.pixelColor(x, y).name()
            counts[name] = counts.get(name, 0) + 1
    background = dialog.background
    return QColor(max((n for n in counts if n != background), key=counts.get))


# -- the dialog --------------------------------------------------------------------------------------------


def test_the_dialog_shows_each_glyph_with_its_label(dialog) -> None:
    assert len(dialog.paths) == 5 and dialog.labels == list("hello")
    assert "5 glyphs, 0 selected" in dialog.status.text()
    rects = [dialog.preview.glyph_rect(i) for i in range(5)]
    assert [r.center().x() for r in rects] == sorted(r.center().x() for r in rects)  # left to right
    assert all(r.width() > 20 for r in rects)  # large
    mouse(dialog.preview, QEvent.Type.MouseMove, centre(dialog, 1), buttons=Qt.MouseButton.NoButton)
    assert dialog.preview.toolTip() == "Glyph 2: e - the object's colour"


def test_click_shift_click_ctrl_click_and_empty_click_select_like_a_list(dialog) -> None:
    click(dialog, centre(dialog, 2))
    assert dialog.selected == {2}
    click(dialog, centre(dialog, 4), SHIFT)
    assert dialog.selected == {2, 3, 4}
    click(dialog, centre(dialog, 3), CTRL)
    assert dialog.selected == {2, 4}
    click(dialog, centre(dialog, 0), CTRL)
    assert dialog.selected == {0, 2, 4}
    click(dialog, QPointF(3, 3))  # the corner: no glyph
    assert dialog.selected == set()
    assert dialog.colour_button.isEnabled() is False and dialog.clear_button.isEnabled() is False


def test_a_rubber_band_selects_the_glyphs_it_touches(dialog) -> None:
    a, b = dialog.preview.glyph_rect(0), dialog.preview.glyph_rect(1)
    start = QPointF(a.left() - 6, a.top() - 6)
    end = QPointF(b.center().x(), b.bottom() + 6)
    mouse(dialog.preview, QEvent.Type.MouseButtonPress, start)
    mouse(dialog.preview, QEvent.Type.MouseMove, (start + end) / 2)
    mouse(dialog.preview, QEvent.Type.MouseMove, end)
    assert dialog.preview.band is not None
    mouse(dialog.preview, QEvent.Type.MouseButtonRelease, end, buttons=Qt.MouseButton.NoButton)
    assert dialog.selected == {0, 1} and dialog.preview.band is None


def test_ctrl_a_selects_all_and_escape_clears_then_closes(dialog) -> None:
    key(dialog.preview, Qt.Key.Key_A, CTRL)
    assert dialog.selected == {0, 1, 2, 3, 4}
    key(dialog.preview, Qt.Key.Key_Escape)
    assert dialog.selected == set() and dialog.isVisible()
    key(dialog.preview, Qt.Key.Key_Escape)
    assert dialog.result() == QDialog.DialogCode.Rejected and not dialog.isVisible()


def test_the_strip_mirrors_the_glyphs_and_follows_the_arrow_keys(dialog) -> None:
    strip = dialog.strip
    mouse(strip, QEvent.Type.MouseButtonPress, QPointF(strip.swatch(1).center()))
    assert dialog.selected == {1}
    key(strip, Qt.Key.Key_Right)
    assert dialog.selected == {2}
    key(strip, Qt.Key.Key_Right, SHIFT)
    key(strip, Qt.Key.Key_Right, SHIFT)
    assert dialog.selected == {2, 3, 4}
    key(strip, Qt.Key.Key_Home)
    assert dialog.selected == {0}
    key(strip, Qt.Key.Key_End)
    key(strip, Qt.Key.Key_Space)  # adds or removes the current one
    assert dialog.selected == set()
    key(strip, Qt.Key.Key_Left)
    assert dialog.selected == {3}


def test_colour_and_clear_apply_to_the_selection_and_the_preview_paints_it(dialog) -> None:
    click(dialog, centre(dialog, 2))
    click(dialog, centre(dialog, 3), SHIFT)  # the two l's
    asked = []
    dialog.ask_colour = lambda current: asked.append(current) or RED
    dialog.colour_button.click()
    assert dialog.colours == [None, None, RED, RED, None] and asked == ["#ffffff"]
    assert pixel(dialog, 2) == QColor(RED) and pixel(dialog, 1) == QColor("#ffffff")
    click(dialog, centre(dialog, 3))
    dialog.clear_button.click()
    assert dialog.colours == [None, None, RED, None, None]
    image = dialog.strip.grab().toImage()
    swatch = dialog.strip.swatch(2)
    assert image.pixelColor(swatch.left() + 4, swatch.top() + 4) == QColor(RED)  # the strip too
    dialog.ask_colour = lambda current: None  # cancelled: nothing changes
    dialog.colour_button.click()
    assert dialog.colours == [None, None, RED, None, None]


def test_gradient_rainbow_and_alternate_cover_the_selection_or_everything(dialog) -> None:
    asked = []
    dialog.ask_two_colours = lambda title, labels, colours: asked.append((title, labels)) or (RED, BLUE)
    dialog.gradient_button.click()  # nothing selected: every glyph
    assert dialog.colours == gc.gradient([RED, BLUE], 5) and asked == [("Gradient", ("Start", "End"))]
    click(dialog, centre(dialog, 1))
    click(dialog, centre(dialog, 3), SHIFT)
    dialog.rainbow_button.click()
    assert dialog.colours[1:4] == gc.rainbow(3) and dialog.colours[0] == RED and dialog.colours[4] == BLUE
    dialog.ask_two_colours = lambda title, labels, colours: (GREEN, RED)
    dialog.alternate_button.click()
    assert dialog.colours[1:4] == [GREEN, RED, GREEN]
    dialog.ask_two_colours = lambda title, labels, colours: None
    dialog.gradient_button.click()
    assert dialog.colours[1:4] == [GREEN, RED, GREEN]
    dialog.reset_button.click()
    assert dialog.colours == [None] * 5


def test_the_dialog_starts_from_the_current_colours_and_shows_part_colours(qt_app) -> None:
    widget = GlyphColoursDialog(project(glyph_colours=[None, GREEN]), "t")
    assert widget.colours == [None, GREEN, None, None, None]
    widget.close()


@pytest.mark.latex
def test_an_equation_lists_its_tex_glyphs_and_a_coloured_part_wins(qt_app) -> None:
    p = project()
    part = Layer(id="b", parent_id="eq", part=PartKey(tex="b^2"), style={"fill": RED})
    p = p.model_copy(update={"layers": [*p.layers, part]})
    widget = GlyphColoursDialog(p, "eq")
    assert widget.labels == ["a", "2", "+", "b", "2", "=", "c", "2"]
    assert widget.parts == {3: RED, 4: RED} and widget.shown_colour(3) == RED
    assert "part's colour" in widget.describe(3) and "coloured part" in widget.status.text()
    widget.close()


def test_without_latex_an_equation_disables_the_dialog_and_a_text_still_works(
    qt_app, monkeypatch, tmp_path
) -> None:
    import uuid

    monkeypatch.setenv("PATH", str(tmp_path))
    unseen = Spec(type="MathTex", params={"text": rf"x + \text{{{uuid.uuid4().hex[:8]}}}"})
    p = Project(
        canvas=CANVAS,
        layers=[Layer(id="eq", spec=unseen), Layer(id="t", spec=Spec(type="Text", params={"text": "hi"}))],
    )
    widget = GlyphColoursDialog(p, "eq")
    assert widget.problem is not None and "LaTeX is not installed" in widget.status.text()
    assert not widget.preview.isEnabled() and not widget.ok_button.isEnabled()
    assert not any(b.isEnabled() for b in widget._controls())
    widget.close()
    text = GlyphColoursDialog(p, "t")
    assert text.problem is None and len(text.paths) == 2 and text.ok_button.isEnabled()
    text.close()


# -- the ways to it ----------------------------------------------------------------------------------------


def undo_texts(document: Document) -> list[str]:
    return [document.undo_stack.text(i) for i in range(document.undo_stack.count())]


@pytest.fixture
def panel(qt_app):
    worker = FakeWorker()
    widget = PropertiesPanel(BuildService(Document(project()), worker))
    widget.worker = worker
    widget.show()
    yield widget
    widget.close()


@pytest.fixture
def layers(qt_app):
    worker = FakeWorker()
    widget = LayersPanel(BuildService(Document(project()), worker))
    widget.worker = worker
    widget.messages = []
    widget.message.connect(widget.messages.append)
    widget.show()
    yield widget
    widget.close()


def test_properties_has_the_button_only_for_texts_and_ok_is_one_undo_step(qt_app, panel) -> None:
    panel.show_layer("c")
    assert panel.characters_button is None
    for layer_id in ("eq", "t"):
        panel.show_layer(layer_id)
        qt_app.processEvents()  # a layout shows new children on the next turn of the event loop
        assert panel.characters_button is not None and panel.characters_button.isVisibleTo(panel)
        # in the object's own section (a Lumen Section now, not a group box)
        section = panel.sections[panel.project.layer(layer_id).spec.type]
        assert section.isAncestorOf(panel.characters_button)
    seen = []
    panel.ask_glyph_colours = lambda layer_id, current: seen.append((layer_id, current)) or [None, RED]
    panel.characters_button.click()
    panel.worker.reply_all()
    assert panel.project.layer("t").spec.params[gc.PARAM] == [None, RED]
    assert undo_texts(panel.document) == ["Colour characters"] and seen == [("t", None)]
    panel.ask_glyph_colours = lambda layer_id, current: None  # Cancel
    panel.characters_button.click()
    panel.ask_glyph_colours = lambda layer_id, current: [None, RED, None]  # OK with nothing changed
    submitted = []
    submit = panel.builds.submit
    panel.builds.submit = lambda *args, **kwargs: submitted.append(args) or submit(*args, **kwargs)
    panel.characters_button.click()
    assert submitted == []  # nothing to build or undo
    panel.worker.reply_all()
    assert undo_texts(panel.document) == ["Colour characters"]
    panel.document.undo_stack.undo()
    assert gc.PARAM not in panel.project.layer("t").spec.params


def test_the_pieces_section_points_to_colour_characters(qt_app, panel) -> None:
    from PySide6.QtWidgets import QLabel

    panel.show_layer("t")
    qt_app.processEvents()
    hints = [w.text() for w in panel.body.findChildren(QLabel) if w.objectName() == "hint" and w.isVisible()]
    assert any("Colour characters..." in text for text in hints)


def test_layers_offer_colour_characters_on_texts_only(layers) -> None:
    texts = lambda layer_id: [a.text() for a in layers.context_menu(layer_id).actions() if a.text()]  # noqa: E731
    layers.select("t")
    assert "Colour Characters..." in texts("t")
    layers.select("c")
    assert "Colour Characters..." not in texts("c")
    assert layers.colour_characters("c") is False and "not a Text" in layers.messages[-1]
    layers.select("t")
    layers.ask_glyph_colours = lambda layer_id, current: [BLUE]
    action = next(a for a in layers.context_menu("t").actions() if a.text() == "Colour Characters...")
    action.trigger()
    layers.worker.reply_all()
    assert layers.project.layer("t").spec.params[gc.PARAM] == [BLUE]
    assert undo_texts(layers.document) == ["Colour characters"]


def test_the_edit_menu_opens_it_for_the_selection(qt_app, tmp_path) -> None:
    from manim_studio.ui.main_window import MainWindow

    path = tmp_path / "p.json"
    path.write_text(project().model_dump_json(by_alias=True), encoding="utf-8")
    window = MainWindow()
    window.load(path)
    window.selection.select_layer("t")
    asked = []
    window.layers.ask_glyph_colours = lambda layer_id, current: asked.append(layer_id)
    window.characters_action.trigger()
    assert asked == ["t"]
    window.close()
