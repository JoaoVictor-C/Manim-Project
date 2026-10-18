"""The project's camera (P7.5, ADR 0048): 3D-capable, fixed for 2D.

The default camera draws through Manim's 2D camera bit for bit as before (a copy
of the pre-P7.5 camera code is the reference); any other camera draws the flat
scene seen from its angles, in the canvas, the preview process and the export.
"""

from __future__ import annotations

import json
from pathlib import Path

import av
import manim as m
import numpy as np
import pytest
from pydantic import ValidationError

from manim_studio.core import edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.frame_cache import changed_layers, changed_spans
from manim_studio.core.python_export import to_python
from manim_studio.core.schema import Camera, Canvas, Clip, Cue, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import export_video, frame_times, make_camera, render_frame
from manim_studio.render.preview import PreviewView, StudioThreeDCamera, preview_camera, scene_camera

ROOT = Path(__file__).resolve().parents[2]
SHOWCASE = ROOT / "examples" / "showcase.json"
TILTED = Camera(phi=60.0)
CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=0.3)


def scene(camera: Camera | None = None) -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="sq",
                spec=Spec(
                    type="Square", params={"side_length": 3.0}, style={"fill": "#3b82f6", "fill_opacity": 1}
                ),
                clips=[Clip(id="in", kind="FadeIn", start=0.0, duration=0.3)],
            ),
            Layer(
                id="ring",
                spec=Spec(type="Circle", params={"radius": 2.5}),
                base=Transform2D(position=(1.0, 0.5)),
            ),
        ],
        subtitles=[Cue(id="cue", start=0.0, end=0.3, text="Hello")],
        **({"camera": camera} if camera is not None else {}),
    )


# -- the camera as it was before P7.5: the reference for bit identity -----------------------------


def old_preview_camera(view: PreviewView) -> m.Camera:
    camera = m.Camera(
        pixel_width=view.pixel_width,
        pixel_height=view.pixel_height,
        frame_width=view.frame_width,
        frame_height=view.frame_height,
        background_color=m.ManimColor(view.background),
        background_opacity=1.0,
    )
    camera.frame_center = np.array([view.centre[0], view.centre[1], 0.0])
    return camera


def old_make_camera(canvas: Canvas) -> m.Camera:
    return m.Camera(
        pixel_width=canvas.width_px,
        pixel_height=canvas.height_px,
        frame_width=canvas.frame_width,
        frame_height=canvas.frame_height,
        background_color=m.ManimColor(canvas.background),
        background_opacity=1.0,
    )


def old_render_frame(camera: m.Camera, mobjects) -> np.ndarray:
    from manim_studio.core.code_frame import CodeFrame

    camera.reset()
    run = []
    for mob in mobjects:
        if isinstance(mob, CodeFrame):
            if run:
                camera.capture_mobjects(run)
                run = []
            mob.paint(camera)
        else:
            run.append(mob)
    if run:
        camera.capture_mobjects(run)
    return np.array(camera.pixel_array, copy=True)


# -- the schema ------------------------------------------------------------------------------------


def test_the_default_camera_is_the_flat_view_and_is_not_saved() -> None:
    project = Project()
    assert project.camera.is_default
    assert "camera" not in json.loads(project.model_dump_json(by_alias=True))
    assert not TILTED.is_default and not Camera(theta=0.0).is_default and not Camera(gamma=5.0).is_default


@pytest.mark.parametrize("name", ["showcase.json", "euler.json", "graphs.json"])
def test_old_files_load_and_save_unchanged(name) -> None:
    path = ROOT / "examples" / name
    if not path.exists():
        pytest.skip(f"{name} is not in this checkout")
    data = json.loads(path.read_text(encoding="utf-8"))
    project = Project.model_validate(data)
    assert project.camera.is_default
    assert json.loads(project.model_dump_json(by_alias=True)) == json.loads(
        Project.model_validate(data).model_dump_json(by_alias=True)
    )
    assert "camera" not in json.loads(project.model_dump_json(by_alias=True))


