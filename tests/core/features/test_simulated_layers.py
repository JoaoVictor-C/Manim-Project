"""Simulated layers (P4c.1, ADR 0033): plugin simulations and traced paths.

Both advance once per canvas frame. A frame must be the same whatever order
frames are asked for in (replayed from kept states), a trace must be the
polyline through its target's point on every frame so far - which is Manim's
own TracedPath within one play - and sampling a trace must not disturb the
frame being drawn.
"""

from __future__ import annotations

import math
import random

import manim as m
import numpy as np
import pytest
from tests.support import max_diff

from manim_studio import plugins
from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.engine.frame_cache import changed_layers
from manim_studio.core.engine.python_export import readable_problems
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Lifetime, Project, Spec, Transform2D
from manim_studio.plugins import Param, Simulation
from manim_studio.render.cairo_export import make_camera, render_frame

FPS = 15
CANVAS = Canvas(width_px=320, height_px=180, fps=FPS, duration=3.0)
TIMES = [i / FPS for i in range(45)]


def swing_step(state, dt, params):
    """A damped pendulum, RK4; mutates its input like much numpy code does."""

    def f(theta, omega):
        return omega, -9.81 / params["length"] * math.sin(theta) - 0.2 * omega

    theta, omega = state
    k1 = f(theta, omega)
    k2 = f(theta + dt / 2 * k1[0], omega + dt / 2 * k1[1])
    k3 = f(theta + dt / 2 * k2[0], omega + dt / 2 * k2[1])
    k4 = f(theta + dt * k3[0], omega + dt * k3[1])
    state[0] = theta + dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
    state[1] = omega + dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
    return state


def bob(state, params):
    return params["length"] * math.sin(state[0]), -params["length"] * math.cos(state[0])


def swing_draw(state, params):
    x, y = bob(state, params)
    return m.VGroup(m.Line(m.ORIGIN, [x, y, 0]), m.Dot([x, y, 0], radius=0.15))


SWING = Simulation(
    "Swing",
    start=lambda params: np.array([math.radians(params["angle"]), 0.0]),
    step=swing_step,
    draw=swing_draw,
    point=bob,
    params=(Param("length", "float", 1.5), Param("angle", "float", 60.0)),
    section="Physics",
)


@pytest.fixture(autouse=True)
def _swing():
    plugins.register(SWING)
    yield
    plugins.unregister("Swing")


def frames(project: Project, times: list[float], order: list[int] | None = None, fresh: bool = False) -> dict:
    camera = make_camera(project.canvas)
    evaluator = Evaluator(project)
    out = {}
    for i in order if order is not None else range(len(times)):
        if fresh:
            evaluator = Evaluator(project)
        out[i] = render_frame(camera, evaluator.frame(times[i]))
    return out


def assert_same(a: dict, b: dict) -> None:
    for i in a:
        assert max_diff(a[i], b[i]) <= 1, f"frame {i}"


def anchors(mob: m.VMobject) -> np.ndarray:
    """A polyline's corners, consecutive duplicates dropped."""
    points = [p for path in mob.get_subpaths() for p in (*path[0::4], path[-1])]
    keep = [p for i, p in enumerate(points) if i == 0 or not np.allclose(p, points[i - 1])]
    return np.array(keep)[:, :2] if keep else np.zeros((0, 2))


def dedup(points: list[np.ndarray]) -> np.ndarray:
    keep = [p for i, p in enumerate(points) if i == 0 or not np.allclose(p, points[i - 1])]
    return np.array(keep) if keep else np.zeros((0, 2))


# -- simulations ---------------------------------------------------------------------


def swing_project(**layer) -> Project:
    swing = Layer(id="swing", spec=Spec(type="Swing", style={"stroke": "#22d3ee"}), **layer)
    return Project(canvas=CANVAS, layers=[swing])


def test_a_simulation_steps_once_per_frame_from_its_first_frame() -> None:
    project = swing_project(lifetime=Lifetime(in_=0.25))  # off the grid: starts on frame 4
    camera = make_camera(CANVAS)
    params = {"length": 1.5, "angle": 60.0}
    state = SWING.start(params)
    expected = {}
    for i, t in enumerate(TIMES):
        if t < 0.25:
            expected[i] = render_frame(camera, [])
            continue
        if i > 4:
            state = swing_step(state.copy(), 1 / FPS, params)
        expected[i] = render_frame(
            camera, [adapter.simulation_drawing(project.layers[0].spec, swing_draw(state, params))]
        )
    n = len(TIMES)
    assert_same(expected, frames(project, TIMES))
    assert_same(expected, frames(project, TIMES, random.Random(4).sample(range(n), n), fresh=True))
    assert_same(
        expected, frames(project, TIMES, list(reversed(range(n))) + random.Random(5).sample(range(n), n))
    )


