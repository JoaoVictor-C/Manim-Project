"""The Code page's file buttons: Save code, Add code file, Import presets from folder and Export
all to folder - and the user templates they feed to the New Python object menu. Files made by
editors on Windows start with a byte-order mark; they must be read as the code they hold."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QFileDialog

from manim_studio.core import python_object, python_templates
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

BOM = "﻿"
SCENE = "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
TWO_SCENES = SCENE + "\nclass Spin(Scene):\n    def construct(self):\n        self.add(Square())\n"
OBJECT = "from manim import *\n\nPARAMS = {}\n\ndef build(p):\n    return Circle()\n"


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": SCENE})),
            Layer(id="dot", spec=Spec(type="Circle")),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    qt_app.processEvents()
    yield win
    win.close()


def page(window):
    return window.pages.pages["code"]


def answer(monkeypatch, **dialogs) -> None:
    for name, value in dialogs.items():
        monkeypatch.setattr(QFileDialog, name, staticmethod(lambda *a, v=value, **k: v))


def message(window) -> str:
    return window.statusBar().currentMessage()


def drain(window, qt_app) -> None:
    for _ in range(20):
        qt_app.processEvents()


# -- python_object.is_python_object_code ------------------------------------------------------


def test_detection_is_by_shape_and_ignores_a_byte_order_mark() -> None:
    assert python_object.is_python_object_code(OBJECT)
    assert python_object.is_python_object_code(BOM + OBJECT)
    assert not python_object.is_python_object_code(SCENE)
    assert not python_object.is_python_object_code(OBJECT + "\n" + SCENE)  # a scene wins
    assert not python_object.is_python_object_code("print(1)\n")
    assert not python_object.is_python_object_code("def build(:\n")  # not Python: never raises


# -- the user templates -------------------------------------------------------------------------


def test_user_templates_round_trip_through_the_settings(window) -> None:
    templates = {"Mine, with commas": OBJECT, "Línea\nbreak": OBJECT + "# ção\n"}
    window.prefs.set_python_code_templates(templates)
    assert window.prefs.python_code_templates() == templates


def test_bad_stored_templates_are_ignored(window) -> None:
    window.prefs._settings.setValue("python_code_templates", "not json")
    assert window.prefs.python_code_templates() == {}
    window.prefs._settings.setValue("python_code_templates", json.dumps(["a"]))
    assert window.prefs.python_code_templates() == {}
    window.prefs._settings.setValue("python_code_templates", json.dumps({"a": OBJECT, "b": 3, "c": None}))
    assert window.prefs.python_code_templates() == {"a": OBJECT}


def test_the_menu_lists_built_in_then_imported_templates(window, tmp_path, monkeypatch) -> None:
    folder = tmp_path / "presets"
    folder.mkdir()
    (folder / "Spiral.py").write_text(OBJECT, encoding="utf-8")
    (folder / "Scene.py").write_text(SCENE, encoding="utf-8")  # not an object: skipped
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    answer(monkeypatch, getExistingDirectory=str(folder))
    code = page(window)
    before = [a.text() for a in code.python_templates_menu.actions()]
    code.import_code_folder()
    names = [a.text() for a in code.python_templates_menu.actions()]
    assert names == [*before, "Spiral"] and set(before) == set(python_templates.TEMPLATES)
    assert "Added 1 Python object preset" in message(window) and "skipped 1" in message(window)
    code.import_code_folder()  # again: a name that is taken gets a number
    assert [a.text() for a in code.python_templates_menu.actions()][-1] == "Spiral (2)"


def test_a_preset_file_with_a_byte_order_mark_is_imported_whole(window, tmp_path, monkeypatch) -> None:
    folder = tmp_path / "presets"
    folder.mkdir()
    (folder / "Bom.py").write_bytes((BOM + OBJECT).encode("utf-8"))
    answer(monkeypatch, getExistingDirectory=str(folder))
    page(window).import_code_folder()
    assert window.prefs.python_code_templates() == {"Bom": OBJECT}  # no BOM in the stored code


def test_an_empty_or_cancelled_import_changes_nothing(window, tmp_path, monkeypatch) -> None:
    code = page(window)
    answer(monkeypatch, getExistingDirectory="")
    code.import_code_folder()
    empty = tmp_path / "empty"
    empty.mkdir()
    answer(monkeypatch, getExistingDirectory=str(empty))
    code.import_code_folder()
    assert "No .py files" in message(window) and window.prefs.python_code_templates() == {}


def test_choosing_an_imported_template_makes_a_python_object(window, qt_app) -> None:
    window.prefs.set_python_code_templates({"Mine": OBJECT})
    code = page(window)
    code._refresh_python_templates()
    action = next(a for a in code.python_templates_menu.actions() if a.text() == "Mine")
    action.trigger()
    drain(window, qt_app)
    layer = window.project.layers[-1]
    assert layer.spec.type == python_object.PYTHON_TYPE and layer.spec.params["code"] == OBJECT


# -- Add code file -----------------------------------------------------------------------------


def test_add_code_file_adds_a_python_object_and_selects_it(window, tmp_path, monkeypatch, qt_app) -> None:
    file = tmp_path / "Wheel.py"
    file.write_bytes((BOM + OBJECT).encode("utf-8"))
    answer(monkeypatch, getOpenFileName=(str(file), ""))
    page(window).add_code_file()
    drain(window, qt_app)
    layer = window.project.layers[-1]
    assert (layer.spec.type, layer.name) == (python_object.PYTHON_TYPE, "Wheel")
    assert layer.spec.params["code"] == OBJECT
    assert window.selection.layer_id == layer.id


def test_add_code_file_adds_a_scene_as_a_code_layer_and_says_what_it_left_out(
    window, tmp_path, monkeypatch, qt_app
) -> None:
    file = tmp_path / "Pair.py"
    file.write_bytes((BOM + TWO_SCENES).encode("utf-8"))
    answer(monkeypatch, getOpenFileName=(str(file), ""))
    page(window).add_code_file()
    drain(window, qt_app)
    layer = window.project.layers[-1]
    assert layer.spec.type == "Code" and "Spin" not in layer.spec.params["code"]
    assert "class Orbit" in layer.spec.params["code"] and not layer.spec.params["code"].startswith(BOM)
    assert "Spin" in message(window)  # the other scene was left out, and it is said


def test_add_code_file_refuses_a_file_that_is_neither(window, tmp_path, monkeypatch, qt_app) -> None:
    file = tmp_path / "plain.py"
    file.write_text("print(1)\n", encoding="utf-8")
    answer(monkeypatch, getOpenFileName=(str(file), ""))
    count = len(window.project.layers)
    page(window).add_code_file()
    drain(window, qt_app)
    assert len(window.project.layers) == count
    assert "Could not add plain.py" in message(window) and "neither" in message(window)


def test_a_new_code_file_does_not_cover_the_objects_already_there(
    window, tmp_path, monkeypatch, qt_app
) -> None:
    file = tmp_path / "Wheel.py"
    file.write_text(OBJECT, encoding="utf-8")
    answer(monkeypatch, getOpenFileName=(str(file), ""))
    page(window).add_code_file()
    drain(window, qt_app)
    assert window.project.layers[-1].spec.type == python_object.PYTHON_TYPE  # placed like any new object


# -- Save code and Export all ----------------------------------------------------------------


def test_save_code_writes_the_editor_text_including_unapplied_edits(window, tmp_path, monkeypatch) -> None:
    code = page(window)
    window.selection.select_layer("orbit")
    code.editor.setPlainText(SCENE + "# unapplied\n")
    target = tmp_path / "out" / "saved"
    target.parent.mkdir()
    answer(monkeypatch, getSaveFileName=(str(target), ""))
    code.save_code()
    saved = target.with_suffix(".py")
    assert saved.read_text(encoding="utf-8").endswith("# unapplied\n")
    assert "Saved code" in message(window)


def test_export_all_writes_one_file_per_code_layer_and_never_overwrites(
    window, tmp_path, monkeypatch
) -> None:
    out = tmp_path / "export"
    out.mkdir()
    answer(monkeypatch, getExistingDirectory=str(out))
    code = page(window)
    code.export_code_folder()
    assert sorted(p.name for p in out.iterdir()) == ["Orbit.py"]
    assert (out / "Orbit.py").read_text(encoding="utf-8") == SCENE
    code.export_code_folder()  # a second export keeps the first files
    assert sorted(p.name for p in out.iterdir()) == ["Orbit (2).py", "Orbit.py"]


def test_the_buttons_exist_and_fit_in_the_left_column(window) -> None:
    code = page(window)
    for button in (
        code.import_folder_button,
        code.add_code_file_button,
        code.export_folder_button,
        code.save_code_button,
    ):
        assert button.isVisibleTo(code.widget) and button.toolTip()