def test_a_turned_camera_is_saved_and_read_back() -> None:
    project = scene(Camera(phi=60.0, theta=-45.0, gamma=10.0))
    data = json.loads(project.model_dump_json(by_alias=True))
    assert data["camera"] == {"phi": 60.0, "theta": -45.0, "gamma": 10.0}
    assert Project.model_validate(data).camera == project.camera


@pytest.mark.parametrize(
    "bad", [{"phi": -1.0}, {"phi": 181.0}, {"theta": 200.0}, {"gamma": -181.0}, {"zoom": 2.0}]
)
def test_camera_ranges_are_validated(bad) -> None:
    with pytest.raises(ValidationError):
        Camera(**bad)


# -- edits, invalidation ---------------------------------------------------------------------------


def test_set_camera_is_a_validated_edit_of_every_layer() -> None:
    project = scene()
    edit = edits.set_camera(project, phi=45.0)
    assert edit.project.camera == Camera(phi=45.0) and project.camera.is_default  # pure
    assert edit.kind == "spec" and edit.layer_ids == {"sq", "ring"}
    with pytest.raises(edits.EditError):
        edits.set_camera(project, phi=500.0)
    with pytest.raises(edits.EditError):
        edits.set_camera(project, zoom=2.0)
    assert edits.reset_camera(edit.project).project.camera.is_default
    assert edits.set_camera(project, phi=0.0).project is project  # no change, no step


def test_classify_treats_a_camera_change_as_a_spec_change_of_every_layer() -> None:
    project = scene()
    kind, layer_ids = edits.classify(project, edits.set_camera(project, theta=-60.0).project)
    assert kind == "spec" and layer_ids == {"sq", "ring"}


def test_a_camera_change_invalidates_every_frame() -> None:
    project = scene()
    turned = edits.set_camera(project, phi=30.0).project
    assert changed_layers(project, turned) is None
    assert changed_spans(project, turned) is None
    assert changed_spans(turned, edits.reset_camera(turned).project) is None


# -- one camera function ---------------------------------------------------------------------------


def showcase_frames():
    project = Project.model_validate_json(SHOWCASE.read_text(encoding="utf-8"))
    evaluator = Evaluator(project)
    for t in np.linspace(0.3, project.canvas.duration - 0.3, 4):
        yield project, evaluator, float(t)


def test_default_camera_frames_are_bit_identical_to_before() -> None:
    """The showcase, framed by the canvas (zoomed, panned) and by the export, at four times."""
    lit = 0
    for project, evaluator, t in showcase_frames():
        canvas = project.canvas.model_copy(update={"width_px": 320, "height_px": 180})
        view = PreviewView(300, 200, 12.0, 8.0, (0.75, -0.5), canvas.background)
        layers = [mob for _, mob in evaluator.frame_layers(t)]
        overlay = evaluator.overlay(t)
        before = old_render_frame(old_preview_camera(view), evaluator.frame(t))
        now = render_frame(preview_camera(view, project.camera), layers, overlay)
        assert np.array_equal(before, now), t
        before = old_render_frame(old_make_camera(canvas), evaluator.frame(t))
        assert np.array_equal(before, render_frame(make_camera(canvas, project.camera), layers, overlay)), t
        lit += int((np.abs(now.astype(int) - now[0, 0].astype(int)).sum(axis=2) > 30).sum())
    assert lit > 1000  # the frames are drawn, not empty


def test_the_default_camera_is_manims_2d_camera() -> None:
    view = PreviewView(64, 36, 16.0, 9.0, (0.0, 0.0), "#000000")
    assert type(scene_camera(view)) is m.Camera
    assert type(scene_camera(view, Camera())) is m.Camera
    assert isinstance(scene_camera(view, TILTED), StudioThreeDCamera)


