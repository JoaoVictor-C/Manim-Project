"""Preset thumbnails (P6d.3, ADR 0044): which frames, the project they are drawn from, the
frames themselves for every built-in preset, and the cache that keeps them."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.core import library
from manim_studio.core.edits import EditError
from manim_studio.render import preset_thumbs as thumbs

BACKGROUND = "#141417"
BUILTIN = library.load_library([library.BUILTIN_FOLDER]).presets


def preset(name: str) -> library.Preset:
    return next(p for p in BUILTIN if p.name == name)


def only_keys(dt: float = 0.2) -> library.Preset:
    return library.Preset(
        name="Nudge",
        category="motion",
        keys={
            "position": [
                library.PresetKey(dt=0.0, value=(0.0, 0.0)),
                library.PresetKey(dt=dt, value=(1.0, 0.0)),
            ]
        },
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    thumbs.clear_cache()
    yield
    thumbs.clear_cache()


def blank(frame: np.ndarray) -> bool:
    return bool((frame == frame[0, 0]).all())  # one colour: nothing but the background


# -- which frames -------------------------------------------------------------------------------------


def test_the_run_is_the_longest_clip_or_key_and_at_least_half_a_second() -> None:
    clips = library.Preset(
        name="Two",
        category="entrance",
        clips=[
            library.PresetClip(kinds=["FadeIn"], offset=0.0, duration=0.4),
            library.PresetClip(kinds=["FadeIn"], offset=1.0, duration=0.75),
        ],
    )
    assert thumbs.span(clips) == pytest.approx(1.75)
    assert thumbs.span(only_keys(2.5)) == pytest.approx(2.5)  # keys count, not only clips
    assert thumbs.span(only_keys(0.2)) == thumbs.MIN_SPAN == 0.5


def test_frames_are_spread_over_the_run_from_its_start_to_just_before_its_end() -> None:
    p = preset("Fade in")
    times = thumbs.frame_times(p)
    assert len(times) == thumbs.FRAMES == 8
    assert times[0] == 0.0
    assert times == sorted(set(times))
    assert times[-1] == pytest.approx(thumbs.span(p) * 0.999)
    assert times[-1] < thumbs.span(p)
    steps = np.diff(times)
    assert steps == pytest.approx(np.full(len(steps), steps[0]))  # evenly
    assert 0 < thumbs.STILL < thumbs.FRAMES - 1  # the card at rest shows the middle of the run


# -- the project it is drawn from ---------------------------------------------------------------------


def test_the_project_is_a_small_square_with_the_preset_applied_at_zero() -> None:
    p = preset("Slide in from left")
    project = thumbs.thumb_project(p, BACKGROUND)
    assert (project.canvas.width_px, project.canvas.height_px) == (160, 90)
    assert project.canvas.background == BACKGROUND
    assert project.canvas.duration >= thumbs.span(p) + 1.0 - 1e-9
    (layer,) = project.layers
    assert layer.spec.type == "Square"
    assert layer.spec.style["fill"] == thumbs.SQUARE_FILL
    starts = [c.start for c in layer.clips] + [k.t for track in layer.tracks.values() for k in track]
    assert starts and min(starts) == 0.0


def test_a_run_longer_than_the_default_scene_still_fits() -> None:
    long = library.Preset(
        name="Slow",
        category="entrance",
        clips=[library.PresetClip(kinds=["FadeIn"], duration=9.0)],
    )
    project = thumbs.thumb_project(long, BACKGROUND)
    assert project.canvas.duration >= 9.0
    assert len(thumbs.render_thumbnail(long, BACKGROUND)) == thumbs.FRAMES


def test_a_preset_a_square_cannot_take_has_no_thumbnail() -> None:
    text_only = library.Preset(
        name="Text only",
        category="entrance",
        clips=[library.PresetClip(kinds=["AddTextLetterByLetter"], duration=1.0)],
    )
    with pytest.raises(EditError):
        thumbs.thumb_project(text_only, BACKGROUND)
    assert thumbs.render_thumbnail(text_only, BACKGROUND) == []
    assert thumbs.thumbnails(text_only, BACKGROUND) == []


# -- the frames ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("p", BUILTIN, ids=lambda p: p.name)
def test_every_builtin_preset_draws_eight_frames_that_move(p) -> None:
    frames = thumbs.render_thumbnail(p, BACKGROUND)
    assert len(frames) == thumbs.FRAMES
    for frame in frames:
        assert frame.shape == (90, 160, 4) and frame.dtype == np.uint8
    distinct = {frame.tobytes() for frame in frames}
    assert len(distinct) >= 2, f"{p.name} looks the same all along"
    assert not all(blank(f) for f in frames), f"{p.name} never shows the square"
    assert not blank(frames[thumbs.STILL]) or p.category == "exit", f"{p.name}: an empty still"


def test_an_entrance_grows_from_nothing_and_an_exit_goes_to_nothing() -> None:
    fade_in = thumbs.render_thumbnail(preset("Fade in"), BACKGROUND)
    assert blank(fade_in[0]) and not blank(fade_in[-1])
    fade_out = thumbs.render_thumbnail(preset("Fade out"), BACKGROUND)
    assert not blank(fade_out[0]) and fade_out[-1].astype(int).sum() < fade_out[0].astype(int).sum()
    assert not blank(fade_out[thumbs.STILL])  # half faded, still there


def test_the_background_is_the_one_given() -> None:
    frame = thumbs.render_thumbnail(preset("Fade in"), "#102030")[0]
    assert tuple(frame[0, 0]) == (0x10, 0x20, 0x30, 255)


def test_the_square_is_drawn_in_the_middle_in_its_fill() -> None:
    frame = thumbs.render_thumbnail(preset("Fade in"), BACKGROUND)[-1]
    assert tuple(frame[45, 80][:3]) == (0x3B, 0x82, 0xF6)
    assert tuple(frame[45, 80 + 14][:3]) == (0x3B, 0x82, 0xF6)  # 3 units wide: about 34 px
    assert tuple(frame[45, 80 + 24][:3]) == (0x14, 0x14, 0x17)  # and no wider


# -- the cache ----------------------------------------------------------------------------------------


def test_a_preset_is_drawn_once_and_then_kept(monkeypatch) -> None:
    calls = []
    real = thumbs.render_thumbnail

    def counting(p, background):
        calls.append(p.name)
        return real(p, background)

    monkeypatch.setattr(thumbs, "render_thumbnail", counting)
    first = thumbs.thumbnails(preset("Pop in"), BACKGROUND)
    again = thumbs.thumbnails(preset("Pop in"), BACKGROUND)
    assert again is first and calls == ["Pop in"] and thumbs.cache_size() == 1
    thumbs.thumbnails(preset("Fade in"), BACKGROUND)
    assert calls == ["Pop in", "Fade in"] and thumbs.cache_size() == 2


def test_the_cache_follows_the_preset_content_not_its_object_or_name(monkeypatch) -> None:
    calls = []
    real = thumbs.render_thumbnail
    monkeypatch.setattr(thumbs, "render_thumbnail", lambda p, b: calls.append(1) or real(p, b))
    original = preset("Pop in")
    thumbs.thumbnails(original, BACKGROUND)
    thumbs.thumbnails(original.model_copy(deep=True), BACKGROUND)  # an equal copy: kept
    assert len(calls) == 1
    longer = original.model_copy(
        update={"clips": [original.clips[0].model_copy(update={"duration": original.clips[0].duration + 1})]}
    )
    thumbs.thumbnails(longer, BACKGROUND)  # same name, edited: drawn again
    assert len(calls) == 2
    thumbs.thumbnails(original, "#222222")  # another background: drawn again
    assert len(calls) == 3


def test_clearing_the_cache_draws_again(monkeypatch) -> None:
    calls = []
    real = thumbs.render_thumbnail
    monkeypatch.setattr(thumbs, "render_thumbnail", lambda p, b: calls.append(1) or real(p, b))
    thumbs.thumbnails(preset("Pop in"), BACKGROUND)
    thumbs.clear_cache()
    assert thumbs.cache_size() == 0
    thumbs.thumbnails(preset("Pop in"), BACKGROUND)
    assert len(calls) == 2


def test_all_builtin_thumbnails_take_well_under_a_second() -> None:
    import time

    start = time.perf_counter()
    for p in BUILTIN:
        thumbs.thumbnails(p, BACKGROUND)
    assert time.perf_counter() - start < 3.0  # ~0.06 s alone (B61); slack for a loaded machine
