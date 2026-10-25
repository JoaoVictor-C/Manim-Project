"""The import window (P12.4): detected kinds preselected, options that are possible, placement, answer."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox

from manim_studio.core import code_import as ci
from manim_studio.core.code_import import ImportItem
from manim_studio.ui.import_code_dialog import ImportCodeDialog

pytestmark = pytest.mark.ui

SCENE = "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
TWO = SCENE + "\nclass Spin(Scene):\n    def construct(self):\n        self.add(Square())\n"
OBJECT = "PARAMS = {'size': (1.0, 0.5, 3.0)}\n\ndef build(p):\n    return Circle()\n"


def ok_enabled(dialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_the_detected_kind_is_preselected(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem(OBJECT, "wheel.py"), ImportItem(SCENE, "orbit.py")])
    first, second = dialog.states
    assert (first.as_, second.as_) == (ci.OBJECT, ci.SCENE)
    assert [c.name for c in dialog.choices()] == ["Wheel", "Orbit"]
    assert ok_enabled(dialog)


def test_impossible_kinds_are_disabled_with_the_reason(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem(OBJECT, "wheel.py")])
    assert dialog.radios[ci.OBJECT].isEnabled() and dialog.radios[ci.PRESET].isEnabled()
    assert not dialog.radios[ci.SCENE].isEnabled()
    assert "Not possible" in dialog.radios[ci.SCENE].toolTip()
    assert "(detected)" in dialog.radios[ci.OBJECT].text()


def test_a_file_that_does_not_parse_is_unchecked_and_blocks_import(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem("def build(:\n", "broken.py")])
    assert not dialog.states[0].include and "Not importable" in dialog.detected_label.text()
    assert not ok_enabled(dialog) and "Nothing is checked" in dialog.message.text()
    dialog.list.item(0).setCheckState(Qt.CheckState.Checked)
    assert not ok_enabled(dialog)  # checked but impossible: the reason is shown
    assert "SyntaxError" in dialog.message.text()


def test_a_file_that_is_neither_an_object_nor_a_scene_is_a_helper(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem("def double(x):\n    return 2 * x\n", "Grid Tools.py")])
    state = dialog.states[0]
    assert state.include and state.as_ == ci.HELPER and state.name == "grid_tools"
    assert "(detected)" in dialog.radios[ci.HELPER].text() and "Helper" in dialog.detected_label.text()
    assert not dialog.radios[ci.OBJECT].isEnabled() and not dialog.radios[ci.SCENE].isEnabled()
    assert dialog.place_box.isHidden() and dialog.trust.isVisibleTo(dialog)  # no time or place
    assert ok_enabled(dialog)
    dialog.radios[ci.PRESET].setChecked(True)  # a preset is named like the others: a title
    assert dialog.states[0].name == "Grid Tools" and not dialog.trust.isVisibleTo(dialog)
    dialog.radios[ci.HELPER].setChecked(True)
    assert dialog.states[0].name == "grid_tools"


def test_a_helper_needs_a_python_name(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem("X = 1\n", "x.py")])
    for bad, why in (("2 grids", "Python name"), ("json", "standard library"), ("numpy", "editor uses")):
        dialog.name_edit.setText(bad)
        dialog.name_edit.textEdited.emit(bad)
        assert not ok_enabled(dialog) and why in dialog.message.text()


def test_an_object_or_a_scene_can_still_become_a_helper(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem(OBJECT, "wheel.py")])
    assert dialog.radios[ci.HELPER].isEnabled() and dialog.states[0].as_ == ci.OBJECT
    dialog.radios[ci.HELPER].setChecked(True)
    choice = dialog.choices()[0]
    assert (choice.as_, choice.name) == (ci.HELPER, "wheel") and ok_enabled(dialog)


def test_without_a_project_a_helper_file_becomes_a_helper_preset(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem("X = 1\n", "consts.py")], has_project=False)
    assert dialog.states[0].as_ == ci.PRESET and not dialog.radios[ci.HELPER].isEnabled()
    assert ci.presets_of(dialog.choices()[0]) == [("Consts", "helper", "X = 1\n")]


def test_changing_the_kind_to_a_preset_hides_the_placement(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem(OBJECT, "wheel.py")])
    dialog.radios[ci.PRESET].setChecked(True)
    assert dialog.states[0].as_ == ci.PRESET
    assert dialog.place_box.isHidden() and not dialog.also_preset.isVisibleTo(dialog)
    choice = dialog.choices()[0]
    assert choice.as_ == ci.PRESET and choice.appear is None and choice.position is None


def test_scene_files_list_their_scenes_and_one_is_checked(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem(TWO, "pair.py")])
    assert dialog.scene_list.count() == 2 and not dialog.scene_list.isHidden()
    assert dialog.choices()[0].scenes == ("Orbit",)
    dialog.scene_list.item(1).setCheckState(Qt.CheckState.Checked)
    assert dialog.choices()[0].scenes == ("Orbit", "Spin")
    dialog.scene_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    dialog.scene_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    dialog.states[0].scenes = []
    assert ci.validate(dialog.choices()[0]) is None  # none checked means the first scene


def test_placement_defaults_follow_the_drop_and_can_be_changed(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem(OBJECT, "w.py")], playhead=1.5, at=3.0, position=(2.0, -1.0))
    choice = dialog.choices()[0]
    assert (choice.appear, choice.position) == (3.0, (2.0, -1.0))
    dialog.auto_time.setChecked(True)
    dialog.auto_position.setChecked(True)
    choice = dialog.choices()[0]
    assert choice.appear is None and choice.position is None
    plain = ImportCodeDialog([ImportItem(OBJECT, "w.py")], playhead=1.5)
    assert plain.choices()[0].appear is None and plain.time.value() == 1.5


def test_name_trust_and_copy_reach_the_answer(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem(OBJECT, "w.py")])
    dialog.name_edit.setText("My wheel")
    dialog.name_edit.textEdited.emit("My wheel")
    dialog.trust.setChecked(True)
    dialog.also_preset.setChecked(True)
    choice = dialog.choices()[0]
    assert (choice.name, choice.trust, choice.also_preset) == ("My wheel", True, True)
    dialog.name_edit.setText("")
    dialog.name_edit.textEdited.emit("")
    assert not ok_enabled(dialog) and "name" in dialog.message.text()


def test_without_a_project_only_presets_are_possible(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem(OBJECT, "w.py")], has_project=False)
    assert dialog.states[0].as_ == ci.PRESET
    assert not dialog.radios[ci.OBJECT].isEnabled() and dialog.radios[ci.PRESET].isEnabled()
    assert ok_enabled(dialog)


def test_switching_rows_keeps_each_items_edits(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem(OBJECT, "a.py"), ImportItem(SCENE, "b.py")])
    dialog.name_edit.setText("First")
    dialog.name_edit.textEdited.emit("First")
    dialog.list.setCurrentRow(1)
    assert dialog.name_edit.text() == "Orbit" and dialog.radios[ci.SCENE].isChecked()
    dialog.list.setCurrentRow(0)
    assert dialog.name_edit.text() == "First"
    assert [c.name for c in dialog.choices()] == ["First", "Orbit"]


def test_the_preview_shows_the_code_without_a_byte_order_mark(qt_app) -> None:
    dialog = ImportCodeDialog([ImportItem("\ufeff" + OBJECT, "w.py")])
    assert dialog.preview.text() == OBJECT and dialog.preview.isReadOnly()
    assert "size" in dialog.params_label.text()


def test_the_dialog_says_what_the_code_reaches(qt_app) -> None:
    from manim_studio.core.code_import import ImportItem
    from manim_studio.ui.import_code_dialog import ImportCodeDialog

    risky = ImportItem("import os\n\ndef build(p):\n    return Circle()\n", "risky.py")
    plain = ImportItem("def build(p):\n    return Circle()\n", "plain.py")
    dialog = ImportCodeDialog([risky, plain])
    dialog.list.setCurrentRow(0)
    assert "os" in dialog.uses_label.text() and "Read it first" in dialog.uses_label.text()
    dialog.list.setCurrentRow(1)
    assert "does not use files" in dialog.uses_label.text()