def test_states_are_kept_every_30_steps_and_replayed_from_the_nearest() -> None:
    evaluator = Evaluator(swing_project())
    evaluator.frame(TIMES[44])
    run = evaluator._runs["swing"]
    assert sorted(run.kept) == [0, 30] and run.latest[0] == 44
    calls = []
    original = SWING.step

    def counted(state, dt, params):
        calls.append(1)
        return original(state, dt, params)

    plugins.SIMULATIONS["Swing"] = Simulation("Swing", SWING.start, counted, swing_draw, bob, SWING.params)
    try:
        evaluator.frame(TIMES[40])
        assert len(calls) == 10  # from the state kept at 30
        evaluator.frame(TIMES[41])
        assert len(calls) == 11  # playing on: one step per frame
    finally:
        plugins.SIMULATIONS["Swing"] = SWING


def test_a_simulation_is_drawn_in_its_own_units_and_moved_by_its_layer() -> None:
    project = swing_project(base=Transform2D(position=(1.0, 1.0)))
    drawn = Evaluator(project).frame(0.0)[0]
    x, y = bob(SWING.start({"length": 1.5, "angle": 60.0}), {"length": 1.5})
    assert drawn[0].get_start()[:2] == pytest.approx([1.0, 1.0])  # the pivot, not re-centred
    assert drawn[1].get_center()[:2] == pytest.approx([1.0 + x, 1.0 + y])


def test_editing_a_simulation_replays_it() -> None:
    project = swing_project()
    evaluator = Evaluator(project)
    before = evaluator.frame(1.0)[0][1].get_center().copy()
    longer = project.model_copy(
        update={
            "layers": [
                project.layers[0].model_copy(update={"spec": Spec(type="Swing", params={"length": 3.0})})
            ]
        }
    )
    evaluator.invalidate(longer, {"swing"}, "spec")
    after = evaluator.frame(1.0)[0][1].get_center()
    fresh = Evaluator(longer).frame(1.0)[0][1].get_center()
    assert not np.allclose(before, after) and np.allclose(after, fresh)


@pytest.mark.parametrize(
    ("step", "draw", "message"),
    [
        (lambda s, dt, p: 1 / 0, swing_draw, "the Swing simulation failed: ZeroDivisionError"),
        (lambda s, dt, p: s + np.random.default_rng().random(2), swing_draw, "runs differently each time"),
        (swing_step, lambda s, p: m.ImageMobject(np.zeros((2, 2, 3), np.uint8)), "must draw a VMobject"),
    ],
)
def test_a_broken_simulation_draws_the_placeholder_and_says_why(step, draw, message) -> None:
    plugins.unregister("Swing")
    plugins.register(Simulation("Swing", SWING.start, step, draw, params=SWING.params))
    evaluator = Evaluator(swing_project())
    assert isinstance(evaluator.frame(1.0)[0], m.DashedVMobject)
    assert message in evaluator.build_errors()["swing"]


def test_a_simulation_failing_late_draws_the_placeholder_from_then_on() -> None:
    def late(state, dt, params):
        if state[1] < -2.0:  # fast, after a few frames of swinging
            raise RuntimeError("blew up")
        return swing_step(state, dt, params)

    plugins.unregister("Swing")
    plugins.register(Simulation("Swing", SWING.start, late, swing_draw, params=SWING.params))
    evaluator = Evaluator(swing_project())
    assert not isinstance(evaluator.frame(0.0)[0], m.DashedVMobject)
    assert isinstance(evaluator.frame(2.0)[0], m.DashedVMobject)
    assert "blew up" in evaluator.build_errors()["swing"]


# -- traced paths --------------------------------------------------------------------


def dot_layer(**kwargs) -> Layer:
    tracks = {"position": [Keyframe(t=0.0, value=(-3.0, -1.0)), Keyframe(t=2.0, value=(3.0, 1.5))]}
    return Layer(id="dot", spec=Spec(type="Dot"), tracks=tracks, **kwargs)


def trace_layer(target: str = "dot", **params) -> Layer:
    return Layer(id="trace", spec=Spec(type="TracedPath", params={"target": target, **params}))


