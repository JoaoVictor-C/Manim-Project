"""Readable Python export of keyframed layers (G3a, ADR 0046).

A keyframed layer is written as plain Manim code: its object, its clips as ``self.play`` calls, and
its keys as data tables drawn by a small ``Keyed`` helper - at every frame the scene shows the object
as its clips leave it, moved, scaled, turned and faded by the keys sampled at the frame's time, as
the editor applies a layer's transform after its clips. Rendered by ``manim render``, the file shows
what the editor's export shows.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import av
import numpy as np
import pytest

from manim_studio.core import adapter, library
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.python_export import readable_problems, to_python
from manim_studio.core.schema import (
    Canvas,
    Clip,
    Easing,
    Keyframe,
    Layer,
    Project,
    Spec,
    Transform2D,
)
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame

EULER = Path(__file__).with_name("euler_example.json")  # examples/euler.json as committed
SMALL = {"width_px": 256, "height_px": 144, "fps": 10}  # frame diffs on small, short videos
TOLERANCE = 1.5  # mean levels per frame: h264 noise only (B43)


def motions() -> Project:
    """Keys of every kind: each ease, a curved path overshooting its ends, an anchor with a turn
    past 180 degrees, opacity keys over an unkeyed base."""
    eases = [Easing(name=name) for name in adapter.EASE_NAMES] + [Easing(bezier=(0.34, 1.56, 0.64, 1.0))]
    scale = [Keyframe(t=round(0.3 * i, 9), value=(1.0, 1.6)[i % 2], ease=e) for i, e in enumerate(eases)]
    scale.append(Keyframe(t=round(0.3 * len(eases), 9), value=1.0))
    curve = [
        Keyframe(t=0.4, value=(-1.5, -0.5), ease=Easing(name="ease_in_out_back"), out_tangent=(0.5, 2.0)),
        Keyframe(t=2.4, value=(1.5, -0.5), in_tangent=(0.0, 1.5), ease=Easing(name="linear")),
        Keyframe(t=3.6, value=(1.0, -2.5), ease=Easing(name="smooth"), out_tangent=(1.0, 0.0)),
        Keyframe(t=4.6, value=(-1.0, -2.5), in_tangent=(0.5, 0.5)),
    ]
    return Project(
        canvas=Canvas(**SMALL, duration=6.0),
        layers=[
            Layer(
                id="eases",
                name="Eases",
                spec=Spec(
                    type="Square", params={"side_length": 1.2}, style={"fill": "#38bdf8", "fill_opacity": 0.6}
                ),
                base=Transform2D(position=(-4.5, 1.5)),
                tracks={"scale": scale},
            ),
            Layer(
                id="curve",
                name="Curve",
                spec=Spec(type="Dot", params={"radius": 0.3}),
                tracks={"position": curve},
            ),
            Layer(
                id="turn",
                name="Turn",
                spec=Spec(type="Rectangle", params={"width": 2.0, "height": 1.0}),
                base=Transform2D(position=(4.0, 1.5), anchor=(0.8, 0.3)),
                tracks={
                    "rotation": [
                        Keyframe(t=0.5, value=-30.0, ease=Easing(name="linear")),
                        Keyframe(t=3.5, value=250.0, ease=Easing(name="ease_out_cubic")),
                        Keyframe(t=5.0, value=400.0),
                    ],
                    "scale": [Keyframe(t=1.0, value=1.0), Keyframe(t=2.0, value=0.6)],
                },
            ),
            Layer(
                id="fade",
                name="Fade",
                spec=Spec(type="Triangle", style={"fill": "#facc15", "fill_opacity": 1.0}),
                base=Transform2D(position=(4.5, -2.0), rotation=20.0, scale=1.3, opacity=0.9),
                tracks={
                    "opacity": [
                        Keyframe(t=0.5, value=1.0, ease=Easing(name="rush_into")),
                        Keyframe(t=2.0, value=0.1, ease=Easing(name="there_and_back")),
                        Keyframe(t=3.0, value=0.6),
                    ]
                },
            ),
        ],
    )


def clips() -> Project:
    """Keyed layers whose clips play while their keys change: alone, in a group with another
    object's clips (after a wait), an overlay, a remover, a morph from a keyed layer, and a keyed
    layer as the path of a move."""
    return Project(
        canvas=Canvas(**SMALL, duration=5.0),
        layers=[
            Layer(
                id="pop",
                name="Pop",
                spec=Spec(type="Square", style={"fill": "#22c55e", "fill_opacity": 0.8}),
                base=Transform2D(position=(-4.5, 1.5)),
                clips=[
                    Clip(id="in", kind="FadeIn", start=0.5, duration=1.0, params={"shift": "UP"}),
                    Clip(id="ind", kind="Indicate", start=2.0, duration=0.6),
                    Clip(id="fl", kind="Flash", start=2.7, duration=0.5),
                    Clip(id="out", kind="FadeOut", start=4.3, duration=0.6),
                ],
                tracks={
                    "scale": [
                        Keyframe(t=0.5, value=0.4),
                        Keyframe(t=1.2, value=1.3, ease=Easing(name="ease_out_back")),
                        Keyframe(t=1.6, value=1.0),
                    ],
                    "rotation": [Keyframe(t=1.5, value=0.0), Keyframe(t=4.5, value=200.0)],
                },
            ),
            Layer(
                id="ring",
                name="Ring",
                spec=Spec(type="Circle", params={"radius": 0.8}),
                base=Transform2D(position=(0.0, 1.5)),
                clips=[Clip(id="cr", kind="Create", start=1.8, duration=1.2)],
            ),
            Layer(
                id="label",
                name="Label",
                spec=Spec(type="Text", params={"text": "Keys", "font_size": 36}),
                base=Transform2D(position=(4.0, 1.5)),
                clips=[
                    Clip(id="wr", kind="Write", start=0.0, duration=1.0),
                    Clip(id="wg", kind="Wiggle", start=2.2, duration=0.6),
                    Clip(id="mo", kind="Transform", start=3.4, duration=0.8, to_layer="star"),
                ],
                tracks={
                    "position": [Keyframe(t=1.0, value=(0.0, 0.0)), Keyframe(t=2.6, value=(0.0, -1.0))],
                    "opacity": [Keyframe(t=0.0, value=0.5), Keyframe(t=1.0, value=1.0)],
                },
            ),
            Layer(
                id="star",
                name="Star",
                spec=Spec(type="Star", style={"fill": "#facc15", "fill_opacity": 1.0}),
                base=Transform2D(position=(4.0, -2.0)),
            ),
            Layer(
                id="track",
                name="Track",
                spec=Spec(type="Circle", params={"radius": 1.0}),
                base=Transform2D(position=(-1.5, -2.0)),
                tracks={
                    "position": [Keyframe(t=0.0, value=(-1.5, -2.0)), Keyframe(t=2.0, value=(0.0, -2.0))]
                },
            ),
            Layer(
                id="runner",
                name="Runner",
                spec=Spec(type="Dot", params={"radius": 0.15}),
                clips=[
                    Clip(id="mv", kind="MoveAlongPath", start=3.4, duration=0.8, params={"path": "track"})
                ],
            ),
        ],
    )


def euler() -> Project:
    project = Project.model_validate_json(EULER.read_text(encoding="utf-8"))
    return project.model_copy(update={"canvas": project.canvas.model_copy(update=SMALL)})


def presets() -> list[library.Preset]:
    return [p for p in library.load_library([library.BUILTIN_FOLDER]).presets]


def preset_project(preset: library.Preset) -> Project:
    """``preset`` applied at 0.5 s to a square and to a text, side by side."""
    project = Project(
        canvas=Canvas(**SMALL, duration=3.0),
        layers=[
            Layer(id="sq", name="Square", spec=Spec(type="Square"), base=Transform2D(position=(-3.0, 0.0))),
            Layer(
                id="tx",
                name="Text",
                spec=Spec(type="Text", params={"text": "Hey"}),
                base=Transform2D(position=(3.0, 0.0)),
            ),
        ],
    )
    for layer_id in ("sq", "tx"):
        project = library.apply_preset(project, layer_id, preset, 0.5).project
    return project


# -- what is readable -------------------------------------------------------------------------------


def test_keyframed_layers_export_readable() -> None:
    for project in (motions(), clips(), euler()):
        assert readable_problems(project) == []
        export = to_python(project, "Keyed")
        assert export.readable and "manim_studio" not in export.code
        assert "class Keyed(Group):" in export.code  # the helper, written once
        assert export.code == to_python(project, "Keyed").code  # deterministic


def test_every_built_in_preset_exports_readable() -> None:
    keyed = []
    for preset in presets():
        project = preset_project(preset)
        assert readable_problems(project) == [], preset.name
        if any(layer.tracks for layer in project.layers):
            keyed.append(preset.name)
    assert keyed == ["Pop in", "Pulse", "Drift up", "Bounce", "Spin", "Grow", "Shrink"]


def test_the_keys_are_written_as_data() -> None:
    code = to_python(euler(), "Euler").code
    assert "eq1 = MathTex('e^{i\\\\pi} + 1 = 0', font_size=72)" in code
    table = re.search(r"eq1_keyed = Keyed\(self, eq1,(.*?)\n\s*\)\n", code, re.S).group(1)
    assert "position=[\n" in table and "(2.2, (0.0, 0.0), smooth)," in table
    assert "(2.2, 1.0, cubic_bezier(0.34, 1.56, 0.64, 1.0))," in table and "(3.2, 0.8, smooth)," in table
    assert "Succession(Wait(0.5), eq1_keyed.clip(Write(eq1, run_time=1.5)))" in code
    assert "self.play(eq1_keyed.clip(Indicate(eq1)), run_time=0.8)" in code
    assert "self.play(ReplacementTransform(eq1_keyed.still(4.4), eq2), run_time=1.2)" in code
    assert "config.disable_caching = True" in code  # Manim's cache does not see the scene clock
    plain = to_python(Project(canvas=euler().canvas, layers=[euler().layers[0]]), "Plain").code
    assert "Keyed" not in plain and "disable_caching" not in plain


def test_what_keyframed_layers_cannot_express() -> None:
    base = clips()
    key = {"opacity": [Keyframe(t=0.0, value=1.0), Keyframe(t=1.0, value=0.5)]}

    def problems(**changes) -> list[str]:
        layers = list(base.layers)
        for layer_id, update in changes.items():
            layers = [x.model_copy(update=update) if x.id == layer_id else x for x in layers]
        return readable_problems(base.model_copy(update={"layers": layers}))

    assert problems(star={"tracks": key}) == ["Star: a morph into a keyframed object"]
    assert problems(runner={"tracks": key}) == ["Runner: a keyframed object moving along a path"]
    write = base.layer("label").clips[0]
    late = [
        write,
        Clip(id="mo", kind="Transform", start=2.4, duration=0.5, to_layer="star"),
    ]  # in Ring's Create
    assert problems(label={"clips": late}) == ["Label: a keyframed object morphing during other animations"]
    dots = [
        Layer(id=f"dot{i}", spec=Spec(type="Dot"), base=Transform2D(position=(float(i), 1.0))) for i in (1, 2)
    ]

    def link(source: str, **update) -> list[str]:
        spec = Spec(type="Connector", params={"source": source, "target": "dot2", "ends": "centres"})
        line = Layer(id="link", name="Link", spec=spec).model_copy(update=update)
        return readable_problems(base.model_copy(update={"layers": [*base.layers, *dots, line]}))

    assert link("dot1") == []
    assert link("track") == ["Link: a connector to a keyframed object"]
    assert link("dot1", tracks=key) == ["Link: a keyframed connector"]


def test_a_turned_keyed_layer_may_have_clips() -> None:
    """Its clips act before the transform, as the drawing helper applies it after them."""
    layers = [
        x.model_copy(update={"base": x.base.model_copy(update={"rotation": 30.0, "scale": 0.7})})
        if x.id == "pop"
        else x
        for x in clips().layers
    ]
    assert readable_problems(clips().model_copy(update={"layers": layers})) == []
    unkeyed = [x.model_copy(update={"tracks": {}}) if x.id == "pop" else x for x in layers]
    assert readable_problems(clips().model_copy(update={"layers": unkeyed})) == [
        "Pop: clips on a turned or scaled object animate before its transform"
    ]


def test_waits_cover_whole_frames() -> None:
    """A 0.25 s clip at 10 fps draws 3 frames: the wait after it covers the rest of the 10 frames
    exactly, whether Manim draws the wait frame by frame or as one held frame."""
    project = Project(
        canvas=Canvas(**{**SMALL, "fps": 10}, duration=1.0),
        layers=[
            Layer(
                id="a", spec=Spec(type="Dot"), clips=[Clip(id="c", kind="FadeIn", start=0.0, duration=0.25)]
            )
        ],
    )
    code = to_python(project, "Short").code
    wait = float(re.search(r"self\.wait\(([^)]*)\)", code).group(1))
    dt = 1 / 10
    assert len(np.arange(0, wait, dt)) == 7 and int(wait / dt) == 7


# -- rendered by Manim --------------------------------------------------------------------------------


def render_scenes(codes: dict[str, str], tmp_path: Path) -> dict[str, list[np.ndarray]]:
    """Render the scenes of ``codes`` (name -> generated file): those with the same Manim config
    (set at import) in one file and one Manim process."""
    runs: dict[str, list[str]] = {}
    for code in codes.values():
        config = "\n".join(line for line in code.splitlines() if line.startswith("config."))
        runs.setdefault(config, []).append(code.replace("from __future__ import annotations\n", ""))
    for i, body in enumerate(runs.values()):
        path = tmp_path / f"scenes{i}.py"
        path.write_text("from __future__ import annotations\n" + "\n\n".join(body), encoding="utf-8")
        media = tmp_path / "media"
        done = subprocess.run(
            [sys.executable, "-m", "manim", "render", str(path), "-a", "--media_dir", str(media)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=tmp_path,
        )
        assert done.returncode == 0, done.stderr[-3000:]
    out = {}
    for name in codes:
        video = next((tmp_path / "media" / "videos").rglob(f"{name}.mp4"))
        with av.open(str(video)) as container:
            out[name] = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    return out


def frame_differences(project: Project, frames: list[np.ndarray]) -> list[float]:
    times = frame_times(project.canvas)
    assert len(frames) == len(times)
    evaluator, camera = Evaluator(project), make_camera(project.canvas)
    return [
        float(
            np.abs(
                frames[i].astype(int) - render_frame(camera, evaluator.frame(t))[:, :, :3].astype(int)
            ).mean()
        )
        for i, t in enumerate(times)
    ]


def assert_matches_editor(project: Project, frames: list[np.ndarray], label: str = "") -> None:
    diffs = frame_differences(project, frames)
    worst = int(np.argmax(diffs))
    assert diffs[worst] < TOLERANCE, (
        f"{label} frame {worst} ({worst / project.canvas.fps:.1f} s): {diffs[worst]:.2f}"
    )


@pytest.mark.slow
def test_keyed_layers_render_what_the_editor_shows(tmp_path) -> None:
    projects = {"Motions": motions(), "Clips": clips(), "Euler": euler()}
    codes = {name: to_python(project, name).code for name, project in projects.items()}
    videos = render_scenes(codes, tmp_path)
    for name, project in projects.items():
        assert_matches_editor(project, videos[name], name)


@pytest.mark.slow
def test_every_built_in_preset_renders_what_the_editor_shows(tmp_path) -> None:
    projects = {f"Preset{i:02d}": preset_project(p) for i, p in enumerate(presets())}
    names = {f"Preset{i:02d}": p.name for i, p in enumerate(presets())}
    codes = {name: to_python(project, name).code for name, project in projects.items()}
    videos = render_scenes(codes, tmp_path)
    for name, project in projects.items():
        assert_matches_editor(project, videos[name], names[name])


def test_the_euler_fixture_is_the_committed_example() -> None:
    """The fixture is examples/euler.json as committed (the example may carry local edits)."""
    data = json.loads(EULER.read_text(encoding="utf-8"))
    assert [layer["id"] for layer in data["layers"]] == ["title", "eq1", "eq2"]
