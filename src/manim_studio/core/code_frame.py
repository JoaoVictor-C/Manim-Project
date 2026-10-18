"""A code layer's frame as the evaluator hands it out (ADR 0019).

``CodeFrame`` is a point-less-to-Cairo ``Mobject``: Manim's camera ignores plain
mobjects, so ``render_frame`` paints it itself — the cached premultiplied crop,
mapped from the project's pixel grid into world units by the layer transform,
then into the camera's pixels. Its ``points`` are the crop's four world corners
in ``ImageMobject`` order (UL, UR, DL, DR), so outlines and bounds work as for
images; ``hit`` tests the crop's alpha.
"""

from __future__ import annotations

import cairo
import manim as m
import numpy as np

from .code_cache import Crop
from .schema import Canvas

VISIBLE_ALPHA = 0.02  # as render.hit_test: barely visible pixels do not select


class CodeFrame(m.Mobject):
    def __init__(self, crop: Crop, canvas: Canvas, a: np.ndarray, b: np.ndarray, opacity: float) -> None:
        super().__init__()
        self.crop, self.opacity = crop, opacity
        # crop pixel (u, v) -> world: world = to_world @ [u, v] + offset
        scale = np.diag([canvas.frame_width / canvas.width_px, -canvas.frame_height / canvas.height_px])
        origin = scale @ np.array([crop.x, crop.y], dtype=float) + np.array(
            [-canvas.frame_width / 2, canvas.frame_height / 2]
        )
        self.to_world = a @ scale
        self.offset = a @ origin + b
        h, w = crop.pixels.shape[:2]
        corners = [(0, 0), (w, 0), (0, h), (w, h)]  # UL, UR, DL, DR
        self.points = np.array([[*self.world(u, v), 0.0] for u, v in corners])

    def world(self, u: float, v: float) -> np.ndarray:
        return self.to_world @ np.array([u, v], dtype=float) + self.offset

    def hit(self, point: np.ndarray) -> bool:
        """Is ``point`` (world units) on a visible pixel of the crop?"""
        try:
            u, v = np.linalg.solve(self.to_world, np.asarray(point, dtype=float)[:2] - self.offset)
        except np.linalg.LinAlgError:
            return False
        h, w = self.crop.pixels.shape[:2]
        if not (0 <= u < w and 0 <= v < h):
            return False
        return self.crop.pixels[int(v), int(u), 3] * self.opacity > VISIBLE_ALPHA * 255

    def paint(self, camera: m.Camera) -> None:
        """Composite the crop onto ``camera.pixel_array`` (premultiplied OVER, in C)."""
        pixels = self.crop.pixels
        h, w = pixels.shape[:2]
        surface = cairo.ImageSurface.create_for_data(memoryview(pixels), cairo.FORMAT_ARGB32, w, h, 4 * w)
        to_world, offset = self.to_world, self.offset
        if isinstance(camera, m.ThreeDCamera):  # a turned camera (ADR 0048): the crop as it is seen,
            # through three corners, as Manim draws an image (an affine map: no perspective inside it)
            corners = np.array([[*self.world(u, v), 0.0] for u, v in ((0, 0), (w, 0), (0, h))])
            seen = camera.project_points(corners)[:, :2]
            to_world = np.column_stack([(seen[1] - seen[0]) / w, (seen[2] - seen[0]) / h])
            offset = seen[0]
            if abs(np.linalg.det(to_world)) < 1e-12:  # seen edge on: nothing to paint
                surface.finish()
                return
        # world -> camera pixels
        sx = camera.pixel_width / camera.frame_width
        sy = -camera.pixel_height / camera.frame_height
        cx, cy = camera.frame_center[:2]
        to_px = np.array([[sx, 0.0], [0.0, sy]])
        linear = to_px @ to_world
        shift = to_px @ (offset - np.array([cx, cy])) + np.array(
            [camera.pixel_width / 2, camera.pixel_height / 2]
        )
        ctx = camera.get_cairo_context(camera.pixel_array)
        ctx.save()
        ctx.identity_matrix()
        ctx.transform(
            cairo.Matrix(linear[0, 0], linear[1, 0], linear[0, 1], linear[1, 1], shift[0], shift[1])
        )
        ctx.set_source_surface(surface, 0, 0)
        ctx.get_source().set_filter(cairo.FILTER_GOOD)
        if self.opacity < 1:
            ctx.paint_with_alpha(self.opacity)
        else:
            ctx.paint()
        ctx.restore()
        surface.finish()
