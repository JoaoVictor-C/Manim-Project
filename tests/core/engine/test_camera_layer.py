"""The camera layer (ADR 0072): the view pans, zooms and rolls by one layer's keys; all else is as ever."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.core.editing import edits
from manim_studio.core.engine import frame_cache
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.engine.python_export import readable_problems, to_python
from manim_studio.core.model.schema import Canvas, Keyframe, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)


def square(**base) -> Layer:
    return Layer(
        id="sq",
        spec=Spec(type="Square", params={"side_length": 2}, style={"fill": "#3b82f6", "fill_opacity": 1}),
        base=Transform2D(**base),
    )


def camera(**base) -> Layer:
    return Layer(id="camera", name="Camera", spec=Spec(type="Camera"), base=Transform2D(**base))


def drawn(project: Project, t: float = 0.0) -> np.ndarray:
    return render_frame(make_camera(project.canvas), Evaluator(project).frame(t)).astype(int)


def project(*layers: Layer) -> Project:
    return Project(canvas=CANVAS, layers=list(layers))


def test_a_camera_at_rest_changes_nothing() -> None:
    assert np.array_equal(drawn(project(square(), camera())), drawn(project(square())))
    assert Evaluator(project(square(), camera())).camera_affine(0.0) is None


def test_the_camera_draws_nothing_and_is_not_in_the_frame() -> None:
    evaluator = Evaluator(project(square(), camera(position=(1.0, 0.0))))
    assert [layer_id for layer_id, _ in evaluator.frame_layers(0.0)] == ["sq"]


def test_panning_moves_the_scene_the_other_way() -> None:
    panned = drawn(project(square(), camera(position=(2.0, 0.0))))
    assert np.array_equal(panned, drawn(project(square(position=(-2.0, 0.0)))))


def test_zooming_scales_the_scene_about_the_point_the_camera_looks_at() -> None:
    zoomed = drawn(project(square(position=(1.0, 0.0)), camera(scale=2.0)))
    assert np.abs(zoomed - drawn(project(square(position=(2.0, 0.0), scale=2.0)))).max() <= 1
    looking = drawn(project(square(position=(1.0, 0.0)), camera(position=(1.0, 0.0), scale=2.0)))
    assert np.abs(looking - drawn(project(square(scale=2.0)))).max() <= 1  # the point it looks at stays put


def test_rolling_turns_the_scene_the_other_way() -> None:
    rolled = drawn(project(square(position=(2.0, 0.0)), camera(rotation=90.0)))
    assert np.abs(rolled - drawn(project(square(position=(0.0, -2.0), rotation=-90.0)))).max() <= 1


def test_keys_move_the_view_with_their_easing() -> None:
    moving = camera()
    moving = moving.model_copy(
        update={
            "tracks": {"position": [Keyframe(t=0.0, value=(0.0, 0.0)), Keyframe(t=2.0, value=(4.0, 0.0))]}
        }
    )
    scene = project(square(), moving)
    evaluator = Evaluator(scene)
    assert evaluator.camera_affine(0.0) is None  # it starts at rest
    a, b = evaluator.camera_affine(2.0)
    assert np.allclose(a, np.eye(2)) and np.allclose(b, (-4.0, 0.0))
    middle = evaluator.camera_affine(1.0)[1][0]
    assert -4.0 < middle < 0.0
    assert np.array_equal(drawn(scene, 2.0), drawn(project(square(position=(-4.0, 0.0)))))


def test_children_and_grouped_objects_follow_the_camera_too() -> None:
    axes = Layer(id="axes", spec=Spec(type="Axes"))
    graph = Layer(id="g", parent_id="axes", spec=Spec(type="Graph", params={"expression": "x"}))
    with_camera = drawn(project(axes, graph, camera(position=(1.0, 0.0))))
    without = drawn(project(axes.model_copy(update={"base": Transform2D(position=(-1.0, 0.0))}), graph))
    assert np.abs(with_camera - without).max() <= 2


def test_only_one_camera_and_it_is_a_plain_root_without_clips() -> None:
    with pytest.raises(ValueError, match="at most one camera"):
        project(camera(), camera().model_copy(update={"id": "camera-2"}))
    with pytest.raises(ValueError, match="no clips"):
        Layer.model_validate(
            {
                **camera().model_dump(by_alias=True),
                "clips": [{"id": "c", "kind": "FadeIn", "start": 0, "duration": 1}],
            }
        )
    with pytest.raises(ValueError, match="uniformly"):
        camera(scale_x=2.0)
    with pytest.raises(ValueError, match="cannot be a child"):
        project(square(), camera().model_copy(update={"parent_id": "sq"}))
    with pytest.raises(ValueError, match="cannot be a child"):
        project(camera(), square().model_copy(update={"id": "x", "parent_id": "camera"}))


def test_adding_a_camera_is_an_edit_and_a_second_is_refused() -> None:
    first = edits.add_camera(project(square()))
    assert [layer.name for layer in first.project.layers] == ["", "Camera"] and first.project.layers[
        1
    ].is_camera
    with pytest.raises(edits.EditError, match="already"):
        edits.add_camera(first.project)


def test_editing_the_camera_drops_every_cached_frame() -> None:
    old = project(square(), camera())
    keyed = camera().model_copy(
        update={"tracks": {"scale": [Keyframe(t=1.0, value=1.0), Keyframe(t=2.0, value=2.0)]}}
    )
    new = project(square(), keyed)
    spans = frame_cache.changed_spans(old, new)
    assert spans is None or frame_cache.span_indices(spans, 10, 40) == set(range(40))


def test_the_readable_python_export_says_it_cannot_and_the_exact_one_works() -> None:
    scene = project(square(), camera(position=(1.0, 0.0)))
    assert any("camera" in problem for problem in readable_problems(scene))
    assert not to_python(scene, "Moving", "code").readable


def test_a_camera_survives_saving_and_loading() -> None:
    scene = project(square(), camera(position=(1.0, 2.0), scale=1.5))
    again = Project.model_validate_json(scene.model_dump_json(by_alias=True))
    assert again == scene and again.layers[1].is_camera