def centres(project: Project, layer_id: str, times: list[float], offset=None) -> list[np.ndarray | None]:
    evaluator = Evaluator(
        project.model_copy(update={"layers": [x for x in project.layers if x.id != "trace"]})
    )
    out = []
    for t in times:
        drawn = dict(evaluator.frame_layers(t)).get(layer_id)
        out.append(None if drawn is None else drawn.get_center()[:2])
    return out


def test_a_trace_is_the_polyline_through_its_target_on_every_frame_so_far() -> None:
    clip = Clip(id="w", kind="Wiggle", start=0.5, duration=1.0)
    project = Project(canvas=CANVAS, layers=[dot_layer(clips=[clip]), trace_layer()])
    expected = centres(project, "dot", TIMES)
    for order in (range(len(TIMES)), random.Random(7).sample(range(len(TIMES)), len(TIMES))):
        evaluator = Evaluator(project)
        for k in order:
            trace = dict(evaluator.frame_layers(TIMES[k]))["trace"]
            assert np.allclose(anchors(trace), dedup(expected[: k + 1])), k


def test_a_trace_starts_on_its_own_first_frame_and_keeps_its_last_seconds() -> None:
    project = Project(
        canvas=CANVAS,
        layers=[dot_layer(), trace_layer(dissipate=0.4).model_copy(update={"lifetime": Lifetime(in_=0.3)})],
    )
    expected = centres(project, "dot", TIMES)
    trace = dict(Evaluator(project).frame_layers(TIMES[30]))["trace"]
    assert np.allclose(anchors(trace), dedup(expected[30 - 6 : 31]))  # round(0.4 * 15) = 6 frames back
    early = dict(Evaluator(project).frame_layers(TIMES[6]))["trace"]
    assert np.allclose(anchors(early), dedup(expected[5:7]))  # from frame ceil(0.3 * 15) = 5


def test_between_frames_the_trace_reaches_the_object() -> None:
    project = Project(canvas=CANVAS, layers=[dot_layer(), trace_layer()])
    t = 0.5 + 0.03
    layers = dict(Evaluator(project).frame_layers(t))
    assert np.allclose(anchors(layers["trace"])[-1], layers["dot"].get_center()[:2])


def test_a_trace_follows_a_point_through_its_offset_as_the_object_turns() -> None:
    turning = dot_layer().model_copy(
        update={"tracks": {"rotation": [Keyframe(t=0, value=0.0), Keyframe(t=2, value=180.0)]}}
    )
    project = Project(canvas=CANVAS, layers=[turning, trace_layer(offset=(1.0, 0.0))])
    trace = dict(Evaluator(project).frame_layers(TIMES[30]))["trace"]
    angle = math.radians(180.0 * min(TIMES[30], 2.0) / 2.0)
    assert anchors(trace)[-1] == pytest.approx([math.cos(angle), math.sin(angle)], abs=1e-6)


def test_a_trace_follows_a_point_on_axes_and_the_bob_of_a_simulation() -> None:
    axes = Layer(
        id="axes",
        spec=Spec(type="Axes"),
        tracks={"position": [Keyframe(t=0, value=(0.0, 0.0)), Keyframe(t=3, value=(1.0, 0.5))]},
    )
    point = Layer(
        id="p",
        parent_id="axes",
        spec=Spec(type="Point", params={"x": 2.0, "y": 1.0}),
        lifetime=Lifetime(in_=0.5),
    )
    swing = Layer(id="swing", spec=Spec(type="Swing"), base=Transform2D(position=(1.0, 2.0), scale=0.5))
    project = Project(
        canvas=CANVAS,
        layers=[axes, point, swing, trace_layer("p"), trace_layer("swing").model_copy(update={"id": "bob"})],
    )
    on_axes = centres(project, "p", TIMES)
    assert on_axes[0] is None and on_axes[10] is not None  # not drawn before 0.5 s
    evaluator = Evaluator(project)
    params = {"length": 1.5, "angle": 60.0}
    state = SWING.start(params)
    bobs = [np.array(bob(state, params))]
    for _ in TIMES[1:]:
        state = swing_step(state.copy(), 1 / FPS, params)
        bobs.append(np.array(bob(state, params)))
    bobs = [np.array([1.0, 2.0]) + 0.5 * b for b in bobs]  # through the layer's transform
    for k in random.Random(3).sample(range(len(TIMES)), 12):
        layers = dict(evaluator.frame_layers(TIMES[k]))
        assert np.allclose(anchors(layers["trace"]), dedup([c for c in on_axes[: k + 1] if c is not None])), k
        assert np.allclose(anchors(layers["bob"]), dedup(bobs[: k + 1])), k


