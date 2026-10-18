"""One-way Python export (P4a.1, ADR 0031).

Readable code for a project plain Manim can express, the exact scene (with its
reasons) for any other; both, rendered by ``manim render``, show what the
editor's export shows.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import av
import numpy as np
import pytest

from manim_studio.core import adapter
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.python_export import class_name, readable_problems, to_python
from manim_studio.core.schema import (
    Canvas,
    Clip,
    Easing,
    Keyframe,
    Layer,
    Lifetime,
    PartKey,
    Project,
    Spec,
    Transform2D,
)
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)
GOLDEN = Path(__file__).with_name("golden_readable_export.txt")


def rich() -> Project:
    """Every readable construct at once: a cluster, a gap, a morph, a path, helpers, style."""
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="back",
                name="Backdrop",
                spec=Spec(type="Square", params={"side_length": 1.0}),
                base=Transform2D(position=(-5.0, -2.5), rotation=30.0, scale=1.5, opacity=0.5),
            ),
            Layer(
                id="title",
                name="Title",
                spec=Spec(type="Text", params={"text": "Hello"}),
                base=Transform2D(position=(0.0, 2.6)),
                clips=[
                    Clip(
                        id="f",
                        kind="FadeIn",
                        start=0.5,
                        duration=1.0,
                        params={"shift": "UP"},
                        ease=Easing(name="ease_out_back"),
                    )
                ],
            ),
            Layer(
                id="ring",
                name="Ring",
                spec=Spec(type="Circle", params={"radius": 1.5}, style={"stroke": "#38bdf8"}),
                clips=[
                    Clip(
                        id="c",
                        kind="Create",
                        start=0.0,
                        duration=1.0,
                        ease=Easing(bezier=(0.3, 0.0, 0.2, 1.0)),
                    )
                ],
            ),
            Layer(
                id="sq",
                name="linear",
                spec=Spec(type="Square"),
                base=Transform2D(position=(3.0, -1.0)),
                clips=[
                    Clip(id="w", kind="Wiggle", start=2.0, duration=0.6),
                    Clip(id="t", kind="Transform", start=3.0, duration=0.6, to_layer="star"),
                ],
            ),
            Layer(
                id="star",
                name="Star",
                spec=Spec(type="Star", style={"fill": "#facc15", "fill_opacity": 1.0}),
                base=Transform2D(position=(3.0, 1.0)),
            ),
            Layer(
                id="dot",
                name="Runner",
                spec=Spec(type="Dot", params={"radius": 0.12}),
                clips=[Clip(id="r", kind="MoveAlongPath", start=2.0, duration=1.5, params={"path": "ring"})],
            ),
        ],
    )


def rendered(code: str, scene: str, tmp_path: Path) -> list[np.ndarray]:
    path = tmp_path / "export.py"
    path.write_text(code, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "manim", "render", str(path), scene, "--media_dir", str(tmp_path / "media")],
        check=True,
        capture_output=True,
        cwd=tmp_path,
    )
    video = next((tmp_path / "media" / "videos").rglob(f"{scene}.mp4"))
    with av.open(str(video)) as container:
        return [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]


def assert_matches_editor(project: Project, frames: list[np.ndarray]) -> None:
    times = frame_times(project.canvas)
    assert len(frames) == len(times)
    evaluator, camera = Evaluator(project), make_camera(project.canvas)
    for i, t in enumerate(times):
        ours = render_frame(camera, evaluator.frame(t))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - ours).mean() < 1.5, t  # h264 noise only (B43)


# -- readable or not -------------------------------------------------------------------------------------


def test_a_simple_project_is_readable() -> None:
    assert readable_problems(rich()) == []
    export = to_python(rich(), "Intro")
    assert export.readable and "from manim import *" in export.code and "manim_studio" not in export.code


def test_the_readable_text_is_stable() -> None:
    """A snapshot: generated code changes only on purpose (regenerate the golden file then)."""
    assert to_python(rich(), "Intro").code == GOLDEN.read_text(encoding="utf-8")


def test_what_plain_code_cannot_express(tmp_path) -> None:
    base = rich()

    def problems(**changes) -> list[str]:
        layers = [*base.layers, *changes.pop("extra", [])]
        for layer_id, update in changes.items():
            layers = [x.model_copy(update=update) if x.id == layer_id else x for x in layers]
        return readable_problems(base.model_copy(update={"layers": layers}))

    assert problems(ring={"tracks": {"opacity": [Keyframe(t=0, value=1.0)]}}) == []  # G3a: drawn by Keyed
    turned = problems(ring={"base": Transform2D(rotation=10.0)})
    assert turned == ["Ring: clips on a turned or scaled object animate before its transform"]
    run = Clip(
        id="r", kind="MoveAlongPath", start=2.0, duration=1.5, params={"path": "ring", "rotate": "along"}
    )
    assert problems(dot={"clips": [run]}) == ["Runner: turning along a path"]
    assert problems(star={"lifetime": Lifetime(in_=0.0)}) == ["Star: a morph target with its own lifetime"]
    late = Layer(id="late", spec=Spec(type="Dot"), lifetime=Lifetime(in_=0.7))  # inside the 0-1.5 group
    assert problems(extra=[late]) == ["late: appears or disappears during other animations"]
    gone = Layer(id="pic", spec=Spec(type="SVGMobject", params={"path": str(tmp_path / "gone.svg")}))
    assert problems(extra=[gone]) == ["pic: file not found"]
    code = Layer(id="code", spec=adapter.default_spec("Code"))
    assert problems(extra=[code]) == ["code: code layers are rendered by the editor"]
    eq = Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a+b"}))
    part = Layer(id="b", parent_id="eq", part=PartKey(tex="b"))
    assert problems(extra=[eq, part]) == ["b: parts and objects on axes are evaluated as one object"]


def test_an_exact_export_embeds_the_project_and_says_why() -> None:
    project = rich().model_copy(
        update={
            "layers": [
                *rich().layers,
                Layer(
                    id="k",
                    spec=Spec(type="Dot"),
                    base=Transform2D(rotation=10.0),
                    clips=[Clip(id="i", kind="Indicate", start=3.6, duration=0.3)],
                ),
            ]
        }
    )
    export = to_python(project, "Turned", code_cache_dir="C:/cache/code")
    why = "k: clips on a turned or scaled object animate before its transform"
    assert not export.readable and export.problems == [why]
    assert f"#   - {why}" in export.code and "code_cache_dir = 'C:/cache/code'" in export.code
    compile(export.code, "<exact>", "exec")
    embedded = export.code.split("PROJECT = r'''")[1].split("'''")[0]
    assert Project.model_validate_json(embedded) == project


def coloured_text() -> Project:
    """A Text with coloured pieces (U5, ADR 0049): Manim's own t2c, and a fill for the rest."""
    words = Spec(type="Text", params={"text": "Hi ok", "t2c": {"ok": "#ff0000"}}, style={"fill": "#00ff00"})
    write = Clip(id="w", kind="Write", start=0.0, duration=1.0)
    return Project(
        canvas=CANVAS.model_copy(update={"duration": 2.0}), layers=[Layer(id="t", spec=words, clips=[write])]
    )


