"""Evaluating objects with part layers (P2c.2, ADR 0012).

The contract is the same as for whole layers: a frame equals what Manim renders
when the same animations play on the same glyphs (``eq[0][3:5]`` in a script),
built by hand here from the plain equation (B28: the marked build is identical).
"""

from __future__ import annotations

import random

import manim as m
import pytest
from tests.support import TOLERANCE, max_diff

from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, PartKey, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

pytestmark = pytest.mark.latex

CANVAS = Canvas(width_px=320, height_px=180, fps=15, duration=4.0)
TEXT = r"a^2 + b^2 = c^2"
PLAIN = Spec(type="MathTex", params={"text": TEXT})
A, B, C = (0, 1), (3, 4), (6, 7)  # glyphs of a^2, b^2, c^2 (B28)


def clip(clip_id: str, kind: str, start: float, duration: float = 1.0) -> Clip:
    return Clip(id=clip_id, kind=kind, start=start, duration=duration)


def part(layer_id: str, tex: str, **fields) -> Layer:
    return Layer(id=layer_id, parent_id="eq", part=PartKey(tex=tex), **fields)


def project(*part_layers: Layer, root_clips=(), **root_fields) -> Project:
    root = Layer(id="eq", spec=PLAIN, clips=list(root_clips), **root_fields)
    return Project(canvas=CANVAS, layers=[root, *part_layers])


def written() -> m.Mobject:
    eq = adapter.build_mobject(PLAIN)
    anim = adapter.make_animation("Write", eq, None, {})
    anim.begin()
    anim.finish()
    return eq


def glyphs(mob: m.Mobject, indices) -> m.VGroup:
    leaves = mob.family_members_with_points()
    return m.VGroup(*(leaves[i] for i in indices))


def play(mob: m.Mobject, kind: str, alpha: float) -> None:
    anim = adapter.make_animation(kind, mob, None, {})
    anim.begin()
    anim.interpolate(alpha)


def assert_renders(evaluator: Evaluator, t: float, expected: list[m.Mobject]) -> None:
    camera = make_camera(CANVAS)
    diff = max_diff(render_frame(camera, evaluator.frame(t)), render_frame(camera, expected))
    assert diff <= TOLERANCE, f"t={t}: differs by {diff}"


WRITE = clip("w", "Write", 0.0)


def test_a_clip_on_a_part_animates_only_its_glyphs_after_the_object_is_written() -> None:
    evaluator = Evaluator(project(part("b", "b^2", clips=[clip("i", "Indicate", 1.0)]), root_clips=[WRITE]))
    eq = written()
    play(glyphs(eq, B), "Indicate", 0.5)
    assert_renders(evaluator, 1.5, [eq])
    mid_write = adapter.build_mobject(PLAIN)
    play(mid_write, "Write", 0.5)  # an ancestor's clip animates the parts' glyphs too
    assert_renders(evaluator, 0.5, [mid_write])
    assert_renders(evaluator, 2.5, [written()])  # Indicate returns to rest


def test_siblings_animate_concurrently_and_a_removed_part_stays_gone() -> None:
    b = part("b", "b^2", clips=[clip("i", "Indicate", 1.0)])
    c = part("c", "c^2", clips=[clip("o", "FadeOut", 1.5)])
    evaluator = Evaluator(project(b, c, root_clips=[WRITE]))
    eq = written()
    play(glyphs(eq, B), "Indicate", 0.75)
    play(glyphs(eq, C), "FadeOut", 0.25)
    assert_renders(evaluator, 1.75, [eq])
    after = written()
    assert_renders(evaluator, 3.0, [glyphs(after, (0, 1, 2, 3, 4, 5))])


def test_a_part_with_a_later_introducer_is_hidden_until_it_appears() -> None:
    c = part("c", "c^2", clips=[clip("f", "FadeIn", 2.0)])
    evaluator = Evaluator(project(c, root_clips=[WRITE]))
    partial = adapter.build_mobject(PLAIN)
    play(partial, "Write", 0.5)
    assert_renders(evaluator, 0.5, [glyphs(partial, (0, 1, 2, 3, 4, 5))])
    assert_renders(evaluator, 1.5, [glyphs(written(), (0, 1, 2, 3, 4, 5))])
    fading = written()
    play(glyphs(fading, C), "FadeIn", 0.5)
    assert_renders(evaluator, 2.5, [fading])


def test_parts_move_with_their_own_keys_and_with_the_object() -> None:
    track = [Keyframe(t=1.0, value=(0.0, 0.0)), Keyframe(t=2.0, value=(1.0, 0.0))]
    b = part("b", "b^2", tracks={"position": track})
    c = part("c", "c^2", base=Transform2D(scale=2.0))  # scales about its own centre
    evaluator = Evaluator(project(b, c, base=Transform2D(position=(-1.0, 0.5))))
    eq = adapter.build_mobject(PLAIN)
    glyphs(eq, B).shift((0.5, 0, 0))  # smooth(0.5) = 0.5 of the way
    glyphs(eq, C).scale(2.0)
    eq.shift((-1.0, 0.5, 0))
    assert_renders(evaluator, 1.5, [eq])


