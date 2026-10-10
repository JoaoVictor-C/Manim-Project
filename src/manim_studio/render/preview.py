"""The preview camera, shared by the canvas and the preview render process (ADR 0028).

Both must build exactly the same camera for a cached frame to be the live frame,
bit for bit, so the framing is a value (``PreviewView``) and the camera comes
from one function.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import manim as m
import numpy as np


@dataclass(frozen=True)
class PreviewView:
    """What a preview frame is framed by: device pixels, scene units, centre, background."""

    pixel_width: int
    pixel_height: int
    frame_width: float
    frame_height: float
    centre: tuple[float, float]
    background: str

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> PreviewView:
        return cls(**{**data, "centre": tuple(data["centre"])})


def preview_camera(view: PreviewView) -> m.Camera:
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
