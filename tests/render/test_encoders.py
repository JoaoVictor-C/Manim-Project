"""Which encoder an export uses (ADR 0065): the card's NVENC when it has one and it pays, else x264."""

from __future__ import annotations

import pytest

from manim_studio.render import encoders
from manim_studio.render.options import MAX_JOBS, OptionsError, RenderOptions

FULL_HD = (1920, 1080)
LONG = 1000  # frames: well past the point where waking the card pays
SHORT = 30


@pytest.fixture
def card(monkeypatch):
    monkeypatch.setattr(encoders, "gpu_listed", lambda: True)


def names(options: list[encoders.Encoder]) -> list[str]:
    return [e.codec for e in options]


def test_cpu_is_always_x264(card) -> None:
    assert names(encoders.candidates("cpu", 18, LONG, *FULL_HD)) == ["libx264"]


def test_a_long_video_goes_to_the_card_with_x264_behind_it(card) -> None:
    assert names(encoders.candidates("auto", 18, LONG, *FULL_HD)) == ["h264_nvenc", "libx264"]
    assert names(encoders.candidates("gpu", 18, LONG, *FULL_HD)) == ["h264_nvenc", "libx264"]


def test_auto_keeps_a_short_video_on_the_processor_but_gpu_does_not(card) -> None:
    """Waking a laptop's card takes seconds: x264 is done before that for a few frames."""
    assert names(encoders.candidates("auto", 18, SHORT, *FULL_HD)) == ["libx264"]
    assert names(encoders.candidates("gpu", 18, SHORT, *FULL_HD)) == ["h264_nvenc", "libx264"]


def test_the_pixels_decide_not_the_frames_alone(card) -> None:
    few_big = encoders.candidates("auto", 18, 120, 3840, 2160)  # 120 frames of 4K = 8.3 Gpx
    assert names(few_big) == ["h264_nvenc", "libx264"]
    assert names(encoders.candidates("auto", 18, 120, 320, 180)) == ["libx264"]


def test_render_processes_use_the_cores_so_auto_hands_the_encoding_to_the_card(card) -> None:
    assert names(encoders.candidates("auto", 18, SHORT, *FULL_HD, farming=True)) == ["h264_nvenc", "libx264"]
    assert names(encoders.candidates("cpu", 18, SHORT, *FULL_HD, farming=True)) == ["libx264"]


def test_without_an_nvenc_encoder_in_this_build_everything_is_x264(monkeypatch) -> None:
    monkeypatch.setattr(encoders, "gpu_listed", lambda: False)
    for choice in ("auto", "gpu", "cpu"):
        assert names(encoders.candidates(choice, 18, LONG, *FULL_HD)) == ["libx264"]


def test_an_unknown_encoder_is_refused() -> None:
    with pytest.raises(ValueError, match="encoder must be one of"):
        encoders.candidates("tpu", 18, LONG, *FULL_HD)


def test_the_cards_quality_scale_follows_crf_and_stays_in_range() -> None:
    """crf 18 and cq 28 give the same picture and size on Cairo frames (ADR 0065)."""
    assert encoders.nvenc(18).options["cq"] == "28"
    assert encoders.nvenc(12).options["cq"] == "22"
    assert encoders.nvenc(51).options["cq"] == "51"
    assert encoders.x264(23).options == {"crf": "23"}


def test_the_card_is_given_rgba_and_x264_converts_itself() -> None:
    assert encoders.nvenc(18).pixel_format == "rgba" and encoders.nvenc(18).hardware
    assert encoders.x264(18).pixel_format == "yuv420p" and not encoders.x264(18).hardware


# -- options ---------------------------------------------------------------------------------


def test_the_new_options_are_flags_only_when_they_are_not_the_default() -> None:
    assert RenderOptions().to_args() == []
    assert RenderOptions(encoder="gpu", jobs=4).to_args() == ["--encoder", "gpu", "--jobs", "4"]
    assert RenderOptions(encoder="cpu").to_args() == ["--encoder", "cpu"]


def test_bad_encoder_and_jobs_are_refused() -> None:
    for bad in ({"encoder": "tpu"}, {"jobs": 0}, {"jobs": MAX_JOBS + 1}):
        with pytest.raises(OptionsError):
            RenderOptions(**bad)
