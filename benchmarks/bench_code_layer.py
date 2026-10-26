"""Code layers planning (B30): rendering user Manim code into a frame cache, and compositing it.

A code layer holds a user's ``construct()`` (updaters, ValueTracker, TracedPath —
what the visual model cannot express). It plays with Manim's own clock, so it
is rendered sequentially, once, into cached frames that the editor composites.

Measures, at 1280x720@30 with a transparent background:

* capturing frames from a real ``Scene.construct`` through a stub file writer
  (no video encode): time per frame;
* storing frames: raw RGBA size, PNG encode/decode per frame and size, and the
  same for a zlib-compressed raw array;
* compositing one cached full frame into the editor's frame: as a full-frame
  ``ImageMobject`` drawn by the Cairo camera, vs. a numpy alpha blend into the
  camera's pixel array between passes.
"""

from __future__ import annotations

import io
import time
import zlib
from pathlib import Path

import manim as m
import numpy as np
from manim.renderer.cairo_renderer import CairoRenderer
from PIL import Image

from manim_studio.core.engine import adapter

adapter.configure(Path(__file__).resolve().parent.parent / ".cache" / "manim")

USER_CODE = """
class Orbit(Scene):
    def construct(self):
        t = ValueTracker(0)
        dot = Dot(color=YELLOW).add_updater(
            lambda d: d.move_to([2 * np.cos(t.get_value()), 2 * np.sin(t.get_value()), 0])
        )
        trace = TracedPath(dot.get_center, stroke_color=YELLOW, stroke_width=4)
        circle = Circle(radius=2, color=BLUE)
        self.add(circle, trace, dot)
        self.play(t.animate.set_value(TAU), run_time=2, rate_func=linear)
        self.wait(1)
"""