def test_subtitled_frames_are_identical_with_the_overlay_apart() -> None:
    project = scene()
    evaluator = Evaluator(project)
    camera = make_camera(project.canvas)
    for t in (0.0, 0.15):
        layers = [mob for _, mob in evaluator.frame_layers(t)]
        assert np.array_equal(
            old_render_frame(old_make_camera(project.canvas), evaluator.frame(t)),
            render_frame(camera, layers, evaluator.overlay(t)),
        )


def test_a_tilted_camera_draws_the_scene_from_its_angle() -> None:
    project = scene(TILTED)
    evaluator = Evaluator(project)
    t = 0.2
    layers = [mob for _, mob in evaluator.frame_layers(t)]
    flat = render_frame(make_camera(project.canvas), layers)
    tilted = render_frame(make_camera(project.canvas, project.camera), layers)
    assert np.abs(flat.astype(int) - tilted.astype(int)).mean() > 1.0
    # Manim's own ThreeDCamera at the same angles (a ThreeDScene) draws the same picture
    manims = m.ThreeDCamera(
        pixel_width=320,
        pixel_height=180,
        frame_width=CANVAS.frame_width,
        frame_height=CANVAS.frame_height,
        background_color=m.ManimColor(CANVAS.background),
        background_opacity=1.0,
    )
    manims.set_phi(60 * m.DEGREES)
    assert np.array_equal(tilted, render_frame(manims, layers))
    # seen from 60 degrees the square is shorter than it is wide
    rows = np.where((tilted[:, :, 2].astype(int) - tilted[:, :, 0].astype(int)) > 80)[0]
    cols = np.where((tilted[:, :, 2].astype(int) - tilted[:, :, 0].astype(int)) > 80)[1]
    assert np.ptp(rows) < 0.75 * np.ptp(cols)


def test_a_pan_moves_a_tilted_picture_without_turning_it() -> None:
    project = scene(TILTED)
    evaluator = Evaluator(project)
    layers = [mob for _, mob in evaluator.frame_layers(0.2)]
    view = PreviewView(320, 180, CANVAS.frame_width, CANVAS.frame_height, (0.0, 0.0), CANVAS.background)
    shift = round(320 / CANVAS.frame_width)  # one unit, in pixels: 20
    still = render_frame(preview_camera(view, TILTED), layers)
    panned = render_frame(
        preview_camera(PreviewView(**{**view.to_json(), "centre": (1.0, 0.0)}), TILTED), layers
    )
    assert np.abs(panned[:, : 320 - shift].astype(int) - still[:, shift:].astype(int)).mean() < 0.5


def test_subtitles_stay_flat_on_the_screen_under_a_tilted_camera() -> None:
    project = scene(TILTED)
    evaluator = Evaluator(project)
    t = 0.15
    flat_cam, tilted_cam = make_camera(project.canvas), make_camera(project.canvas, TILTED)
    only_subtitle_flat = render_frame(flat_cam, [], evaluator.overlay(t))
    only_subtitle_tilted = render_frame(tilted_cam, [], evaluator.overlay(t))
    assert np.abs(only_subtitle_flat.astype(int)).sum() > 0
    assert np.array_equal(only_subtitle_flat, only_subtitle_tilted)


def test_code_frames_are_painted_seen_from_the_camera() -> None:
    from manim_studio.core.code_cache import Crop
    from manim_studio.core.code_frame import CodeFrame

    pixels = np.zeros((40, 60, 4), np.uint8)
    pixels[..., 1] = pixels[..., 3] = 255
    frame = CodeFrame(Crop(x=130, y=70, pixels=pixels), CANVAS, np.eye(2), np.zeros(2), 1.0)
    flat = render_frame(make_camera(CANVAS), [frame])
    tilted = render_frame(make_camera(CANVAS, TILTED), [frame])
    green = lambda image: np.argwhere(image[:, :, 1] > 128)  # noqa: E731
    f, g = green(flat), green(tilted)
    assert len(g) and (np.ptp(g[:, 0]) < 0.8 * np.ptp(f[:, 0]))  # shorter, as a tilted square
    assert abs(np.ptp(g[:, 1]) - np.ptp(f[:, 1])) <= 4  # the middle row keeps its width
    edge_on = render_frame(make_camera(CANVAS, Camera(phi=90.0)), [frame])
    assert edge_on.shape == flat.shape  # seen edge on: nothing, and no error


