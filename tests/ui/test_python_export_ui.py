"""Python export from the editor and the command line (P4a.2, ADR 0031)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import menu_action
from manim_studio import cli
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


def simple() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(
                id="c",
                name="Ring",
                spec=Spec(type="Circle"),
                clips=[Clip(id="a", kind="Create", start=0, duration=1)],
            )
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "intro scene.json"
    path.write_text(simple().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    yield win
    win.close()


def test_file_export_python_writes_readable_code(window, tmp_path) -> None:
    target = tmp_path / "intro scene.py"
    window.ask_python_path = lambda start: str(target) if start == tmp_path / "intro scene.py" else ""
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    code = target.read_text(encoding="utf-8")
    assert "class IntroScene(Scene):" in code and "ring = Circle()" in code
    assert window.statusBar().currentMessage() == "Wrote intro scene.py: readable Manim code"


def test_a_turned_project_is_written_as_the_exact_scene(window, tmp_path) -> None:
    turned = simple().model_copy(
        update={"layers": [simple().layers[0].model_copy(update={"base": Transform2D(rotation=15.0)})]}
    )
    window.document.replace(turned)
    export = window.write_python(tmp_path / "turned.py")
    assert not export.readable
    assert "class Turned(StudioScene):" in (tmp_path / "turned.py").read_text(encoding="utf-8")
    message = window.statusBar().currentMessage()
    assert (
        message.startswith("Wrote turned.py: exact scene (needs Manim Studio)")
        and "Ring: clips on a turned or scaled object" in message
    )


def test_a_keyed_project_is_written_as_readable_code(window, tmp_path) -> None:
    keyed = simple().model_copy(
        update={
            "layers": [
                simple()
                .layers[0]
                .model_copy(
                    update={"tracks": {"opacity": [Keyframe(t=0, value=1.0), Keyframe(t=1, value=0.5)]}}
                )
            ]
        }
    )
    window.document.replace(keyed)
    export = window.write_python(tmp_path / "keyed.py")
    assert export.readable and "ring_keyed = Keyed(self, ring," in export.code
    assert window.statusBar().currentMessage() == "Wrote keyed.py: readable Manim code"


def test_the_command_line(tmp_path, capsys) -> None:
    project = tmp_path / "p.json"
    project.write_text(simple().model_dump_json(by_alias=True), encoding="utf-8")
    out = tmp_path / "my_scene.py"
    assert cli.main(["python", str(project), str(out)]) == 0
    assert "class MyScene(Scene):" in out.read_text(encoding="utf-8")
    assert "wrote" in capsys.readouterr().out
    assert cli.main(["python", str(project), str(out), "--scene", "Other"]) == 0
    assert "class Other(Scene):" in out.read_text(encoding="utf-8")
    assert cli.main(["python", str(tmp_path / "missing.json"), str(out)]) == 2
