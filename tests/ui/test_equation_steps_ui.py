"""Equation steps in the editor (P11, ADR 0054): Layers > Add > Equation steps... and
Animate > Equation Steps... open a dialog; its lines are checked as they are typed, a line can be
derived from another, and OK adds the steps as one undo step with the new layers selected."""

from __future__ import annotations

import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialogButtonBox

from manim_studio.core.equation_steps import MATCHING
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.build_service import BuildService
from manim_studio.ui.document import Document
from manim_studio.ui.equation_steps_dialog import EquationStepsDialog
from manim_studio.ui.layers_panel import LayersPanel
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.preferences import Preferences
from qt_support import FakeWorker

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=2.0)
PYTHAGORAS = [r"A = L \times L", r"L = a+b", r"A = (a+b) \times (a+b)"]


def ok_button(dialog: EquationStepsDialog):
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)


def rows(dialog: EquationStepsDialog) -> list[str]:
    return [dialog.preview.item(i).text() for i in range(dialog.preview.count())]


def pick(dialog: EquationStepsDialog, operation: str) -> None:
    dialog.operation.setCurrentIndex(dialog.operation.findData(operation))


@pytest.fixture
def builds(qt_app):
    worker = FakeWorker()
    service = BuildService(Document(Project(canvas=CANVAS)), worker)
    service.worker = worker
    return service


# -- the dialog ----------------------------------------------------------------------------------


def test_typing_lines_previews_the_steps_and_the_morphs_between_them(builds) -> None:
    dialog = EquationStepsDialog(1.5, builds)
    assert not ok_button(dialog).isEnabled() and "Type the steps" in dialog.status.text()
    dialog.text.setPlainText("\n".join(PYTHAGORAS[:2]) + "\n% a note\n")
    assert dialog.steps == PYTHAGORAS[:2]
    assert rows(dialog)[0].startswith(r"1.  A = L \times L")
    assert rows(dialog)[1] == "    then a matching morph (1 new term)"
    assert rows(dialog)[2].startswith("2.  L = a+b")
    assert dialog.start.value() == 1.5  # the playhead
    assert all(
        w.toolTip() for w in (dialog.text, dialog.operation, dialog.term, dialog.add_line, dialog.preview)
    )
    assert all(w.toolTip() for w in (dialog.start, dialog.step_duration, dialog.hold, dialog.font_size))
    assert all(
        w.toolTip() for w in (dialog.entrance, dialog.colour, dialog.highlight, dialog.highlight_colour)
    )


def test_add_line_derives_from_the_last_or_the_selected_step(builds) -> None:
    dialog = EquationStepsDialog(0.0, builds)
    assert not dialog.derive_line() and "Type an equation first" in dialog.status.text()
    dialog.text.setPlainText("\n".join(PYTHAGORAS[:2]))
    pick(dialog, "square")
    assert not dialog.term.isEnabled()
    assert dialog.derive_line()
    assert dialog.steps[-1] == "L^2 = (a+b)^2"  # from the last line
    dialog.preview.setCurrentRow(0)  # step 1
    pick(dialog, "substitute")
    assert dialog.term.isEnabled() and "symbol = value" in dialog.term.placeholderText()
    dialog.term.setText("L = a+b")
    assert dialog.derive_line()
    assert dialog.steps[-1] == PYTHAGORAS[2]
    pick(dialog, "divide")
    dialog.term.setText("")
    assert (
        not dialog.derive_line() and "Cannot derive the next line: type the divisor" in dialog.status.text()
    )
    assert dialog.steps[-1] == PYTHAGORAS[2]  # nothing added


def test_each_line_is_checked_quickly_then_with_latex_through_the_worker(builds) -> None:
    dialog = EquationStepsDialog(0.0, builds)
    dialog.text.setPlainText("x = 1\n\\frac{x}{")
    assert "Step 2 cannot be added" in dialog.status.text() and "missing" in dialog.status.text()
    assert not ok_button(dialog).isEnabled()
    assert builds.worker.requests == {}  # nothing goes to the worker while typing
    dialog.text.setPlainText("x = 1\nx = \\badcommand")
    assert "Checking 2 lines" in dialog.status.text() and not builds.worker.requests
    dialog.refresh(check=True)  # the typing pause: the lines go to the worker
    assert len(builds.worker.requests) == 2
    builds.worker.reply(Spec(type="MathTex", params={"text": "x = 1"}))
    assert "Checking 1 line" in dialog.status.text()
    builds.worker.reply(
        Spec(type="MathTex", params={"text": "x = \\badcommand"}), ok=False, error="LaTeX error: Undefined"
    )
    assert "Step 2 cannot be added: LaTeX error: Undefined" in dialog.status.text()
    assert rows(dialog)[-1].endswith("- LaTeX error: Undefined") and not ok_button(dialog).isEnabled()
    dialog.text.setPlainText("x = 1\nx = 2")
    dialog.refresh(check=True)
    builds.worker.reply(Spec(type="MathTex", params={"text": "x = 2"}))
    assert dialog.status.text() == "2 steps, 1 morph." and ok_button(dialog).isEnabled()


