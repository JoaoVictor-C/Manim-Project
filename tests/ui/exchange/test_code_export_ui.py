"""Exporting code (P12.4): the window, the question about files that exist, the index, the summary."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox

from manim_studio.core.exchange.code_export import ExportEntry, ExportOptions
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.exchange.export_code_dialog import ExportCodeDialog
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

SCENE = "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
OBJECT = "PARAMS = {}\n\ndef build(p):\n    return Circle()\n"


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=4.0),
        layers=[
            Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": SCENE})),
            Layer(id="wheel", name="Wheel", spec=Spec(type="Python", params={"code": OBJECT})),
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
    qt_app.processEvents()
    yield win
    win.close()


def project_only(window):
    return [e for e in window.importer.entries() if e.group == "project"]


def export_to(window, folder, options=None, chosen=None):
    window.importer.ask_export = lambda entries, checked, start, saved: (
        chosen if chosen is not None else project_only(window),
        str(folder),
        options or ExportOptions(),
    )


def answers(window, *given):
    """The questions about existing files are answered with ``given`` in order; the names asked are kept."""
    asked, it = [], iter(given)

    def decide(name):
        asked.append(name)
        return next(it)

    window.importer.conflicts = lambda folder="", what="file": decide
    return asked


def test_entries_are_the_code_layers_then_the_presets(window) -> None:
    entries = window.importer.entries()
    assert [(e.name, e.kind, e.group) for e in entries[:2]] == [
        ("Orbit", "scene", "project"),
        ("Wheel", "object", "project"),
    ]
    assert all(e.group == "preset" for e in entries[2:]) and len(entries) > 2  # the built-in presets


def test_exporting_to_a_new_folder_writes_the_files(window, tmp_path) -> None:
    out = tmp_path / "out"
    export_to(window, out)
    message = window.importer.export_code()
    assert sorted(p.name for p in out.iterdir()) == ["Orbit.py", "Wheel.py"]
    assert (out / "Orbit.py").read_text(encoding="utf-8") == SCENE
    assert message.startswith("Exported 2 files") and "replaced" not in message


@pytest.mark.parametrize(
    ("choice", "files", "word"),
    [
        ("replace", ["Orbit.py", "Wheel.py"], "replaced"),
        ("skip", ["Orbit.py", "Wheel.py"], "skipped"),
        ("copy", ["Orbit (2).py", "Orbit.py", "Wheel.py"], "copies"),
    ],
)
def test_a_file_that_exists_is_replaced_skipped_or_kept_both(window, tmp_path, choice, files, word) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "Orbit.py").write_text("# old\n", encoding="utf-8")
    export_to(window, out)
    asked = answers(window, choice)
    message = window.importer.export_code()
    assert asked == ["Orbit.py"] and word in message
    assert sorted(p.name for p in out.iterdir()) == files
    expected_old = choice in ("skip", "copy")
    assert ((out / "Orbit.py").read_text(encoding="utf-8") == "# old\n") is expected_old


def test_cancelling_the_question_stops_the_export(window, tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "Orbit.py").write_text("# old\n", encoding="utf-8")
    export_to(window, out)
    answers(window, None)
    message = window.importer.export_code()
    assert "cancelled" in message and not (out / "Wheel.py").exists()
    assert (out / "Orbit.py").read_text(encoding="utf-8") == "# old\n"


def test_the_index_is_written_and_lists_the_files(window, tmp_path) -> None:
    out = tmp_path / "pack"
    export_to(window, out, ExportOptions(manifest=True))
    message = window.importer.export_code()
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["name"] == "pack" and [p["file"] for p in index["presets"]] == ["Orbit.py", "Wheel.py"]
    assert "index.json written" in message


def test_line_endings_and_header_follow_the_options(window, tmp_path) -> None:
    out = tmp_path / "out"
    export_to(window, out, ExportOptions(newline="\r\n", header=True))
    window.importer.export_code()
    data = (out / "Wheel.py").read_bytes()
    assert data.startswith(b"# Wheel - exported from Manim Studio\r\n") and b"\r\n" in data


def test_the_choices_are_remembered_for_next_time(window, tmp_path) -> None:
    out = tmp_path / "out"
    export_to(window, out, ExportOptions(newline="\r\n", header=True, manifest=True))
    window.importer.export_code()
    seen = []
    window.importer.ask_export = lambda entries, checked, folder, options: (
        seen.append((folder, options)) or None
    )
    window.importer.export_code()
    assert seen == [(str(out), ExportOptions("\r\n", True, True))]


def test_nothing_to_export_says_so(window) -> None:
    assert "no code" in window.importer.export_code([]).lower()


# -- the window -------------------------------------------------------------------------------


def entries() -> list[ExportEntry]:
    return [
        ExportEntry("a", "Orbit", "scene", SCENE),
        ExportEntry("b", "Wheel", "object", OBJECT),
        ExportEntry("p", "Matrix", "object", OBJECT, group="preset"),
    ]


def ok(dialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_the_dialog_needs_a_folder_and_something_ticked(qt_app, tmp_path) -> None:
    dialog = ExportCodeDialog(entries(), folder="")
    assert not ok(dialog) and "folder" in dialog.message.text()
    dialog.folder_edit.setText(str(tmp_path))
    assert ok(dialog) and [e.key for e in dialog.chosen()] == ["a", "b", "p"]
    dialog._set_all(False)
    assert not ok(dialog) and "Tick" in dialog.message.text()


def test_the_dialog_ticks_only_what_it_was_given(qt_app, tmp_path) -> None:
    dialog = ExportCodeDialog(entries(), checked={"b"}, folder=str(tmp_path))
    assert [e.key for e in dialog.chosen()] == ["b"]
    dialog.list.item(1).setCheckState(Qt.CheckState.Checked)
    assert [e.key for e in dialog.chosen()] == ["a", "b"]


def test_the_dialog_reports_the_options(qt_app, tmp_path) -> None:
    dialog = ExportCodeDialog(entries(), folder=str(tmp_path), options=ExportOptions("\r\n", True, False))
    assert dialog.options() == ExportOptions("\r\n", True, False)
    dialog.manifest.setChecked(True)
    dialog.newline.setCurrentIndex(0)
    assert dialog.options() == ExportOptions("\n", True, True)


def test_a_file_as_the_folder_is_refused(qt_app, tmp_path) -> None:
    file = tmp_path / "x.txt"
    file.write_text("x", encoding="utf-8")
    dialog = ExportCodeDialog(entries(), folder=str(file))
    assert not ok(dialog) and "not a folder" in dialog.message.text()
