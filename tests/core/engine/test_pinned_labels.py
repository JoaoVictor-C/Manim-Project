"""Pinned labels drawn (ADR 0075): a label sits by its target at every frame, upright and its own size unless
it follows the target, the same in the editor and the export, and its frames are drawn again when it moves."""

from __future__ import annotations

import random

import numpy as np
import pytest

from manim_studio.core.editing import edits
from manim_studio.core.engine import frame_cache
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.engine.python_export import readable_problems, to_python
from manim_studio.core.model.schema import (
    PIN_GAP,
    Canvas,
    Keyframe,
    Layer,
    Lifetime,
    Project,
    Spec,
    Transform2D,
)
from manim_studio.render.cairo_export import make_camera, render_frame, rendered_frames

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=3.0, background="#101010")


def moving_square(**tracks) -> Layer:
    keys = {
        "position": [Keyframe(t=0.0, value=(-3.0, -1.0)), Keyframe(t=2.0, value=(3.0, 1.0))],
        **tracks,
    }
    return Layer(
        id="sq",
        spec=Spec(type="Square", params={"side_length": 2}, style={"fill": "#3b82f6", "fill_opacity": 1}),
        tracks=keys,
    )


def label(**base) -> Layer:
    return Layer(id="lab", spec=Spec(type="Text", params={"text": "Ab"}), base=Transform2D(**base))


def pin(scene: Project, anchor: str = "top", offset=None, **follow) -> Project:
    return edits.pin_label(scene, "lab", "sq", anchor, offset, **follow).project


def project(*layers: Layer) -> Project:
    return Project(canvas=CANVAS, layers=list(layers))


def drawn(evaluator: Evaluator, t: float) -> dict:
    return dict(evaluator.frame_layers(t))


def box(mob) -> tuple[np.ndarray, np.ndarray]:
    every = np.vstack([sub.points[:, :2] for sub in mob.family_members_with_points()])
    return every.min(axis=0), every.max(axis=0)


@pytest.mark.parametrize("t", [0.0, 0.5, 1.0, 2.0, 2.5])
def test_a_label_sits_above_its_target_wherever_the_target_moves(t: float) -> None:
    evaluator = Evaluator(pin(project(moving_square(), label(position=(5.0, 5.0)))))
    frame = drawn(evaluator, t)
    (s_lo, s_hi), (l_lo, l_hi) = box(frame["sq"]), box(frame["lab"])
    assert l_lo[1] == pytest.approx(s_hi[1] + PIN_GAP, abs=1e-6)  # its bottom a gap above the target's top
    assert (l_lo[0] + l_hi[0]) / 2 == pytest.approx((s_lo[0] + s_hi[0]) / 2, abs=1e-6)  # centred over it


@pytest.mark.parametrize(
    ("anchor", "check"),
    [
        ("bottom", lambda s, lab: lab[1][1] == pytest.approx(s[0][1] - PIN_GAP, abs=1e-6)),
        ("left", lambda s, lab: lab[1][0] == pytest.approx(s[0][0] - PIN_GAP, abs=1e-6)),
        ("right", lambda s, lab: lab[0][0] == pytest.approx(s[1][0] + PIN_GAP, abs=1e-6)),
        ("centre", lambda s, lab: np.allclose((lab[0] + lab[1]) / 2, (s[0] + s[1]) / 2, atol=1e-6)),
    ],
)
def test_each_anchor_puts_the_label_on_its_side(anchor: str, check) -> None:
    frame = drawn(Evaluator(pin(project(moving_square(), label()), anchor)), 1.0)
    assert check(box(frame["sq"]), box(frame["lab"]))


def test_the_offset_is_the_labels_own_position() -> None:
    plain = drawn(Evaluator(pin(project(moving_square(), label()))), 1.0)["lab"]
    plain_box = box(plain)
    moved = drawn(Evaluator(pin(project(moving_square(), label()), offset=(0.5, 0.25))), 1.0)["lab"]
    assert np.allclose(box(moved)[0], plain_box[0] + (0.5, 0.25), atol=1e-6)


def test_the_label_stays_upright_and_its_size_while_the_target_turns_and_grows() -> None:
    target = moving_square(
        rotation=[Keyframe(t=0.0, value=0.0), Keyframe(t=2.0, value=90.0)],
        scale=[Keyframe(t=0.0, value=1.0), Keyframe(t=2.0, value=2.0)],
    )
    evaluator = Evaluator(pin(project(target, label())))
    sizes = [np.subtract(*reversed(box(drawn(evaluator, t)["lab"]))) for t in (0.0, 1.0, 2.0)]
    assert all(np.allclose(size, sizes[0], atol=1e-6) for size in sizes)


