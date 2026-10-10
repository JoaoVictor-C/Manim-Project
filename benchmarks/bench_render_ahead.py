"""B41 — render-ahead: what a frame costs to make, to keep and to show again.

Probes for a cache of rendered preview frames, filled while the editor is idle:

1. evaluate + Cairo render per frame at a typical canvas widget size (1100x620)
   on the stress scene and on a heavier scene (the stress scene plus a
   400-path SVG drawn on and two graphs): median, p90, max;
2. keeping a frame: raw RGBA bytes, and zlib at levels 1 and 6 (time, ratio);
3. showing a kept frame: decompress + QImage, vs rendering it again;
4. how many frames fit in a 512 MB budget, raw and compressed.

Run: ``python benchmarks/bench_render_ahead.py``.
"""

from __future__ import annotations

import random
import statistics
import sys
import tempfile
import time
import zlib
from pathlib import Path

import manim as m
import numpy as np
from PySide6.QtGui import QGuiApplication, QImage

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_preview import stress_project  # noqa: E402

from manim_studio.core import adapter  # noqa: E402
from manim_studio.core.evaluator import Evaluator  # noqa: E402
from manim_studio.core.schema import Clip, Layer, Spec, Transform2D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SIZE = (1100, 620)
BUDGET = 512 * 2**20


def heavy_project():
    project = stress_project()
    rng = random.Random(1)
    paths = "".join(
        f'<path d="M{rng.randint(0, 900)} {rng.randint(0, 900)} q {rng.randint(-50, 50)} {rng.randint(-50, 50)} '
        f'{rng.randint(-80, 80)} {rng.randint(-80, 80)} z" fill="#{rng.randint(0, 0xFFFFFF):06x}"/>'
        for _ in range(400)
    )
    folder = Path(tempfile.mkdtemp(dir=ROOT / ".cache", prefix="bench-ahead-"))
    svg = folder / "big.svg"
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">{paths}</svg>', "utf-8")
    extra = [
        Layer(
            id="svg",
            spec=Spec(type="SVGMobject", params={"path": str(svg), "height": 4.0}),
            clips=[Clip(id="d", kind="DrawBorderThenFill", start=0.0, duration=3.0)],
        ),
        Layer(id="axes", spec=Spec(type="Axes"), base=Transform2D(scale=0.6)),
        Layer(id="g1", parent_id="axes", spec=Spec(type="Graph", params={"expression": "sin(3*x)"})),
        Layer(id="g2", parent_id="axes", spec=Spec(type="Graph", params={"expression": "x**2/8 - 2"})),
    ]
    return project.model_copy(update={"layers": [*project.layers, *extra]})


def camera(project) -> m.Camera:
    return m.Camera(
        pixel_width=SIZE[0],
        pixel_height=SIZE[1],
        frame_width=16.0,
        frame_height=16.0 * SIZE[1] / SIZE[0],
        background_color=m.ManimColor(project.canvas.background),
        background_opacity=1.0,
    )


def render(cam: m.Camera, evaluator: Evaluator, t: float) -> np.ndarray:
    cam.reset()
    cam.capture_mobjects(evaluator.frame(t))
    return cam.pixel_array


def stats(samples: list[float]) -> str:
    p90 = sorted(samples)[int(len(samples) * 0.9)]
    return f"median {statistics.median(samples):5.1f} ms, p90 {p90:5.1f}, max {max(samples):5.1f}"


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 - QImage needs an application
    adapter.configure(ROOT / ".cache" / "manim")
    for name, project in (("stress", stress_project()), ("heavy", heavy_project())):
        evaluator = Evaluator(project)
        cam = camera(project)
        times = [i / project.canvas.fps for i in range(int(project.canvas.duration * project.canvas.fps))]
        for t in times:  # checkpoints and active clips are built before timing, as when idle
            evaluator.frame(t)
        costs, frames = [], []
        for t in times:
            start = time.perf_counter()
            frames.append(render(cam, evaluator, t).copy())
            costs.append((time.perf_counter() - start) * 1000)
        print(f"{name}: {len(times)} frames at {SIZE[0]}x{SIZE[1]}: render {stats(costs)}")
        raw = frames[0].nbytes
        for level in (1, 6):
            packed = [zlib.compress(f.tobytes(), level) for f in frames[::10]]
            start = time.perf_counter()
            for f in frames[::10]:
                zlib.compress(f.tobytes(), level)
            pack_ms = (time.perf_counter() - start) * 1000 / len(packed)
            start = time.perf_counter()
            for p in packed:
                data = zlib.decompress(p)
                QImage(data, SIZE[0], SIZE[1], 4 * SIZE[0], QImage.Format.Format_RGBA8888).copy()
            show_ms = (time.perf_counter() - start) * 1000 / len(packed)
            ratio = raw / statistics.mean(len(p) for p in packed)
            per = raw / ratio
            print(
                f"  zlib {level}: compress {pack_ms:5.1f} ms, show (decompress + QImage) {show_ms:4.1f} ms, "
                f"ratio {ratio:5.1f}x -> {per / 2**20:4.2f} MB/frame, {int(BUDGET // per)} frames in 512 MB"
            )
        start = time.perf_counter()
        for f in frames[::10]:
            QImage(f.data, SIZE[0], SIZE[1], 4 * SIZE[0], QImage.Format.Format_RGBA8888).copy()
        show_raw = (time.perf_counter() - start) * 1000 / len(frames[::10])
        print(
            f"  raw: {raw / 2**20:4.2f} MB/frame, show {show_raw:4.1f} ms, {int(BUDGET // raw)} frames in 512 MB"
        )


if __name__ == "__main__":
    main()
