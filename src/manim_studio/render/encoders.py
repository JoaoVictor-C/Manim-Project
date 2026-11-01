"""Which video encoder an export uses: the graphics card's if it has one and it pays, else x264 (ADR 0065).

The frames are drawn by Manim's Cairo camera on the processor - that is what makes the canvas and the video
the same pixels (ADR 0028) - but turning them into H.264 can be done by the card. NVENC takes the camera's
RGBA straight from memory and does the colour conversion itself, so the processor neither converts nor
compresses: at 4K that is 24 ms a frame against x264's 74 ms, and about a sixth of the processor time.

``candidates`` lists what to try, best first, and always ends with x264: a card that cannot open the session
(a driver without NVENC, the card's limit of sessions at once) falls through to the next entry before any
frame is written. Only NVENC is offered: it is the one verified against x264 (picture and size at the same
quality, below). Intel's QSV opened here but was slower than x264 and much worse at the same setting, and
AMD's AMF and Apple's VideoToolbox could not be tried, so those machines get x264.
"""

from __future__ import annotations

from dataclasses import dataclass

import av

from .options import ENCODERS

# Waking a laptop's graphics card and opening its encoder takes one to three seconds, which x264 would use
# to encode on its own anything this small: "auto" keeps the processor for exports shorter than this.
GPU_MIN_PIXELS = 1920 * 1080 * 400  # pixels in the whole video (400 frames of Full HD, 13 s at 30 fps)
# NVENC's constant-quality scale runs about ten steps above x264's CRF for the same picture and size: on
# Cairo frames, crf 18 and cq 28 are within 0.5 dB and 5 % of each other (ADR 0065).
CQ_OFFSET = 10
NVENC_MAX_SIDE = 4096  # H.264 on the card does not go beyond this on either side (8K opens and fails)


@dataclass(frozen=True)
class Encoder:
    """One way to encode: the codec, its options, and how frames are handed to it."""

    codec: str
    options: dict[str, str]
    pixel_format: str  # of the stream (what the encoder is given); the file is yuv420p either way
    label: str  # for the user: "GPU (NVENC)" / "CPU (x264)"
    hardware: bool = False


def x264(crf: int) -> Encoder:
    return Encoder("libx264", {"crf": str(crf)}, "yuv420p", "CPU (x264)")


def nvenc(crf: int) -> Encoder:
    options = {
        "rc": "vbr",
        "cq": str(min(51, crf + CQ_OFFSET)),
        "b": "0",  # no bitrate target: the constant quality decides
        "preset": "p5",
        "tune": "hq",
        "profile": "high",
    }
    return Encoder("h264_nvenc", options, "rgba", "GPU (NVENC)", hardware=True)


def by_codec(codec: str, crf: int) -> Encoder | None:
    """The encoder that ``codec`` names, as an export with quality ``crf`` makes it (None: not one of ours).
    A resumed export (ADR 0081) encodes its remaining segments as the first ones were."""
    makers = {"libx264": x264, "h264_nvenc": nvenc}
    return makers[codec](crf) if codec in makers else None


def gpu_listed() -> bool:
    """Whether this PyAV can name an NVENC encoder (not whether the card has one: opening it tells)."""
    return "h264_nvenc" in av.codecs_available


def candidates(
    encoder: str, crf: int, frames: int, width: int, height: int, farming: bool = False
) -> list[Encoder]:
    """What to try for an export of ``frames`` frames of ``width`` x ``height``, best first; x264 is last.

    ``encoder`` is ``"cpu"`` (x264 only), ``"gpu"`` (NVENC when it can be opened, whatever the size) or
    ``"auto"`` (NVENC when it can, unless the export is too small for it to pay). While render processes
    (``farming``) use the cores, x264 would take them from the frames, so "auto" gives the card the job."""
    if encoder not in ENCODERS:
        raise ValueError(f"encoder must be one of {', '.join(ENCODERS)}, not {encoder!r}")
    cpu = x264(crf)
    if encoder == "cpu" or not gpu_listed() or max(width, height) > NVENC_MAX_SIDE:
        return [cpu]
    if encoder == "auto" and not farming and frames * width * height < GPU_MIN_PIXELS:
        return [cpu]
    return [nvenc(crf), cpu]
