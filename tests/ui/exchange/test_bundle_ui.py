"""File > Export Bundle... and File > Open Bundle... (ADR 0077); the test answers the file dialogs."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from acceptance.test_acceptance_v1 import menu_action
from manim_studio.core.exchange import bundle
from manim_studio.core.model import snapshots
from manim_studio.core.model.schema import AudioClip, Canvas, Layer, Project, Spec
from manim_studio.ui.exchange.bundle_dialog import ExportBundleDialog
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
CODE = "class Scene1(Scene):\n    def construct(self):\n        self.add(Circle())\n"


def scene(folder: Path, code: bool = False) -> Project:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "logo.svg").write_bytes(SVG)
    layers = [
        Layer(id="logo", name="Logo", spec=Spec(type="SVGMobject", params={"path": str(folder / "logo.svg")}))
    ]
    if code:
        layers.append(Layer(id="code", spec=Spec(type="Code", params={"code": CODE})))
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=layers,
        audio=[AudioClip(id="audio-1", name="voice", path=str(folder / "gone.wav"), duration=1.0)],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "made" / "intro.json"
    path.parent.mkdir()
    path.write_text(scene(tmp_path / "made").model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    yield win
    win.close()


def test_the_file_menu_has_both_actions(window) -> None:
    assert menu_action(window.menuBar(), "File", "Export Bundle...") is not None
    assert menu_action(window.menuBar(), "File", "Open Bundle...") is not None


def test_export_bundle_writes_it_and_warns_about_missing_files(window, tmp_path, monkeypatch) -> None:
    snapshots.save(window.path, window.document.project, "rough cut")
    asked = {}

    def options(references, missing, count):
        asked.update(files=[r.owner for r in references], missing=missing, count=count)
        return True

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))
    window.ask_bundle_options = options
    window.ask_bundle_save_path = lambda start: (
        str(tmp_path / "out" / "intro") if start.name == "intro.msbundle" else ""
    )
    menu_action(window.menuBar(), "File", "Export Bundle...").trigger()

    target = tmp_path / "out" / "intro.msbundle"
    assert target.is_file()
    assert asked == {
        "files": ["logo", "audio-1"],
        "missing": {str(tmp_path / "made" / "gone.wav")},
        "count": 1,
    }
    assert window.last_bundle.snapshots == 1 and [r.owner for r in window.last_bundle.missing] == ["audio-1"]
    assert "gone.wav" in warnings[0]
    assert window.statusBar().currentMessage() == "Wrote intro.msbundle: the project and 1 files"


def test_open_bundle_unpacks_beside_it_and_asks_about_its_code(window, tmp_path) -> None:
    target = tmp_path / "shared" / "talk.msbundle"
    bundle.build_bundle(scene(tmp_path / "theirs", code=True), target, name="talk")
    asked = []
    window.ask_trust = lambda names: asked.append(names) or "skip"
    window.ask_bundle_open_path = lambda start: str(target)
    menu_action(window.menuBar(), "File", "Open Bundle...").trigger()

    assert window.path == tmp_path / "shared" / "talk" / "talk.json"
    logo = window.document.project.layer("logo").spec.params["path"]
    assert Path(logo).read_bytes() == SVG and Path(logo).is_relative_to(tmp_path / "shared" / "talk")
    assert len(asked) == 1  # the code in a bundle is not trusted for being there


def test_a_bad_bundle_is_reported_and_the_project_stays(window, tmp_path, monkeypatch) -> None:
    bad = tmp_path / "bad.msbundle"
    bad.write_bytes(b"not a zip")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a[1])))
    before = window.path
    window.ask_bundle_open_path = lambda start: str(bad)
    window.open_bundle_dialog()
    assert errors == ["Could not open the bundle"] and window.path == before


def test_the_dialog_lists_the_files_and_offers_snapshots(qt_app, tmp_path) -> None:
    project = scene(tmp_path)
    refs = bundle.external_references(project)
    dialog = ExportBundleDialog(refs, bundle.missing_paths(refs), 0)
    assert dialog.list.count() == 2 and "missing" in dialog.list.item(1).text()
    assert not dialog.include_snapshots.isEnabled()
    assert "1 missing" in dialog.summary.text()
    dialog.close()
    with_snaps = ExportBundleDialog(refs, set(), 2)
    assert with_snaps.include_snapshots.isEnabled() and "2 snapshots" in with_snaps.include_snapshots.text()
    with_snaps.close()