class CapturingRenderer(CairoRenderer):
    """Keeps frames instead of handing them to the video writer (``write_to_movie`` is off)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.frames: list[np.ndarray] = []

    def add_frame(self, frame, num_frames: int = 1) -> None:
        if self.skip_animations:
            return
        self.time += num_frames / self.camera.frame_rate
        self.frames.extend([frame] * num_frames)

    def scene_finished(self, scene) -> None:
        pass  # no movie to combine


def render_code(code: str, width: int, height: int, fps: int) -> list[np.ndarray]:
    namespace: dict = {}
    exec("from manim import *\nimport numpy as np\n", namespace)
    provided = set(namespace)
    exec(code, namespace)  # the user's own code
    scene_class = next(
        v
        for k, v in namespace.items()
        if k not in provided and isinstance(v, type) and issubclass(v, m.Scene)
    )
    with m.tempconfig(
        {
            "pixel_width": width,
            "pixel_height": height,
            "frame_rate": fps,
            "background_opacity": 0.0,
            "disable_caching": True,
            "write_to_movie": False,
            "save_last_frame": False,
            "progress_bar": "none",
        }
    ):
        renderer = CapturingRenderer()
        scene = scene_class(renderer=renderer)
        scene.render()
    return renderer.frames


def main() -> None:
    m.logger.setLevel("WARNING")
    w, h, fps = 1280, 720, 30
    t0 = time.perf_counter()
    frames = render_code(USER_CODE, w, h, fps)
    render_s = time.perf_counter() - t0
    first = frames[0]
    print(
        f"captured {len(frames)} frames {first.shape} {first.dtype} in {render_s:.2f} s "
        f"({render_s / len(frames) * 1000:.1f} ms/frame incl. scene setup)"
    )
    alpha = first[..., 3]
    print(
        f"transparent background: alpha min {alpha.min()} max {alpha.max()}, "
        f"opaque fraction {float((alpha > 0).mean()):.3f}"
    )

    sample = frames[len(frames) // 2]
    raw_mb = sample.nbytes / 1e6
    t0 = time.perf_counter()
    for _ in range(10):
        buf = io.BytesIO()
        Image.fromarray(sample, "RGBA").save(buf, format="PNG", compress_level=1)
    png_enc = (time.perf_counter() - t0) * 100
    png = buf.getvalue()
    t0 = time.perf_counter()
    for _ in range(10):
        np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
    png_dec = (time.perf_counter() - t0) * 100
    t0 = time.perf_counter()
    for _ in range(10):
        z = zlib.compress(sample.tobytes(), 1)
    z_enc = (time.perf_counter() - t0) * 100
    t0 = time.perf_counter()
    for _ in range(10):
        np.frombuffer(zlib.decompress(z), np.uint8).reshape(sample.shape)
    z_dec = (time.perf_counter() - t0) * 100
    print(
        f"per frame: raw {raw_mb:.1f} MB; "
        f"PNG(level 1) {len(png) / 1e3:.0f} kB enc {png_enc:.1f} ms dec {png_dec:.1f} ms; "
        f"zlib(1) {len(z) / 1e3:.0f} kB enc {z_enc:.1f} ms dec {z_dec:.1f} ms"
    )

    camera = m.Camera(
        pixel_width=w,
        pixel_height=h,
        frame_width=8 * w / h,
        frame_height=8.0,
        background_color=m.ManimColor("#000000"),
        background_opacity=1.0,
    )
    others = [m.Square(side_length=3).set_fill(m.BLUE, 0.5), m.MathTex(r"e^{i\pi}+1=0").shift(m.UP * 3)]
    image = m.ImageMobject(sample)
    image.height = 8.0
    t0 = time.perf_counter()
    for _ in range(10):
        camera.reset()
        camera.capture_mobjects([others[0], image, others[1]])
    image_ms = (time.perf_counter() - t0) * 100
    t0 = time.perf_counter()
    for _ in range(10):
        camera.reset()
        camera.capture_mobjects([others[0]])
        px = camera.pixel_array
        a = sample[..., 3:4].astype(np.float32) / 255.0
        px[..., :3] = (sample[..., :3] * a + px[..., :3] * (1 - a)).astype(np.uint8)
        camera.capture_mobjects([others[1]])
    blend_ms = (time.perf_counter() - t0) * 100
    t0 = time.perf_counter()
    for _ in range(10):
        camera.reset()
        camera.capture_mobjects(others)
    none_ms = (time.perf_counter() - t0) * 100
    print(
        f"composite per frame: without code layer {none_ms:.1f} ms; ImageMobject {image_ms:.1f} ms; "
        f"numpy blend between passes {blend_ms:.1f} ms"
    )

    t0 = time.perf_counter()
    for _ in range(10):
        camera.reset()
        camera.capture_mobjects([others[0]])
        camera.capture_mobjects([others[1]])
    two_pass_ms = (time.perf_counter() - t0) * 100
    ys, xs = np.nonzero(sample[..., 3])
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = np.ascontiguousarray(sample[y0:y1, x0:x1])  # stored cropped, with its offset
    t0 = time.perf_counter()
    for _ in range(10):
        camera.reset()
        camera.capture_mobjects([others[0]])
        region = camera.pixel_array[y0:y1, x0:x1, :3]
        a = crop[..., 3:4].astype(np.uint16)
        region[...] = ((crop[..., :3] * a + region * (255 - a)) // 255).astype(np.uint8)
        camera.capture_mobjects([others[1]])
    crop_ms = (time.perf_counter() - t0) * 100
    print(
        f"two capture passes, no blend {two_pass_ms:.1f} ms; cropped integer blend between passes "
        f"{crop_ms:.1f} ms (crop {x1 - x0}x{y1 - y0} px, {crop.nbytes / 1e3:.0f} kB)"
    )

    # Cairo composites a premultiplied crop (same channel order as the camera) in C.
    import cairo

    alpha = crop[..., 3:4].astype(np.uint16)
    premultiplied = crop.copy()
    premultiplied[..., :3] = (crop[..., :3] * alpha // 255).astype(np.uint8)
    surface = cairo.ImageSurface.create_for_data(
        memoryview(premultiplied), cairo.FORMAT_ARGB32, x1 - x0, y1 - y0
    )
    t0 = time.perf_counter()
    for _ in range(10):
        camera.reset()
        camera.capture_mobjects([others[0]])
        ctx = camera.get_cairo_context(camera.pixel_array)
        ctx.save()
        ctx.identity_matrix()
        ctx.set_source_surface(surface, int(x0), int(y0))
        ctx.paint()
        ctx.restore()
        camera.capture_mobjects([others[1]])
    cairo_ms = (time.perf_counter() - t0) * 100
    camera.reset()
    camera.capture_mobjects([others[0]])
    under = camera.pixel_array[y0:y1, x0:x1, :3].astype(float)
    ctx = camera.get_cairo_context(camera.pixel_array)
    ctx.set_source_surface(surface, 0, 0)
    ctx.identity_matrix()
    ctx.set_source_surface(surface, int(x0), int(y0))
    ctx.paint()
    a = crop[..., 3:4] / 255.0
    error = np.abs(camera.pixel_array[y0:y1, x0:x1, :3] - (crop[..., :3] * a + under * (1 - a))).max()
    print(
        f"cropped premultiplied crop painted by Cairo between passes {cairo_ms:.1f} ms "
        f"(max channel error vs float blend {error:.2f})"
    )


if __name__ == "__main__":
    main()
