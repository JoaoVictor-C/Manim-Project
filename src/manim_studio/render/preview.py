"""The camera, shared by the canvas, the preview render process and the export (ADR 0028, 0048).

All three must build exactly the same camera for a cached frame to be the live
frame, bit for bit, so the framing is a value (``PreviewView``) and the camera
comes from one function, ``scene_camera``. The project's ``Camera`` (ADR 0048)
picks the kind: the default draws through Manim's 2D ``Camera`` exactly as
before; any other through ``StudioThreeDCamera`` at its angles.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import manim as m
import numpy as np

from ..core.schema import Camera


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


class StudioThreeDCamera(m.ThreeDCamera):
    """Manim's ``ThreeDCamera`` turning about the scene's origin, with ``frame_center`` a pan of the
    picture (ADR 0048).

    Manim's own camera subtracts ``frame_center`` twice - before turning the points and again when
    it maps them to pixels - so a pan would move the picture twice as far and change the angle it
    is seen from. Here the scene turns about its origin, as in a ``ThreeDScene``, and the centre
    only moves the picture, as the 2D camera's does; at the centre (0, 0) - the export - it is
    exactly Manim's camera.
    """

    def project_points(self, points: np.ndarray) -> np.ndarray:
        return super().project_points(points + self.frame_center)


def scene_camera(view: PreviewView, camera: Camera | None = None) -> m.Camera:
    """The camera for ``view``, seen from ``camera`` (None or the default: Manim's 2D camera)."""
    if camera is None or camera.is_default:
        flat = m.Camera(
            pixel_width=view.pixel_width,
            pixel_height=view.pixel_height,
            frame_width=view.frame_width,
            frame_height=view.frame_height,
            background_color=m.ManimColor(view.background),
            background_opacity=1.0,
        )
        flat.frame_center = np.array([view.centre[0], view.centre[1], 0.0])
        return flat
    tilted = StudioThreeDCamera(
        pixel_width=view.pixel_width,
        pixel_height=view.pixel_height,
        frame_width=view.frame_width,
        frame_height=view.frame_height,
        background_color=m.ManimColor(view.background),
        background_opacity=1.0,
    )
    orient(tilted, camera)
    tilted.frame_center = np.array([view.centre[0], view.centre[1], 0.0])
    return tilted


def orient(three_d: m.ThreeDCamera, camera: Camera) -> None:
    """Turn a 3D camera to ``camera``'s angles (degrees, written as a generated file writes them)."""
    three_d.set_phi(camera.phi * m.DEGREES)
    three_d.set_theta(camera.theta * m.DEGREES)
    three_d.set_gamma(camera.gamma * m.DEGREES)
    three_d.reset_rotation_matrix()  # else used stale until the first capture (a code frame before it)


def preview_camera(view: PreviewView, camera: Camera | None = None) -> m.Camera:
    return scene_camera(view, camera)


def keep_in_frame(camera: m.Camera, overlay: Iterable[m.Mobject]) -> None:
    """What is drawn over the scene (burned-in subtitles, ADR 0035) stays flat on the screen when
    the camera is turned: Manim's fixed-in-frame mobjects. Nothing to do for the 2D camera."""
    if isinstance(camera, m.ThreeDCamera):
        camera.fixed_in_frame_mobjects = {member for mob in overlay for member in mob.get_family()}
