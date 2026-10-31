"""Extract selection as code (ADR 0076): selected layers become one code layer that draws the same frames."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.core.code.code_cache import CodeCache
from manim_studio.core.editing import edits
from manim_studio.core.editing.edits import EditError
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.engine.extract_code import extract_as_code
from manim_studio.core.model.schema import (
    Camera,
    Canvas,
    Clip,
    Keyframe,
    Layer,
    Lifetime,
    Pin,
    Project,
    Spec,
    Transform2D,
)
from manim_studio.processes.code_runner import Job, render_code
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)


def scene() -> Project:
    """A backdrop left alone, then shapes, a text and clips (one keyed) to extract."""
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="back",
                spec=Spec(type="Rectangle", params={"width": 12.0, "height": 6.0}, style={"fill": "#1e293b"}),
            ),
            Layer(
                id="ring",
                name="Ring",
                spec=Spec(type="Circle", params={"radius": 1.5}, style={"stroke": "#38bdf8"}),
                clips=[Clip(id="c", kind="Create", start=0.5, duration=1.0)],
            ),
            Layer(
                id="box",
                name="Box",
                spec=Spec(
                    type="Square", params={"side_length": 1.0}, style={"fill": "#facc15", "fill_opacity": 1.0}
                ),
                base=Transform2D(position=(3.0, -1.0)),
                tracks={"rotation": [Keyframe(t=2.0, value=0.0), Keyframe(t=2.7, value=90.0)]},
                lifetime=Lifetime(in_=2.0, out=2.8),
            ),
            Layer(
                id="title",
                name="Title",
                spec=Spec(type="Text", params={"text": "Hello"}),
                base=Transform2D(position=(0.0, 2.4)),
                clips=[
                    Clip(id="f", kind="FadeIn", start=1.0, duration=1.0),
                    Clip(id="o", kind="FadeOut", start=3.0, duration=0.5),
                ],
            ),
        ],
    )


SELECTED = ["ring", "box", "title"]


def frames(project: Project, cache: CodeCache) -> list[np.ndarray]:
    evaluator, camera = Evaluator(project, cache), make_camera(project.canvas)
    return [
        render_frame(camera, evaluator.frame(t))[:, :, :3].astype(int) for t in frame_times(project.canvas)
    ]


def test_the_selection_becomes_one_code_layer_in_its_place_and_time() -> None:
    project = scene()
    result = extract_as_code(project, SELECTED)
    after = result.edit.project
    assert [x.id for x in after.layers] == ["back", result.layer_id]
    layer = after.layer(result.layer_id)
    assert layer.spec.type == "Code" and layer.spec.params["code"] == result.code
    assert layer.name == "Extracted code"
    assert layer.lifetime == Lifetime(in_=0.5, out=None)  # from the ring's Create; the ring stays to the end
    assert "manim_studio" not in result.code and "\nconfig." not in result.code
    assert "class ExtractedScene(Scene):" in result.code and "#   - Title" in result.code
    assert result.embedded == ()
    one = extract_as_code(project, ["box"])
    assert one.edit.project.layer(one.layer_id).lifetime == Lifetime(in_=2.0, out=2.8)
    assert one.edit.project.layer(one.layer_id).name == "Box (code)" and "class BoxScene(Scene)" in one.code


def test_the_start_is_put_on_the_frame_grid() -> None:
    project = scene()
    ring = project.layer("ring").model_copy(
        update={"clips": [Clip(id="c", kind="Create", start=0.55, duration=1)]}
    )
    project = edits.update_layer(project, "ring", clips=ring.clips).project
    result = extract_as_code(project, ["ring"])
    assert result.edit.project.layer(result.layer_id).lifetime.in_ == 0.5
    assert "self.wait(0.1)" in result.code  # the 0.05 s before the Create, as its whole frame


def test_the_code_layer_renders_the_frames_the_layers_did(tmp_path) -> None:
    project = scene()
    before = frames(project, CodeCache(tmp_path / "a"))
    result = extract_as_code(project, SELECTED)
    after_project = result.edit.project
    cache = CodeCache(tmp_path / "b")
    layer = after_project.layer(result.layer_id)
    key = Evaluator(after_project, cache).code_key(layer)
    canvas = after_project.canvas
    job = Job(
        key=key,
        code=result.code,
        width=canvas.width_px,
        height=canvas.height_px,
        fps=canvas.fps,
        frame_height=canvas.frame_height,
    )
    assert render_code(job, cache) == 35  # 3.5 s of the 4 s scene, from 0.5 s
    after = frames(after_project, cache)
    assert len(after) == len(before)
    for t, a, b in zip(frame_times(canvas), before, after, strict=True):
        diff = np.abs(a - b)
        assert diff.max() <= 3, t  # premultiplied rounding only


def test_what_readable_code_cannot_say_is_refused_with_the_reason() -> None:
    project = scene()
    pinned = project.model_copy(
        update={
            "layers": [
                *project.layers[:3],
                project.layer("title").model_copy(update={"pin": Pin(target="box")}),
            ]
        }
    )
    pinned = Project.model_validate(pinned.model_dump(by_alias=True))
    with pytest.raises(EditError, match="pinned to another layer"):
        extract_as_code(pinned, SELECTED)
    turned = Project.model_validate(
        {**project.model_dump(by_alias=True), "camera": Camera(phi=60.0).model_dump()}
    )
    with pytest.raises(EditError, match="camera is turned"):
        extract_as_code(turned, SELECTED)
    with pytest.raises(EditError, match="select the objects"):
        extract_as_code(project, [])


def test_a_layer_drawn_between_them_or_using_them_is_refused() -> None:
    project = scene()
    with pytest.raises(EditError, match="Box: it is drawn between the selected layers"):
        extract_as_code(project, ["ring", "title"])
    morph = Clip(id="m", kind="Transform", start=3.5, duration=0.4, to_layer="ring")
    back = project.layer("back").model_copy(update={"clips": [morph]})
    used = Project.model_validate(
        {
            **project.model_dump(by_alias=True),
            "layers": [back.model_dump(by_alias=True)]
            + [x.model_dump(by_alias=True) for x in project.layers[1:]],
        }
    )
    with pytest.raises(EditError, match="back: it uses a selected layer"):
        extract_as_code(used, SELECTED)
    with pytest.raises(EditError, match="uses a layer that is not selected"):
        extract_as_code(used, ["back"])  # it morphs into the ring, which stays
