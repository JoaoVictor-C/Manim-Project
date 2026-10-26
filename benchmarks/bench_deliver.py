"""B59 - the Deliver page: what showing it, queueing an export and exporting a range cost.

With the showcase project open at 1400x860 (offscreen):

1. the Python preview: ``to_python`` for the showcase (an exact scene) and for a small readable
   project, and the first ``show_page("deliver")`` (which computes the preview);
2. ``add_to_queue`` (a reference to the project, the options, one row);
3. an export of a 1.5 s range at three sizes through ``export_video``: milliseconds per frame,
   so the cost of 480p / 720p / 1080p presets is known.

Run: ``python benchmarks/bench_deliver.py``.
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for name in ("MANIM_STUDIO_PREVIEW", "MANIM_STUDIO_WORKER", "MANIM_STUDIO_AUDIO", "MANIM_STUDIO_CODE"):
    os.environ.setdefault(name, "0")

from PySide6.QtWidgets import QApplication  # noqa: E402

from manim_studio.core.engine import adapter  # noqa: E402
from manim_studio.core.engine.python_export import to_python  # noqa: E402
from manim_studio.core.model.schema import Canvas, Clip, Layer, Project, Spec  # noqa: E402
from manim_studio.render.cairo_export import export_video  # noqa: E402
from manim_studio.render.options import RenderOptions, preset_sizes  # noqa: E402
from manim_studio.ui.main_window import MainWindow  # noqa: E402
from manim_studio.ui.style import theme  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms"


def timed(fn, repeat: int = 5) -> float:
    runs = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        runs.append(time.perf_counter() - start)
    return statistics.median(runs)


def main() -> None:
    adapter.configure(ROOT / ".cache" / "manim")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    showcase = Project.model_validate_json((ROOT / "examples" / "showcase.json").read_text(encoding="utf-8"))
    code_dir = str(adapter.cache_dir() / "code")
    small = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square", style={"fill": "#3b82f6", "fill_opacity": 1}),
                clips=[Clip(id="c", kind="FadeIn", start=0, duration=1.0)],
            )
        ],
    )
    for label, project in (("showcase", showcase), ("small readable", small)):
        export = to_python(project, "Scene", code_dir)
        cost = timed(lambda p=project: to_python(p, "Scene", code_dir))
        form = "readable" if export.readable else f"exact ({len(export.problems)} reasons)"
        print(f"to_python {label}: {ms(cost)}, {form}, {len(export.code)} characters")

    win = MainWindow()
    win.resize(1400, 860)
    win.show()
    win.load(ROOT / "examples" / "showcase.json")
    page = win.pages.pages["deliver"]
    start = time.perf_counter()
    win.show_page("deliver")
    print(f"first show_page('deliver') with the preview: {ms(time.perf_counter() - start)}")
    flips = []
    for _ in range(10):
        win.show_page("compose")
        start = time.perf_counter()
        win.show_page("deliver")
        flips.append(time.perf_counter() - start)
    print(f"show_page('deliver') again (preview kept): {ms(statistics.median(flips))}")

    def add() -> None:
        page.path.setText(str(ROOT / "out" / "bench.mp4"))
        page.add_to_queue()

    print(f"add_to_queue: {ms(timed(add, 20))}")

    folder = Path(tempfile.mkdtemp(prefix="bench-deliver-"))
    sizes = preset_sizes(showcase.canvas)
    for name in ("480p", "720p", "1080p"):
        width, height = sizes[name]
        options = RenderOptions(width=width, height=height, start=2.0, end=3.5)
        start = time.perf_counter()
        result = export_video(showcase, folder / f"{name}.mp4", options=options)
        took = time.perf_counter() - start
        frames = round(1.5 * showcase.canvas.fps)
        print(
            f"export 1.5 s range at {name} ({width}x{height}): {took:.2f} s, "
            f"{took / frames * 1000:.0f} ms/frame"
        )
        result.path.unlink(missing_ok=True)
    win.ask_stop_export = lambda: "stop"
    win.close()
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