# -- the export -----------------------------------------------------------------------------------


def test_the_export_renders_a_tilted_camera(tmp_path) -> None:
    project = scene(TILTED)
    out = export_video(project, tmp_path / "tilted.mp4")
    with av.open(str(out.path)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    times = frame_times(project.canvas)
    assert len(frames) == len(times) == 3
    evaluator = Evaluator(project)
    turned, flat = make_camera(project.canvas, TILTED), make_camera(project.canvas)
    for frame, t in zip(frames, times, strict=True):
        layers = [mob for _, mob in evaluator.frame_layers(t)]
        ours = render_frame(turned, layers, evaluator.overlay(t))[:, :, :3].astype(int)
        assert np.abs(frame.astype(int) - ours).mean() < 1.5  # h264 noise only
        if t > 0:
            plain = render_frame(flat, layers, evaluator.overlay(t))[:, :, :3].astype(int)
            assert np.abs(frame.astype(int) - plain).mean() > 2.0


# -- Python export ----------------------------------------------------------------------------------


def plain() -> Project:
    return scene().model_copy(update={"subtitles": []})


def test_python_export_of_the_default_camera_is_unchanged() -> None:
    code = to_python(plain(), "Intro").code
    assert "class Intro(Scene):" in code and "camera" not in code


def test_readable_python_export_sets_the_camera() -> None:
    project = plain().model_copy(update={"camera": Camera(phi=60.0, theta=-45.0, gamma=10.0)})
    export = to_python(project, "Intro")
    assert export.readable
    assert "class Intro(ThreeDScene):" in export.code
    assert "self.set_camera_orientation(phi=60.0 * DEGREES, theta=-45.0 * DEGREES, gamma=10.0 * DEGREES)" in (
        export.code
    )


def test_exact_python_export_keeps_the_camera_in_the_project() -> None:
    export = to_python(scene(TILTED), "Intro")  # burned-in subtitles: exact
    assert not export.readable and '"camera"' in export.code


def test_the_exact_scene_uses_the_turned_camera() -> None:
    """StudioScene picks Manim's 3D camera at the project's angles (checked without rendering)."""
    from manim_studio.manim_scene import StudioScene

    class Probe(StudioScene):
        project_json = scene(TILTED).model_dump_json(by_alias=True)

    probe = Probe()
    assert isinstance(probe.renderer.camera, StudioThreeDCamera)
    probe.setup()
    assert probe.renderer.camera.get_phi() == 60.0 * m.DEGREES

    class Flat(StudioScene):
        project_json = scene().model_dump_json(by_alias=True)

    assert type(Flat().renderer.camera) is m.Camera


@pytest.mark.slow
def test_readable_code_with_a_camera_renders_what_the_editor_shows(tmp_path) -> None:
    from tests.core.test_python_export import rendered

    project = plain().model_copy(
        update={"camera": TILTED, "canvas": CANVAS.model_copy(update={"duration": 0.5})}
    )
    export = to_python(project, "Tilted")
    assert export.readable
    assert_matches_editor_turned(project, rendered(export.code, "Tilted", tmp_path))


def assert_matches_editor_turned(project: Project, frames: list[np.ndarray]) -> None:
    times = frame_times(project.canvas)
    assert len(frames) == len(times)
    evaluator, camera = Evaluator(project), make_camera(project.canvas, project.camera)
    for i, t in enumerate(times):
        ours = render_frame(camera, evaluator.frame(t))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - ours).mean() < 1.5, t