def test_an_offset_on_a_child_object_scales_and_turns_with_its_parent() -> None:
    axes = Layer(id="axes", spec=Spec(type="Axes"), base=Transform2D(scale=2.0, rotation=90.0))
    point = Layer(id="p", parent_id="axes", spec=Spec(type="Point"))
    project = Project(canvas=CANVAS, layers=[axes, point, trace_layer("p", offset=(0.5, 0.0))])
    layers = dict(Evaluator(project).frame_layers(0.0))
    expected = layers["p"].get_center()[:2] + np.array([0.0, 1.0])  # 0.5 right, doubled, turned 90 degrees
    assert anchors(layers["trace"])[-1] == pytest.approx(expected, abs=1e-6)


def test_frames_where_the_target_is_not_drawn_break_the_trace(monkeypatch) -> None:
    project = Project(canvas=CANVAS, layers=[dot_layer(), trace_layer()])
    evaluator = Evaluator(project)
    sample = evaluator._traced_point
    monkeypatch.setattr(
        evaluator,
        "_traced_point",
        lambda target, t, offset: None if 0.3 < t < 0.6 else sample(target, t, offset),
    )
    trace = dict(evaluator.frame_layers(TIMES[20]))["trace"]
    assert len(trace.get_subpaths()) == 2


def test_sampling_a_trace_leaves_the_frame_being_drawn_intact() -> None:
    """The trace samples its target at earlier times; the target is drawn before the trace
    (list order), so sampling must happen first or the target shows an earlier state."""
    ring = Layer(id="ring", spec=Spec(type="Circle", params={"radius": 2.0}))
    run = Clip(id="r", kind="MoveAlongPath", start=0.0, duration=3.0, params={"path": "ring"})
    plain = Layer(id="dot", spec=Spec(type="Dot"), clips=[run])  # no transform: drawn from its own buffer
    axes = Layer(id="axes", spec=Spec(type="Axes"), clips=[Clip(id="w", kind="Wiggle", start=0, duration=3)])
    point = Layer(id="p", parent_id="axes", spec=Spec(type="Point"))  # drawn from its tree's buffers
    for target, objects in (("dot", [ring, plain]), ("p", [axes, point])):
        alone = Project(canvas=CANVAS, layers=objects)
        for layers in ([*objects, trace_layer(target)], [trace_layer(target), *objects]):
            project = Project(canvas=CANVAS, layers=layers)
            for t in (TIMES[20], TIMES[44]):
                drawn = dict(Evaluator(project).frame_layers(t))[target]
                expected = dict(Evaluator(alone).frame_layers(t))[target]
                assert np.allclose(drawn.get_all_points(), expected.get_all_points()), (target, t)


def test_only_edits_to_what_the_target_is_drawn_from_resample_a_trace() -> None:
    axes = Layer(id="axes", spec=Spec(type="Axes"))
    point = Layer(id="p", parent_id="axes", spec=Spec(type="Point"))
    other = Layer(id="sq", spec=Spec(type="Square"))
    project = Project(canvas=CANVAS, layers=[axes, point, other, trace_layer("p")])
    evaluator = Evaluator(project)
    evaluator.frame(1.0)
    kept = evaluator._traces["trace"].points
    moved_square = edits.update_layer(project, "sq", base=Transform2D(position=(2.0, 0.0)))
    evaluator.apply(moved_square)
    evaluator.frame(1.0)
    assert evaluator._traces["trace"].points is kept
    keyed = edits.update_layer(moved_square.project, "axes", base=Transform2D(position=(0.0, 1.0)))
    evaluator.apply(keyed)
    trace = dict(evaluator.frame_layers(1.0))["trace"]
    assert evaluator._traces["trace"].points is not kept
    assert np.allclose(anchors(trace), anchors(dict(Evaluator(keyed.project).frame_layers(1.0))["trace"]))


def test_moving_the_path_a_target_follows_resamples_its_trace() -> None:
    ring = Layer(id="ring", spec=Spec(type="Circle", params={"radius": 2.0}))
    run = Clip(id="r", kind="MoveAlongPath", start=0.0, duration=3.0, params={"path": "ring"})
    project = Project(
        canvas=CANVAS, layers=[ring, Layer(id="dot", spec=Spec(type="Dot"), clips=[run]), trace_layer()]
    )
    evaluator = Evaluator(project)
    evaluator.frame(1.0)
    moved = edits.update_layer(project, "ring", base=Transform2D(position=(1.0, 0.0)))
    evaluator.apply(moved)
    trace = dict(evaluator.frame_layers(1.0))["trace"]
    assert np.allclose(anchors(trace), anchors(dict(Evaluator(moved.project).frame_layers(1.0))["trace"]))


