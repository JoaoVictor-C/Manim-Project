"""B64 - readable Python export of keyframed layers (G3a) rendered by Manim vs the editor.

Exports the G3a test projects (every kind of key, keyed layers with clips, the euler example as
committed, and the 32 built-in presets applied to a square and a text) as readable code, renders
them with ``manim render`` (one process per Manim config) and reports the generation time and the
per-frame mean differences from the editor's own frames (h264 noise is about 0.3-1 level). Also
times the 640x360, 30 fps golden-path case (Pop in on a circle).

Run: ``python benchmarks/bench_keyed_export.py``.
"""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from manim_studio.core import adapter, library  # noqa: E402
from manim_studio.core.python_export import to_python  # noqa: E402
from manim_studio.core.schema import Canvas, Layer, Project, Spec  # noqa: E402
from tests.core import test_python_export_keyed as cases  # noqa: E402


def main() -> None:
    adapter.configure(ROOT / ".cache" / "manim")
    projects = {"Motions": cases.motions(), "Clips": cases.clips(), "Euler": cases.euler()}
    projects |= {f"Preset{i:02d}": cases.preset_project(p) for i, p in enumerate(cases.presets())}
    pop = Project(canvas=Canvas(width_px=640, height_px=360, duration=2.0), layers=[Layer(id="c", spec=Spec(type="Circle"))])
    preset = next(p for p in library.load_library([library.BUILTIN_FOLDER]).presets if p.name == "Pop in")
    projects["PopIn"] = library.apply_preset(pop, "c", preset, 0.5).project
    times, codes = {}, {}
    for name, project in projects.items():
        start = time.perf_counter()
        export = to_python(project, name)
        times[name] = (time.perf_counter() - start) * 1000
        assert export.readable, (name, export.problems)
        codes[name] = export.code
    folder = Path(tempfile.mkdtemp(dir=ROOT / ".cache", prefix="bench-keyed-"))
    start = time.perf_counter()
    videos = cases.render_scenes(codes, folder)
    render = time.perf_counter() - start
    worst = {name: max(cases.frame_differences(p, videos[name])) for name, p in projects.items()}
    for name in ("Motions", "Clips", "Euler", "PopIn"):
        lines = len(codes[name].splitlines())
        print(f"{name:8s} generated in {times[name]:5.1f} ms ({lines} lines); worst per-frame mean diff {worst[name]:.2f}")
    preset_worst = {cases.presets()[int(n[6:])].name: w for n, w in worst.items() if n.startswith("Preset")}
    keyed = ["Pop in", "Pulse", "Drift up", "Bounce", "Spin", "Grow", "Shrink"]
    print(f"presets: worst {max(preset_worst.values()):.2f} ({max(preset_worst, key=preset_worst.get)}), "
          f"keyed presets worst {max(preset_worst[k] for k in keyed):.2f}, "
          f"median generation {statistics.median(times[n] for n in times if n.startswith('Preset')):.1f} ms")
    print(f"manim render of all {len(codes)} scenes: {render:.1f} s; frames compared: "
          f"{sum(len(v) for v in videos.values())}; all below 1.5: {all(np.array(list(worst.values())) < 1.5)}")


if __name__ == "__main__":
    main()
