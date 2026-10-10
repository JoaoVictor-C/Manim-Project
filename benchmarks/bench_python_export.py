"""B43 — exported Python rendered by Manim vs the editor's frames.

Writes the test suite's rich project (a cluster, a gap, a morph, a path, helper
eases) as readable code and, with a keyframed layer added, as the exact scene;
renders both with ``manim render`` and reports the generation time and the
largest per-frame mean difference from the editor's own frames (h264 noise is
about 0.3-0.5 levels).

Run: ``python benchmarks/bench_python_export.py``.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

import av
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from manim_studio.core import adapter  # noqa: E402
from manim_studio.core.evaluator import Evaluator  # noqa: E402
from manim_studio.core.python_export import to_python  # noqa: E402
from manim_studio.core.schema import Keyframe, Layer, Spec  # noqa: E402
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame  # noqa: E402
from tests.core.test_python_export import rich  # noqa: E402


def render(code: str, scene: str, folder: Path) -> tuple[list[np.ndarray], float]:
    path = folder / f"{scene}.py"
    path.write_text(code, encoding="utf-8")
    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "-m", "manim", "render", str(path), scene, "--media_dir", str(folder / "media")],
        check=True, capture_output=True, cwd=folder,
    )
    seconds = time.perf_counter() - start
    video = next((folder / "media" / "videos").rglob(f"{scene}.mp4"))
    with av.open(str(video)) as container:
        return [f.to_ndarray(format="rgb24") for f in container.decode(video=0)], seconds


def main() -> None:
    adapter.configure(ROOT / ".cache" / "manim")
    readable = rich()
    keyed = readable.model_copy(update={"layers": [
        *readable.layers,
        Layer(id="k", spec=Spec(type="Dot"), tracks={"position": [Keyframe(t=0, value=(-3.0, 0.0)),
                                                                  Keyframe(t=4, value=(3.0, 0.0))]}),
    ]})
    folder = Path(tempfile.mkdtemp(dir=ROOT / ".cache", prefix="bench-python-"))
    for project, scene in ((readable, "Readable"), (keyed, "Exact")):
        start = time.perf_counter()
        export = to_python(project, scene)
        generate = (time.perf_counter() - start) * 1000
        frames, seconds = render(export.code, scene, folder)
        evaluator, camera = Evaluator(project), make_camera(project.canvas)
        worst = max(
            float(np.abs(frames[i].astype(int) - render_frame(camera, evaluator.frame(t))[:, :, :3]).mean())
            for i, t in enumerate(frame_times(project.canvas))
        )
        form = "readable" if export.readable else "exact"
        print(f"{scene:9s} ({form}): generated in {generate:5.1f} ms, {len(export.code.splitlines())} lines; "
              f"manim render {seconds:4.1f} s; worst per-frame mean diff {worst:.2f}")


if __name__ == "__main__":
    main()