def test_a_label_can_follow_the_targets_rotation_and_scale() -> None:
    target = moving_square(
        rotation=[Keyframe(t=0.0, value=90.0)],
        scale=[Keyframe(t=0.0, value=2.0)],
    )
    scene = pin(project(target, label()), follow_rotation=True, follow_scale=True)
    evaluator = Evaluator(scene)
    a, _b = evaluator.world_affine(scene.layer("lab"), 1.0)
    assert np.allclose(a, [[0.0, -2.0], [2.0, 0.0]], atol=1e-9)  # turned a quarter and twice its size
    centre = np.mean(box(drawn(evaluator, 1.0)["sq"]), axis=0)
    label_centre = np.mean(box(drawn(evaluator, 1.0)["lab"]), axis=0)
    assert label_centre[0] < centre[0] - 2.0  # its "top" turned with the square: now on the left


def test_a_target_not_drawn_yet_holds_the_label_at_its_position() -> None:
    late = moving_square().model_copy(update={"lifetime": Lifetime(in_=2.0)})
    evaluator = Evaluator(pin(project(late, label())))
    frame = drawn(evaluator, 1.0)
    assert "sq" not in frame
    lo, hi = box(frame["lab"])
    assert (lo[0] + hi[0]) / 2 == pytest.approx(0.0, abs=1e-6) and lo[1] == pytest.approx(PIN_GAP, abs=1e-6)


def test_unpinned_position_keeps_the_label_where_it_was_drawn() -> None:
    scene = pin(project(moving_square(), label()), offset=(0.3, 0.1))
    evaluator = Evaluator(scene)
    before = box(drawn(evaluator, 1.0)["lab"])
    position = evaluator.unpinned_position(scene.layer("lab"), 1.0)
    after = box(drawn(Evaluator(edits.unpin_label(scene, "lab", position).project), 1.0)["lab"])
    assert np.allclose(before, after, atol=1e-3)


def test_a_canvas_move_of_a_pinned_label_changes_its_offset() -> None:
    scene = pin(project(moving_square(), label()), follow_rotation=True)
    evaluator = Evaluator(scene)
    pivot, _rotation, to_local = evaluator.layer_frame(scene.layer("lab"), 1.0)
    assert np.allclose(to_local, np.eye(2))  # the target is not turned: a move is the offset
    assert np.allclose(pivot, np.mean(box(drawn(evaluator, 1.0)["lab"]), axis=0), atol=0.2)


def test_the_label_follows_through_the_camera() -> None:
    camera = Layer(id="camera", spec=Spec(type="Camera"), base=Transform2D(position=(1.0, 0.5), scale=1.5))
    scene = pin(project(moving_square(), label(), camera))
    evaluator = Evaluator(scene)
    position = evaluator.unpinned_position(scene.layer("lab"), 1.0)
    unpinned = edits.unpin_label(scene, "lab", position).project
    camera_view = make_camera(CANVAS)
    pinned_frame = render_frame(camera_view, Evaluator(scene).frame(1.0)).astype(int)
    plain_frame = render_frame(camera_view, Evaluator(unpinned).frame(1.0)).astype(int)
    assert np.abs(pinned_frame - plain_frame).max() <= 8  # edges drawn from other floats


def test_the_editor_and_the_export_draw_the_same_frames_in_any_order() -> None:
    scene = pin(project(moving_square(), label()))
    last = round(CANVAS.duration * CANVAS.fps)
    exported = [rgba.copy() for _, rgba in rendered_frames(scene, 0, last, 1)]
    camera = make_camera(CANVAS)
    editor = Evaluator(scene)
    order = list(range(last))
    random.Random(7).shuffle(order)
    for index in order:  # scrubbing: one evaluator, frames asked out of order
        frame = render_frame(camera, editor.frame(index / CANVAS.fps))
        assert np.array_equal(frame, exported[index]), index
    assert not np.array_equal(exported[0], exported[20])  # the label moved with its target


def test_editing_the_pin_or_its_target_draws_the_labels_frames_again() -> None:
    scene = pin(project(moving_square(), label().model_copy(update={"lifetime": Lifetime(in_=2.5)})))
    span = [(2.5, float("inf"))]
    repinned = edits.pin_label(scene, "lab", "sq", "bottom").project
    assert frame_cache.changed_layers(scene, repinned) == {"lab"}
    assert frame_cache.changed_spans(scene, repinned) == span
    moved = edits.set_property(scene, "sq", "scale", 2.0, 0.0).project
    assert frame_cache.changed_layers(scene, moved) == {"sq", "lab"}


def test_the_readable_python_export_says_it_cannot_and_the_exact_one_works() -> None:
    scene = pin(project(moving_square(), label()))
    assert any("pinned" in problem for problem in readable_problems(scene))
    assert not to_python(scene, "Pinned", "code").readable