def test_render_ahead_drops_a_traces_frames_when_its_target_changes() -> None:
    project = Project(
        canvas=CANVAS, layers=[dot_layer(), Layer(id="sq", spec=Spec(type="Square")), trace_layer()]
    )
    moved = edits.update_layer(project, "dot", base=Transform2D(position=(0.0, 1.0))).project
    assert changed_layers(project, moved) == {"dot", "trace"}


def test_trace_rules() -> None:
    dot = dot_layer()
    with pytest.raises(ValueError, match="'nope' is missing"):
        Project(layers=[dot, trace_layer("nope")])
    with pytest.raises(ValueError, match="cannot be traced"):
        Project(layers=[dot, trace_layer(), trace_layer("trace").model_copy(update={"id": "t2"})])
    with pytest.raises(ValueError, match="cannot be traced"):
        Project(layers=[dot, trace_layer("trace")])
    with pytest.raises(ValueError, match="has no clips"):
        Layer.model_validate(
            trace_layer().model_dump() | {"clips": [{"id": "f", "kind": "FadeIn", "start": 0, "duration": 1}]}
        )
    run = Clip(id="r", kind="MoveAlongPath", start=0, duration=1, params={"path": "trace"})
    with pytest.raises(ValueError, match="cannot be its path"):
        Project(layers=[dot, trace_layer(), Layer(id="r", spec=Spec(type="Dot"), clips=[run])])
    morph = Clip(id="m", kind="Transform", start=0, duration=1, to_layer="trace")
    with pytest.raises(ValueError, match="cannot morph into a traced path"):
        Project(layers=[dot, trace_layer(), Layer(id="s", spec=Spec(type="Square"), clips=[morph])])
    assert adapter.allowed_clip_kinds("TracedPath") == [] and adapter.allowed_clip_kinds("Swing") == []


def test_deleting_a_traced_layer_deletes_its_traces() -> None:
    project = Project(canvas=CANVAS, layers=[dot_layer(), trace_layer()])
    assert [x.id for x in edits.remove_layer(project, "dot").project.layers] == []


def test_simulated_layers_make_a_python_export_exact() -> None:
    project = Project(
        canvas=CANVAS, layers=[dot_layer(), trace_layer(), Layer(id="swing", spec=Spec(type="Swing"))]
    )
    problems = readable_problems(project)
    assert "trace: a simulated layer" in problems and "swing: a simulated layer" in problems


def test_trace_runs_are_separate_sub_paths() -> None:
    mob = adapter.trace_mobject(
        [np.array([[0, 0, 0], [1, 0, 0]]), np.array([[2, 0, 0]])], {"stroke": "#ff0000"}
    )
    assert len(mob.get_subpaths()) == 2 and mob.get_stroke_width() == 2
    assert m.color_to_rgb(mob.get_stroke_color()) == pytest.approx([1.0, 0.0, 0.0])


def test_a_trace_matches_manims_traced_path_within_one_play() -> None:
    """Manim's play loop with a TracedPath following a dot, frame by frame (B46)."""
    rendered: list[np.ndarray] = []
    camera = make_camera(CANVAS)

    class Traced(m.Scene):
        def construct(self) -> None:
            dot = m.Dot([-3.0, -1.0, 0.0])
            trace = m.TracedPath(dot.get_center)
            self.add(trace, dot)
            self.renderer.render = lambda scene, t, moving: rendered.append(
                render_frame(camera, [trace, dot])
            )
            self.play(dot.animate.move_to([3.0, 1.5, 0.0]), run_time=2.0, rate_func=m.linear)

    with m.tempconfig({"frame_rate": FPS, "disable_caching": True, "dry_run": True}):
        Traced().render()
    linear = {
        "position": [
            Keyframe(t=0.0, value=(-3.0, -1.0), ease={"name": "linear"}),
            Keyframe(t=2.0, value=(3.0, 1.5)),
        ]
    }
    project = Project(
        canvas=CANVAS, layers=[trace_layer(), Layer(id="dot", spec=Spec(type="Dot"), tracks=linear)]
    )
    ours = frames(project, TIMES[: len(rendered)])
    assert len(rendered) == 30
    assert np.abs(rendered[-1].astype(int) - rendered[0].astype(int)).sum() > 0  # it drew something
    for i, frame in enumerate(rendered):
        assert max_diff(frame, ours[i]) <= 1, i
