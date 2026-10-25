"""The Code page's file buttons (P12): Add file, Import folder, Get online, Export, Save code - and the
presets they feed to the New Python object menu. The windows they open have their own tests
(test_import_code_dialog, test_code_export_ui, test_online_presets_dialog); here the buttons are
followed to the importer with the questions answered."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QFileDialog

from manim_studio.core import code_import as ci
from manim_studio.core import python_object, python_templates
from manim_studio.core.code_import import ImportChoice
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

BOM = "﻿"
SCENE = "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
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


def drain(qt_app) -> None:
    for _ in range(20):
        qt_app.processEvents()


# -- python_object.is_python_object_code (kept for the Python object detection) --------------


def test_detection_is_by_shape_and_ignores_a_byte_order_mark() -> None:
    assert python_object.is_python_object_code(OBJECT)
    assert python_object.is_python_object_code(BOM + OBJECT)
    assert not python_object.is_python_object_code(SCENE)
    assert not python_object.is_python_object_code(OBJECT + "\n" + SCENE)  # a scene wins
    assert not python_object.is_python_object_code("print(1)\n")
    assert not python_object.is_python_object_code("def build(:\n")  # not Python: never raises


# -- the buttons ----------------------------------------------------------------------------


def test_the_buttons_exist_and_have_tips(window) -> None:
    code = page(window)
    for button in (
        code.import_folder_button,
        code.online_button,
        code.export_folder_button,
        code.save_code_button,
        code.new_button,
    ):
        assert button.isVisibleTo(code.widget) and button.toolTip()
    assert set(code.new_actions) == {"layer", "object", "helper", "file"}
    assert all(action.toolTip() for action in code.new_actions.values())


def test_add_file_goes_through_the_import_window(window, tmp_path, monkeypatch, qt_app) -> None:
    file = tmp_path / "Wheel.py"
    file.write_bytes((BOM + OBJECT).encode("utf-8"))
    seen = {}

    def ask(items, at, position, **kw):
        seen["origin"] = [i.origin for i in items]
        return [ImportChoice(items[0], "Wheel", ci.OBJECT)]

    window.importer.ask = ask
    answer(monkeypatch, getOpenFileNames=([str(file)], ""))
    page(window).add_code_file()
    drain(qt_app)
    assert seen == {"origin": ["Wheel.py"]}
    layer = window.project.layers[-1]
    assert (layer.spec.type, layer.name) == ("Python", "Wheel") and layer.spec.params["code"] == OBJECT
    assert window.selection.layer_id == layer.id


def test_cancelling_the_file_dialog_does_nothing(window, monkeypatch, qt_app) -> None:
    answer(monkeypatch, getOpenFileNames=([], ""), getExistingDirectory="")
    page(window).add_code_file()
    page(window).import_code_folder()
    drain(qt_app)
    assert len(window.project.layers) == 2


def test_import_folder_adds_presets_to_the_new_python_object_menu(window, tmp_path, monkeypatch) -> None:
    folder = tmp_path / "presets"
    folder.mkdir()
    (folder / "Spiral.py").write_text(OBJECT, encoding="utf-8")
    window.importer.ask = lambda items, at, position, **kw: [ImportChoice(items[0], "Spiral", ci.PRESET)]
    answer(monkeypatch, getExistingDirectory=str(folder))
    code = page(window)
    before = [a.text() for a in code.python_templates_menu.actions()]
    assert set(before) == set(python_templates.TEMPLATES)
    code.import_code_folder()
    names = [a.text() for a in code.python_templates_menu.actions()]
    assert names == [*before, "Spiral"]
    assert "Spiral" in code.explorer.texts("user")  # the explorer lists it under your presets


def test_choosing_an_imported_preset_makes_an_untrusted_python_object(window, qt_app) -> None:
    code_text = OBJECT + "# imported preset\n"
    window.code_presets.add("Mine", "object", code_text)
    code = page(window)
    code._refresh_python_templates()
    next(a for a in code.python_templates_menu.actions() if a.text() == "Mine").trigger()
    drain(qt_app)
    layer = window.project.layers[-1]
    assert layer.spec.type == python_object.PYTHON_TYPE and layer.spec.params["code"] == code_text
    assert not window.trust.is_trusted(code_text)


def test_choosing_a_builtin_preset_is_trusted_like_the_starter(window, qt_app) -> None:
    code = page(window)
    name, text = next(iter(python_templates.TEMPLATES.items()))
    next(a for a in code.python_templates_menu.actions() if a.text() == name).trigger()
    drain(qt_app)
    assert window.project.layers[-1].spec.params["code"] == text and window.trust.is_trusted(text)


def test_get_online_hands_the_window_the_downloaded_items(window) -> None:
    from manim_studio.core.code_import import ImportItem

    window.importer.ask_online = lambda: [ImportItem(OBJECT, "https://example.com/Wheel.py", "Wheel.py")]
    window.importer.ask = lambda items, at, position, **kw: [ImportChoice(items[0], "Online", ci.PRESET)]
    page(window).get_online()
    assert "Online" in page(window).explorer.texts("online")


# -- save, export ---------------------------------------------------------------------------


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


def test_export_offers_the_editor_text_and_ticks_what_is_yours(window) -> None:
    code = page(window)
    window.selection.select_layer("orbit")
    code.editor.setPlainText(SCENE + "# unapplied\n")
    seen = {}

    def ask(entries, checked, folder, options):
        seen["entries"] = {e.key: e.source for e in entries}
        seen["checked"] = checked

    window.importer.ask_export = ask
    code.export_code_folder()
    assert seen["entries"]["orbit"].endswith("# unapplied\n")
    builtin = {p.id for p in window.code_presets.presets() if p.builtin}
    assert "orbit" in seen["checked"] and not seen["checked"] & builtin


def test_row_menu_export_ticks_just_that_row(window) -> None:
    code = page(window)
    seen = {}
    window.importer.ask_export = lambda entries, checked, folder, options: seen.update(checked=checked)
    window.selection.select_layer("orbit")
    menu = code.row_menu("layer", "orbit")
    next(a for a in menu.actions() if a.text() == "Export...").trigger()
    assert seen["checked"] == {"orbit"}


def test_the_new_menu_offers_each_kind_and_runs_it(window, monkeypatch) -> None:
    code = page(window)
    calls = []
    monkeypatch.setattr(code.helper_actions, "new_helper", lambda: calls.append("helper"))
    monkeypatch.setattr(code, "add_code_file", lambda: calls.append("file"))
    assert [a.text() for a in code.new_menu.actions() if a.text()] == [
        "Code layer (a Manim scene)",
        "Python object",
        "Python object from a preset",
        "Helper...",
        "From a file...",
    ]
    code.new_actions["helper"].trigger()
    assert calls == ["helper"]
    before = len(window.project.layers)
    code.new_actions["layer"].trigger()
    assert len(window.project.layers) == before + 1
