"""The Code page's cards for the tools added since the first design (ADR 0067, 0084): the error card that
knows its line and its time, the farm chip with its popover, the controls of a Python object's parameters, and
the preview as one card."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.code.farm_chip import FarmChip, FarmEntry, counts
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.pages.code import clock_text
from manim_studio.ui.pages.code_controls import (
    ControlsPanel,
    ParamSliderField,
    SwitchField,
    control_field,
    has_range,
)
from manim_studio.ui.services.code_render import CodeStatus
from manim_studio.ui.style.card import Chip

pytestmark = pytest.mark.ui

ORBIT = "class Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n        self.add(Squre())\n"
SPIN = "class Spin(Scene):\n    def construct(self):\n        self.add(Square())\n"
POLY = (
    "PARAMS = {\n"
    '    "radius": {"type": "float", "default": 1.5, "min": 0.2, "max": 4.0, "unit": "m"},\n'
    '    "sides": {"type": "int", "default": 5, "min": 3, "max": 12},\n'
    '    "free": {"type": "float", "default": 1.0},\n'
    '    "filled": {"type": "bool", "default": True},\n'
    '    "tint": {"type": "color", "default": "#3b82f6"},\n'
    "}\n\ndef build(p):\n    return RegularPolygon(p['sides'], radius=p['radius'])\n"
)


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=12.0),
        layers=[
            Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": ORBIT})),
            Layer(id="spin", name="Spin", spec=Spec(type="Code", params={"code": SPIN})),
            Layer(id="poly", name="Polygon", spec=Spec(type="Python", params={"code": POLY})),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1440, 900)
    win.show()
    win.load(path)
    win.show_page("code")
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def page(window):
    return window.pages.pages["code"]


def set_statuses(window, **statuses: CodeStatus) -> None:
    window.code.status = lambda layer_id: statuses.get(layer_id)
    for layer_id in statuses:
        window.code.statusChanged.emit(layer_id)


# -- the error card -------------------------------------------------------------------------------------


def error(**fields) -> CodeStatus:
    return CodeStatus(
        "error", error="name 'Squre' is not defined", line=4, error_type="NameError", seconds=4.2, **fields
    )


def test_an_error_is_a_card_with_the_exception_a_sentence_and_where_to_look(window) -> None:
    code = page(window)
    code.open_item("orbit")
    assert not code.error_card.isVisibleTo(code.widget)
    set_statuses(window, orbit=error())
    assert code.error_card.isVisibleTo(code.widget) and code.output_card.isAncestorOf(code.error_card)
    assert code.error_card.isAncestorOf(code.error_type_chip) and code.error_type_chip.text() == "NameError"
    assert code.error_type_chip.property("tone") == "bad"
    assert "name 'Squre' is not defined" in code.error_label.plain
    for button in (code.goto_error_button, code.failure_button):
        assert code.error_card.isAncestorOf(button) and button.property("role") == "ghost"
        assert button.isVisibleTo(code.widget)
    assert code.goto_error_button.text() == "Go to line"
    assert code.failure_button.text() == "Go to layer at 0:04.20"
    assert code.hint_card.isVisibleTo(code.widget) and "Square" in code.hint_title.text()  # the hint stays
    set_statuses(window, orbit=CodeStatus("ready", frames=3))
    assert not code.error_card.isVisibleTo(code.widget)


def test_go_to_line_moves_the_cursor_and_go_to_layer_moves_the_playhead(window) -> None:
    code = page(window)
    code.open_item("orbit")
    set_statuses(window, orbit=error())
    code.goto_error_button.click()
    assert code.editor.textCursor().blockNumber() + 1 == 4
    start = window.evaluator.lifetime(window.project.layer("orbit"))[0]
    code.failure_button.click()
    assert window.t == pytest.approx(min(start + 4.2, window.project.canvas.duration))
    assert window.page == "animate"


def test_the_time_is_the_layers_start_plus_how_far_it_got_and_never_past_the_end(window) -> None:
    code = page(window)
    code.open_item("orbit")
    set_statuses(window, orbit=CodeStatus("error", error="x", line=1, error_type="Error", seconds=99.0))
    assert code.failure_button.text() == f"Go to layer at {clock_text(window.project.canvas.duration)}"
    set_statuses(window, orbit=CodeStatus("error", error="x", line=1, error_type="Error"))
    assert not code.failure_button.isVisibleTo(code.widget)  # no time known: nothing to go to
    assert clock_text(0) == "0:00.00" and clock_text(65.5) == "1:05.50" and clock_text(4.2) == "0:04.20"


# -- the farm chip --------------------------------------------------------------------------------------


def test_the_toolbar_counts_the_code_layers_rendering_over_all_of_them(window) -> None:
    code = page(window)
    chip = code.farm_chip
    assert isinstance(chip, FarmChip) and chip.isVisibleTo(code.widget)
    assert code.editor_card.isAncestorOf(chip) and chip.text() == "Farm 0 / 2"  # the object is not a scene
    assert chip.property("tone") == "neutral"
    set_statuses(window, orbit=CodeStatus("rendering", frames=2), spin=CodeStatus("queued"))
    assert chip.text() == "Farm 1 / 2" and chip.property("tone") == "accent"
    set_statuses(window, orbit=CodeStatus("ready", frames=9), spin=CodeStatus("ready", frames=9))
    assert chip.text() == "Farm 0 / 2" and chip.property("tone") == "neutral"
    assert counts([FarmEntry("a", "A", "rendering"), FarmEntry("b", "B", "queued")]) == (1, 2)


def test_the_popover_lists_each_layers_state_with_run_again_and_stop(window, monkeypatch) -> None:
    code = page(window)
    set_statuses(window, orbit=error(), spin=CodeStatus("rendering", frames=1))
    chip = code.farm_chip
    chip.toggle_popover()
    popover = chip.popover
    assert popover.isVisible()
    rows = {row.entry.layer_id: row for row in popover.findChildren(type(popover.rows.itemAt(0).widget()))}
    assert [rows[i].chip.text() for i in ("orbit", "spin")] == ["Failed", "Running"]
    assert rows["orbit"].run_button is not None and rows["orbit"].stop_button is None
    assert rows["spin"].stop_button is not None and rows["spin"].run_button is None
    assert rows["orbit"].chip.property("tone") == "bad" and rows["spin"].chip.property("tone") == "accent"
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(window.code, "retry", lambda layer_id: calls.append(("retry", layer_id)))
    monkeypatch.setattr(window.code, "cancel", lambda layer_id: calls.append(("cancel", layer_id)) or True)
    rows["orbit"].run_button.click()
    rows["spin"].stop_button.click()
    assert calls == [("retry", "orbit"), ("cancel", "spin")]
    chip.toggle_popover()
    assert not popover.isVisible()


def test_a_name_in_the_popover_opens_that_layer(window) -> None:
    code = page(window)
    code.farm_chip.openRequested.emit("spin")
    assert code.layer_id == "spin"


def test_a_project_without_code_layers_has_no_farm_chip(qt_app, tmp_path) -> None:
    project = Project(canvas=Canvas(width_px=160, height_px=90, fps=10, duration=2.0), layers=[])
    path = tmp_path / "empty.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.load(path)
    win.show_page("code")
    qt_app.processEvents()
    assert not page(win).farm_chip.isVisibleTo(page(win).widget)
    win.document.undo_stack.setClean()
    win.close()


# -- the controls ---------------------------------------------------------------------------------------


def test_a_number_with_a_range_is_a_slider_a_yes_no_a_switch_a_colour_a_swatch(window, qt_app) -> None:
    window.selection.select_layer("poly")
    values = page(window).values
    assert isinstance(values, ControlsPanel)
    fields = values.fields
    assert isinstance(fields["radius"], ParamSliderField) and isinstance(fields["sides"], ParamSliderField)
    assert not isinstance(fields["free"], ParamSliderField)  # no range declared: a number field
    assert isinstance(fields["filled"], SwitchField)
    assert type(fields["tint"]).__name__ == "ColorField"
    assert fields["radius"].widget.readout.text() == "1.50 m" and fields["sides"].widget.readout.text() == "5"
    assert fields["filled"].widget.isChecked() and fields["filled"].widget.text() == "Filled"


def test_moving_a_slider_changes_the_object_through_the_document(window, qt_app) -> None:
    window.selection.select_layer("poly")
    fields = page(window).values.fields
    before = window.document.undo_stack.count()
    slider = fields["sides"].widget.slider
    slider.setValue(slider.maximum())  # a keyboard or drag move to the end of the range
    for _ in range(20):
        qt_app.processEvents()
    assert window.project.layer("poly").spec.params["values"]["sides"] == 12
    assert isinstance(window.project.layer("poly").spec.params["values"]["sides"], int)
    assert window.document.undo_stack.count() > before
    assert fields["sides"].widget.readout.text() == "12"


def test_a_switch_commits_at_once(window, qt_app) -> None:
    window.selection.select_layer("poly")
    switch = page(window).values.fields["filled"].widget
    switch.click()
    for _ in range(20):
        qt_app.processEvents()
    assert window.project.layer("poly").spec.params["values"]["filled"] is False
    assert not switch.isChecked()


def test_has_range_wants_both_ends() -> None:
    from manim_studio.core.engine.adapter import Param

    assert has_range(Param("a", "float", 1.0, minimum=0.0, maximum=2.0))
    assert not has_range(Param("a", "float", 1.0, minimum=0.0))
    assert not has_range(Param("a", "float", 1.0, minimum=2.0, maximum=2.0))
    assert not has_range(Param("a", "float", 1.0, minimum=-1e6, maximum=1e6))  # the adapter's "not declared"
    assert not has_range(Param("a", "text", "x", minimum=0.0, maximum=2.0))
    assert isinstance(control_field(Param("a", "bool", True), lambda v: None), SwitchField)


# -- one card for the preview ---------------------------------------------------------------------------


def test_the_preview_is_one_card_with_the_stage_header_only(window) -> None:
    code = page(window)
    assert not code.preview_card.header.isVisibleTo(code.widget)  # no PREVIEW title over the STAGE one
    assert code.preview_card.isAncestorOf(window.viewer)
    assert isinstance(code.preview_chip, Chip) and code.editor_card.isAncestorOf(code.preview_chip)
    set_statuses(window, orbit=CodeStatus("ready", frames=9))
    code.open_item("orbit")
    assert code.preview_chip.isVisibleTo(code.widget) and code.preview_chip.text() == "Ready · 9 frames"