def test_ok_refuses_while_a_line_cannot_be_added(builds) -> None:
    dialog = EquationStepsDialog(0.0, builds)
    dialog.text.setPlainText("x = 1\n\\frac{x}{")
    dialog.accept()  # Enter in a field, say
    assert dialog.result() != EquationStepsDialog.DialogCode.Accepted
    assert Preferences().option("steps/hold", -1.0) == -1.0  # nothing remembered either


def test_without_a_worker_lines_are_built_when_the_steps_are_added(qt_app) -> None:
    service = BuildService(Document(Project(canvas=CANVAS)), FakeWorker(available=False))
    dialog = EquationStepsDialog(0.0, service)
    dialog.text.setPlainText("x = 1")
    assert "LaTeX builds the lines when the steps are added" in dialog.status.text()
    assert ok_button(dialog).isEnabled()


def test_without_latex_the_dialog_says_so_and_still_adds(builds, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert shutil.which("latex") is None
    dialog = EquationStepsDialog(0.0, builds)
    dialog.text.setPlainText("x = 1\nx + 1 = 2")
    assert "LaTeX is not installed" in dialog.status.text() and "placeholders" in dialog.status.text()
    dialog.refresh(check=True)  # the typing pause sends nothing: it could only fail
    assert ok_button(dialog).isEnabled() and builds.worker.requests == {}


def test_the_options_are_remembered_for_next_time(builds) -> None:
    dialog = EquationStepsDialog(0.0, builds)
    dialog.text.setPlainText("x = 1")
    dialog.hold.setValue(0.25)
    dialog.font_size.setValue(36)
    dialog.entrance.setCurrentText("FadeIn")
    dialog.highlight.setChecked(False)
    dialog.place.setCurrentText("Centre")
    dialog.ask_colour = lambda current: "#00ff00"  # content: the user's choice
    dialog.colour.click()
    dialog.accept()
    request = dialog.request()
    assert (request.hold, request.font_size, request.entrance, request.colour) == (
        0.25,
        36,
        "FadeIn",
        "#00ff00",
    )
    assert request.highlight_colour is None and not request.free_spot
    again = EquationStepsDialog(3.0, builds)
    assert (again.hold.value(), again.font_size.value(), again.entrance.currentText()) == (0.25, 36, "FadeIn")
    assert not again.highlight.isChecked() and again.colour.property("colour") == "#00ff00"
    assert again.start.value() == 3.0 and Preferences().option("steps/hold", 1.0) == 0.25


# -- adding them ---------------------------------------------------------------------------------


@pytest.fixture
def panel(qt_app):
    worker = FakeWorker()
    doc = Document(Project(canvas=CANVAS, layers=[Layer(id="dot", spec=Spec(type="Dot"))]))
    widget = LayersPanel(BuildService(doc, worker))
    widget.worker = worker
    widget.messages = []
    widget.message.connect(widget.messages.append)
    widget.show()
    yield widget
    widget.close()


def answer(lines, **changes):
    def ask(start: float):
        dialog = EquationStepsDialog(start, None)
        dialog.text.setPlainText("\n".join(lines))
        dialog.place.setCurrentText("Centre")
        for name, value in changes.items():
            getattr(dialog, name).setValue(value)
        return dialog.request()

    return ask


def test_the_add_menu_offers_equation_steps(panel) -> None:
    action = next(a for a in panel.library_menu.actions() if a.text() == "Equation steps...")
    assert action is panel.equation_steps_action and action.toolTip()
    texts = [a.text() for a in panel.library_menu.actions()]
    assert texts.index("Equation steps...") == texts.index("MathTex") + 1


def test_cancelling_adds_nothing(panel) -> None:
    panel.ask_steps = lambda start: None
    panel.add_equation_steps()
    assert len(panel.project.layers) == 1 and panel.document.undo_stack.count() == 0


def test_the_steps_wait_for_the_worker_then_are_one_undo_step_and_selected(panel) -> None:
    panel.playhead = lambda: 0.5
    panel.ask_steps = answer(["x = 1", "x + 1 = 1 + 1"], hold=0.5)
    panel.add_equation_steps()
    assert len(panel.project.layers) == 1  # the formulas are built by the worker first
    panel.worker.reply_all()
    panel.worker.reply_all()  # the coloured step is built again with its part's marker
    roots = panel.project.roots()
    assert [r.name for r in roots] == ["", "Step 1", "Step 2"]
    one, two = roots[1:]
    assert one.clips[0].start == 0.5 and one.clips[1].to_layer == two.id and one.clips[1].kind == MATCHING
    assert [p.part.tex for p in panel.project.children(two.id)] == ["+ 1", "+ 1"]
    assert panel.selected_ids() == [two.id, one.id]  # both new objects (front first)
    stack = panel.document.undo_stack
    assert [stack.text(i) for i in range(stack.count())] == ["Add equation steps"]
    stack.undo()
    assert [x.id for x in panel.project.layers] == ["dot"]


@pytest.mark.latex
def test_a_free_spot_is_below_what_is_there_once_the_steps_can_be_measured(qt_app) -> None:
    square = Layer(id="sq", spec=Spec(type="Square", params={"side_length": 3}))
    doc = Document(Project(canvas=CANVAS, layers=[square]))
    worker = FakeWorker()
    widget = LayersPanel(BuildService(doc, worker))
    lines = PYTHAGORAS[:2]

    def ask(start: float):
        dialog = EquationStepsDialog(start, None)
        dialog.text.setPlainText("\n".join(lines))
        dialog.place.setCurrentText("Free spot")
        return dialog.request()

    widget.ask_steps = ask
    widget.add_equation_steps()  # cold: nothing is measured in the UI thread
    worker.reply_all()  # warm: the edit runs again and measures the steps
    x, y = widget.project.roots()[1].base.position
    assert x == 0.0 and y < -1.5  # below the square (its bottom is at -1.5)
    assert {r.base.position for r in widget.project.roots()[1:]} == {(x, y)}
    widget.close()


def test_without_latex_the_steps_are_added_at_once_as_placeholders(panel, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    panel.ask_steps = answer(["x = 1", "x = 2"])
    panel.add_equation_steps()
    assert [r.name for r in panel.project.roots()][1:] == ["Step 1", "Step 2"]
    assert panel.worker.requests == {}  # no build that cannot succeed
    assert "LaTeX is not installed" in panel.messages[-1]


# -- the real window ------------------------------------------------------------------------------


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "proof.json"
    path.write_text(Project(canvas=CANVAS).model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


@pytest.mark.latex
def test_pythagoras_by_typing_and_deriving_in_the_real_window(window, qt_app) -> None:
    window.seek(1.0)
    seen = {}

    def ask(start: float):
        dialog = EquationStepsDialog(start, window.layers.builds)
        dialog.text.setPlainText("\n".join(PYTHAGORAS[:2]))
        dialog.preview.setCurrentRow(0)  # derive from step 1
        pick(dialog, "substitute")
        dialog.term.setText("L = a+b")
        assert dialog.derive_line()
        dialog.step_duration.setValue(0.5)
        dialog.hold.setValue(0.5)
        dialog.place.setCurrentText("Centre")
        seen["rows"], seen["ok"] = rows(dialog), ok_button(dialog).isEnabled()
        dialog.accept()
        return dialog.request()

    window.layers.ask_steps = ask
    window.equation_steps_action.trigger()
    assert seen["ok"] and seen["rows"][-1].startswith("3.  " + PYTHAGORAS[2])
    roots = window.document.project.roots()
    assert [r.spec.params["text"] for r in roots] == PYTHAGORAS
    assert [r.name for r in roots] == ["Step 1", "Step 2", "Step 3"]
    assert [c.start for c in roots[0].clips] == [1.0, 2.0] and roots[1].clips[0].start == 3.0
    assert set(window.selection.layer_ids) == {r.id for r in roots}
    assert window.document.undo_stack.count() == 1
    assert window.document.project.canvas.duration == pytest.approx(4.0)  # grew: last morph, then a hold
    window.seek(2.75)  # step 2, between the morphs
    qt_app.processEvents()
    assert next(i for i, _ in window.evaluator.frame_layers(2.75)) == roots[1].id
