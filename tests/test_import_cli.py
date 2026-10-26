"""``manim-studio import scene.py -o project.json`` (P10.3, ADR 0053)."""

from __future__ import annotations

import json
import textwrap

import pytest

from manim_studio import cli
from manim_studio.core.editing.edits import insert_scene
from manim_studio.core.model.schema import Clip, Layer, Lifetime, Project, Spec
from manim_studio.processes import scene_recorder

SCENE = textwrap.dedent(
    """
    from manim import *

    class Intro(Scene):
        def construct(self):
            self.play(Create(Circle()))
            self.play(FadeIn(Square().shift(RIGHT * 2)))
    """
)


@pytest.fixture
def in_process(monkeypatch):
    """The recorder run in this process (the real command starts a new one: the slow test)."""

    def run(path, scene, cache_dir, timeout=60.0):
        return scene_recorder.record_file(path, scene)

    monkeypatch.setattr(scene_recorder, "run_recorder", run)


def test_import_writes_the_project_and_prints_the_report(tmp_path, capsys, in_process) -> None:
    path = tmp_path / "intro.py"
    path.write_text(SCENE, encoding="utf-8")
    out = tmp_path / "intro.json"
    assert cli.main(["import", str(path), "-o", str(out)]) == 0
    project = Project.model_validate_json(out.read_text(encoding="utf-8"))
    assert [x.spec.type for x in project.layers] == ["Circle", "Square"]
    printed = capsys.readouterr().out
    assert "Imported Intro (intro.py): 2 layers" in printed and "wrote" in printed


def test_import_of_a_scene_that_stays_code_still_succeeds(tmp_path, capsys, in_process) -> None:
    path = tmp_path / "orbit.py"
    path.write_text(
        "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n"
        "        d = Dot().add_updater(lambda m, dt: m.shift(RIGHT * dt))\n        self.add(d)\n"
        "        self.wait(1)\n",
        encoding="utf-8",
    )
    out = tmp_path / "orbit.json"
    assert cli.main(["import", str(path), "-o", str(out)]) == 0
    (layer,) = json.loads(out.read_text(encoding="utf-8"))["layers"]
    assert layer["spec"]["type"] == "Code"
    assert "kept as one code layer" in capsys.readouterr().out


def test_import_errors_exit_with_2(tmp_path, capsys, in_process) -> None:
    path = tmp_path / "two.py"
    path.write_text(
        SCENE + "\n\nclass Other(Scene):\n    def construct(self):\n        pass\n", encoding="utf-8"
    )
    assert cli.main(["import", str(path), "-o", str(tmp_path / "x.json")]) == 2
    assert "--scene" in capsys.readouterr().err
    broken = tmp_path / "broken.py"
    broken.write_text("from manim import *\nclass A(Scene):\n    def construct(self):\n        1 / 0\n")
    assert cli.main(["import", str(broken), "-o", str(tmp_path / "y.json")]) == 2
    assert "line 4" in capsys.readouterr().err
    assert cli.main(["import", str(tmp_path / "nope.py"), "-o", str(tmp_path / "z.json")]) == 2


@pytest.mark.slow
def test_the_import_command_records_in_another_process(tmp_path) -> None:
    path = tmp_path / "intro.py"
    path.write_text(SCENE, encoding="utf-8")
    recording = scene_recorder.run_recorder(path, None, tmp_path / "cache")
    assert recording["scene"] == "Intro" and recording["problems"] == []
    with pytest.raises(scene_recorder.RecordError, match="longer than"):
        slow = tmp_path / "slow.py"
        slow.write_text("import time\nfrom manim import *\nclass S(Scene):\n    def construct(self):\n"
                        "        time.sleep(30)\n", encoding="utf-8")  # fmt: skip
        scene_recorder.run_recorder(slow, None, tmp_path / "cache", timeout=8.0)


# -- into a project ---------------------------------------------------------------------------------------


def test_an_imported_scene_goes_on_top_with_free_ids_and_moved_times() -> None:
    project = Project(layers=[Layer(id="circle-1", spec=Spec(type="Circle"))])
    scene = Project(
        layers=[
            Layer(
                id="circle-1",
                spec=Spec(type="Circle"),
                clips=[Clip(id="t", kind="Transform", start=1.0, duration=1.0, to_layer="square-1")],
            ),
            Layer(id="square-1", spec=Spec(type="Square"), lifetime=Lifetime(out=4.0)),
        ]
    )
    scene = scene.model_copy(update={"canvas": scene.canvas.model_copy(update={"duration": 9.0})})
    edit, ids = insert_scene(project, scene, offset=2.0)
    assert ids == ["circle-2", "square-1"]
    new = edit.project
    assert [x.id for x in new.layers] == ["circle-1", "circle-2", "square-1"]
    moved = new.layer("circle-2").clips[0]
    assert (moved.start, moved.to_layer) == (3.0, "square-1")
    assert new.layer("square-1").lifetime.out == 6.0
    assert new.canvas.duration == 11.0


def test_converting_a_code_layer_replaces_it_where_it_was() -> None:
    project = Project(
        layers=[
            Layer(id="code-1", spec=Spec(type="Code", params={"code": "x"}), lifetime=Lifetime(in_=1.5)),
            Layer(id="dot-1", spec=Spec(type="Dot")),
        ]
    )
    scene = Project(layers=[Layer(id="code-1", spec=Spec(type="Square"), lifetime=Lifetime(in_=0.5))])
    edit, ids = insert_scene(project, scene, offset=1.5, replace="code-1")
    assert [x.id for x in edit.project.layers] == ["code-1", "dot-1"] and ids == ["code-1"]
    assert edit.project.layers[0].spec.type == "Square" and edit.project.layers[0].lifetime.in_ == 2.0
