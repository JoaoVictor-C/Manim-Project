"""Plugins in the editor (P4b.2, ADR 0032): library entries, Help > Plugins, startup and load messages."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import manim as m
import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import menu_action
from manim_studio import plugins
from manim_studio.core.engine import adapter
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.plugins import ObjectType, Param
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.shell import plugins_dialog

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=2.0)


@pytest.fixture
def pendulum():
    """A plugin type, and a load report naming it and a failed plugin, for one test."""
    plugins.register(
        ObjectType(
            "Pendulum",
            lambda p: m.VGroup(m.Line(m.ORIGIN, m.DOWN * p["length"]), m.Dot(m.DOWN * p["length"])),
            params=(Param("length", "float", 2.0, minimum=0.1, maximum=20.0),),
            section="Physics",
            label="Simple pendulum",
        )
    )
    plugins.loaded["C:/plugins/pendulum.py"] = ["Pendulum"]
    plugins.problems["C:/plugins/broken.py"] = "ImportError: needs scipy"
    yield
    plugins.unregister("Pendulum")
    plugins.loaded.pop("C:/plugins/pendulum.py")
    plugins.problems.pop("C:/plugins/broken.py")


def open_window(tmp_path, project: Project) -> MainWindow:
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    return win


def test_a_plugin_object_is_added_from_the_library_and_edited(qt_app, tmp_path, pendulum) -> None:
    win = open_window(tmp_path, Project(canvas=CANVAS))
    try:
        menu_action(win.layers.library_menu, "Simple pendulum").trigger()
        (layer,) = win.document.project.layers
        assert layer.spec.type == "Pendulum" and win.evaluator.build_errors() == {}
        assert win.evaluator.frame(0.0)[0].height == pytest.approx(2.0, abs=0.2)
        win.properties.fields["params.length"].commit(4.0)  # its param, edited in Properties
        assert win.document.project.layers[0].spec.params["length"] == 4.0
        assert win.evaluator.frame(0.0)[0].height == pytest.approx(4.0, abs=0.2)
    finally:
        win.close()


def test_help_plugins_lists_types_and_failures(qt_app, tmp_path, pendulum) -> None:
    win = open_window(tmp_path, Project(canvas=CANVAS))
    try:
        menu_action(win.menuBar(), "Help", "Plugins...").trigger()
        dialog = win.findChild(plugins_dialog.PluginsDialog)
        text = dialog.text.toPlainText()
        assert "C:/plugins/pendulum.py\n    adds: Simple pendulum (Physics)" in text
        assert "C:/plugins/broken.py\n    NOT LOADED: ImportError: needs scipy" in text
        assert str(plugins.folders()[0]) in text
        dialog.close()
    finally:
        win.close()


def test_the_editor_says_at_startup_when_a_plugin_failed(qt_app, pendulum) -> None:
    win = MainWindow()
    try:
        assert win.statusBar().currentMessage() == "1 plugin could not load: see Help > Plugins"
    finally:
        win.close()


def test_without_plugins_the_dialog_says_so() -> None:
    assert plugins_dialog.startup_message() is None
    assert plugins_dialog.report().startswith("No plugins are installed.")


def test_a_project_using_a_missing_plugin_opens_and_says_so(qt_app, tmp_path) -> None:
    project = Project(canvas=CANVAS, layers=[Layer(id="t", name="Teapot 1", spec=Spec(type="Teapot"))])
    win = open_window(tmp_path, project)
    try:
        message = "Cannot draw: Teapot 1 (no installed plugin provides Teapot)"
        assert win.statusBar().currentMessage() == message
        assert isinstance(win.evaluator.frame(0.0)[0], m.DashedVMobject)
        assert adapter.allowed_clip_kinds("Teapot")  # its clips stay editable until the plugin is back
    finally:
        win.close()


@pytest.fixture
def manifested(monkeypatch, tmp_path):
    """A plugin waiting for approval (asking for more than approved before), a loaded one with a manifest and
    a legacy one without, for one test (ADR 0078)."""
    from manim_studio import plugin_manifest
    from manim_studio.plugin_manifest import Manifest

    monkeypatch.setenv("MANIM_STUDIO_PLUGIN_APPROVALS", str(tmp_path / "approvals.json"))
    waiting = Manifest("Weather", "2.0", "Ada", "Live weather maps.", permissions=("network", "ui"))
    before = plugin_manifest.approval_record(Manifest("Weather", "1.0", permissions=("ui",)))
    monkeypatch.setitem(plugins.pending, "C:/plugins/weather.py", waiting)
    monkeypatch.setitem(plugins.approvals, "C:/plugins/weather.py", before)
    monkeypatch.setitem(plugins.loaded, "C:/plugins/grid.py", [])
    monkeypatch.setitem(plugins.manifests, "C:/plugins/grid.py", Manifest("Grid", "1.0", permissions=("ui",)))
    monkeypatch.setitem(plugins.loaded, "C:/plugins/old.py", [])
    yield tmp_path / "approvals.json"
    plugins.approved.pop("C:/plugins/weather.py", None)


def test_the_dialog_shows_permissions_and_says_it_is_not_a_sandbox(qt_app, manifested) -> None:
    dialog = plugins_dialog.PluginsDialog()
    dialog.show()
    try:
        assert not dialog.grab().isNull()  # every icon it paints exists
        assert (
            "not enforced" in dialog.warning.text()
            and "all of your user account's rights" in dialog.warning.text()
        )
        row = dialog.rows["C:/plugins/weather.py"]
        assert [chip.text() for chip in row.chips] == ["network (new)", "ui"]
        assert row.chips[0].property("tone") == "warn"
        text = dialog.text.toPlainText()
        waits = "C:/plugins/weather.py\n    WAITS FOR APPROVAL: Weather 2.0 by Ada\n"
        assert waits + "    permissions: network, ui (new: network)" in text
        assert "C:/plugins/grid.py\n    adds: no object types\n    Grid 1.0\n    permissions: ui" in text
        assert "C:/plugins/old.py\n    adds: no object types\n    no manifest: unknown permissions" in text
        assert "1 waits for approval" in dialog.frame.description_label.text()
    finally:
        dialog.close()


def test_allowing_a_plugin_stores_the_approval_for_the_next_start(qt_app, manifested) -> None:
    import json

    dialog = plugins_dialog.PluginsDialog()
    dialog.show()
    try:
        dialog.rows["C:/plugins/weather.py"].allow.click()
        assert "C:/plugins/weather.py" not in dialog.rows and "C:/plugins/weather.py" not in plugins.pending
        stored = json.loads(manifested.read_text(encoding="utf-8"))["approved"]["C:/plugins/weather.py"]
        assert stored["version"] == "2.0" and stored["permissions"] == ["network", "ui"]
        assert "APPROVED: Weather 2.0 by Ada loads at the next start" in dialog.text.toPlainText()
        assert not dialog.grab().isNull()
    finally:
        dialog.close()


def test_the_editor_says_at_startup_when_a_plugin_waits(qt_app, manifested) -> None:
    assert plugins_dialog.startup_message() == "1 plugin waits for your approval: see Help > Plugins"