def test_frame_layers_yields_the_object_then_its_parts_and_skips_orphans() -> None:
    p = project(part("b", "b^2"), part("gone", "z^2"), part("c", "c^2"))
    layers = Evaluator(p).frame_layers(1.0)
    assert [layer_id for layer_id, _ in layers] == ["eq", "b", "c"]
    counts = [len(mob.family_members_with_points()) for _, mob in layers]
    assert counts == [4, 2, 2]  # the object draws the glyphs no part owns: a^2, +, =


def test_nested_parts_own_their_glyphs() -> None:
    lhs = part("lhs", "a^2 + b^2")
    inner = Layer(id="b", parent_id="lhs", part=PartKey(tex="b^2"))
    layers = Evaluator(project(lhs, inner)).frame_layers(0.0)
    counts = {layer_id: len(mob.family_members_with_points()) for layer_id, mob in layers}
    assert counts == {"eq": 3, "lhs": 3, "b": 2}


def test_random_access_matches_sequential_playback() -> None:
    b = part("b", "b^2", clips=[clip("i", "Indicate", 1.0)])
    c = part("c", "c^2", clips=[clip("o", "FadeOut", 1.5)])
    p = project(b, c, root_clips=[WRITE])
    times = [i / CANVAS.fps for i in range(int(CANVAS.duration * CANVAS.fps))]
    camera = make_camera(CANVAS)
    sequential = Evaluator(p)
    expected = {t: render_frame(camera, sequential.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(7).shuffle(shuffled)
    scrubbing = Evaluator(p)
    for t in shuffled:
        assert max_diff(render_frame(camera, scrubbing.frame(t)), expected[t]) <= TOLERANCE, t


def test_edits_keep_or_drop_tree_caches_correctly() -> None:
    p = project(part("b", "b^2", clips=[clip("i", "Indicate", 1.0)]), root_clips=[WRITE])
    evaluator = Evaluator(p)
    evaluator.frame(1.5)
    moved = edits.move_clip(p, "b", "i", 2.0)  # timing: a new order of finished clips
    evaluator.apply(moved)
    eq = written()
    play(glyphs(eq, B), "Indicate", 0.5)
    assert_renders(evaluator, 2.5, [eq])
    with_c = edits.add_part(moved.project, "eq", "c^2")  # rebuilt with another marker
    evaluator.apply(with_c)
    assert [i for i, _ in evaluator.frame_layers(2.5)] == ["eq", "b", "part-1"]
    assert_renders(evaluator, 2.5, [eq])
    fresh = Evaluator(with_c.project)
    camera = make_camera(CANVAS)
    for t in (0.5, 1.5, 2.5, 3.5):
        assert (
            max_diff(render_frame(camera, evaluator.frame(t)), render_frame(camera, fresh.frame(t)))
            <= TOLERANCE
        )


def test_a_saved_project_with_parts_exports_what_the_editor_shows(tmp_path) -> None:
    import av
    import numpy as np

    from manim_studio import cli
    from manim_studio.render.cairo_export import frame_times

    small = Canvas(width_px=160, height_px=90, fps=4, duration=3.0)
    b = part("b", "b^2", clips=[clip("i", "Indicate", 1.0)])
    c = part("c", "c^2", clips=[clip("o", "FadeOut", 1.5)])
    p = project(b, c, root_clips=[WRITE]).model_copy(update={"canvas": small})
    project_file = tmp_path / "parts.json"
    project_file.write_text(p.model_dump_json(by_alias=True), encoding="utf-8")
    loaded = Project.model_validate_json(project_file.read_text(encoding="utf-8"))
    assert loaded == p
    out = tmp_path / "parts.mp4"
    assert cli.main(["render", str(project_file), str(out)]) == 0
    with av.open(str(out)) as container:
        frames = [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
    camera, evaluator = make_camera(small), Evaluator(p)
    for t, decoded in zip(frame_times(small), frames, strict=True):
        expected = render_frame(camera, evaluator.frame(t))[:, :, :3].astype(int)
        assert np.abs(decoded.astype(int) - expected).mean() < 4, f"t={t}"


def test_idle_checkpoints_cover_a_tree() -> None:
    b = part("b", "b^2", clips=[clip("i", "Indicate", 1.0)])
    evaluator = Evaluator(project(b, root_clips=[WRITE]))
    missing = evaluator.missing_checkpoints()
    assert [index for _, index in missing] == [(("eq", "w"),), (("eq", "w"), ("b", "i"))]
    while missing := evaluator.missing_checkpoints():
        evaluator.compute_checkpoint(*missing[0])
    assert evaluator.missing_checkpoints() == []