def test_a_text_with_coloured_pieces_is_plain_t2c_code_that_builds_what_the_editor_builds() -> None:
    import manim

    export = to_python(coloured_text(), "Words")
    assert export.readable
    line = next(x.strip() for x in export.code.splitlines() if "= Text(" in x)
    assert line.endswith("Text('Hi ok', t2c={'ok': '#ff0000'}, color='#00ff00')")
    assert ".set_fill(" not in export.code  # it would paint over the pieces
    built = eval(line.split(" = ", 1)[1], vars(manim))  # what the exported file builds
    built.move_to(manim.ORIGIN)
    camera = make_camera(CANVAS)
    ours = adapter.build_mobject(coloured_text().layers[0].spec)
    assert np.array_equal(render_frame(camera, [built]), render_frame(camera, [ours]))


def test_a_project_with_a_coloured_part_exports_in_the_exact_form() -> None:
    eq = Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a+b"}))
    part = Layer(id="b", parent_id="eq", part=PartKey(tex="b"), style={"fill": "#ff0000"})
    project = Project(canvas=CANVAS, layers=[eq, part])
    export = to_python(project, "Parts")
    assert not export.readable
    assert export.problems == ["b: parts and objects on axes are evaluated as one object"]
    compile(export.code, "<exact>", "exec")
    embedded = export.code.split("PROJECT = r'''")[1].split("'''")[0]
    assert Project.model_validate_json(embedded).layer("b").style == {"fill": "#ff0000"}


def test_names() -> None:
    assert class_name("my intro") == "MyIntro" and class_name("2d plot") == "Scene2dPlot"
    code = to_python(rich(), "Intro").code
    assert "linear_2 = Square()" in code  # 'linear' would hide Manim's rate function


def test_code_layer_frames_paint_through_the_exported_scene_camera() -> None:
    """StudioScene teaches Manim's camera to paint CodeFrames; checked against render_frame."""
    from manim_studio.core.code_cache import Crop
    from manim_studio.core.code_frame import CodeFrame
    from manim_studio.manim_scene import StudioScene

    pixels = np.zeros((20, 30, 4), np.uint8)
    pixels[..., 1] = pixels[..., 3] = 200
    frame = CodeFrame(Crop(x=100, y=60, pixels=pixels), CANVAS, np.eye(2), np.zeros(2), 0.8)
    camera = make_camera(CANVAS)
    expected = render_frame(camera, [frame])

    class Probe(StudioScene):
        pass

    scene = Probe.__new__(Probe)
    scene.renderer = type("R", (), {"camera": make_camera(CANVAS)})()
    StudioScene.setup(scene)
    scene.renderer.camera.reset()
    scene.renderer.camera.capture_mobjects([frame])
    assert np.array_equal(scene.renderer.camera.pixel_array, expected)


# -- rendered by Manim -------------------------------------------------------------------------------------


@pytest.mark.slow
def test_readable_code_renders_what_the_editor_shows(tmp_path) -> None:
    export = to_python(rich(), "Intro")
    assert_matches_editor(rich(), rendered(export.code, "Intro", tmp_path))


@pytest.mark.slow
def test_readable_t2c_code_renders_what_the_editor_shows(tmp_path) -> None:
    export = to_python(coloured_text(), "Words")
    assert_matches_editor(coloured_text(), rendered(export.code, "Words", tmp_path))


@pytest.mark.slow
def test_the_exact_scene_renders_what_the_editor_shows(tmp_path) -> None:
    layers = [
        x.model_copy(update={"base": Transform2D(rotation=20.0, scale=0.8)}) if x.id == "ring" else x
        for x in rich().layers
    ]
    keyed = Layer(
        id="k",
        spec=Spec(type="Dot"),
        tracks={"position": [Keyframe(t=0, value=(-3.0, 0.0)), Keyframe(t=4, value=(3.0, 0.0))]},
    )
    project = rich().model_copy(update={"layers": [*layers, keyed]})
    export = to_python(project, "Keyed")
    assert not export.readable
    assert_matches_editor(project, rendered(export.code, "Keyed", tmp_path))
