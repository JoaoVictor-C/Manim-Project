"""P3f acceptance: a heavy project plays from frames rendered ahead (ADR 0028).

The stress scene of the benchmarks (20 equations, three drawn on, ten moving)
plus a late title, opened in the editor with the real preview process: once its
frames are rendered ahead, playback shows them - equal to the live frames - at a
fraction of a live frame's cost; editing the late title keeps the early frames;
zooming refills the cache for the new view.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import wait_until
from manim_studio.core.model.schema import Clip, Layer, Spec, Transform2D
from manim_studio.render.cairo_export import render_frame
from manim_studio.render.preview import preview_camera
from manim_studio.ui.main_window import MainWindow

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmarks"))
from bench_preview import stress_project

pytestmark = [pytest.mark.ui, pytest.mark.slow, pytest.mark.latex]  # a real process; the scene is LaTeX


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_PREVIEW", "1")
    project = stress_project()
    title = Layer(
        id="title",
        spec=Spec(type="Text", params={"text": "The end"}),
        base=Transform2D(position=(0.0, -3.2)),
        clips=[Clip(id="in", kind="FadeIn", start=3.0, duration=0.5)],
    )
    project = project.model_copy(update={"layers": [*project.layers, title]})
    path = tmp_path / "heavy.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def shown(window) -> np.ndarray:
    image = window.canvas._image
    return np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes()).reshape(
        image.height(), image.width(), 4
    )


def live(window, t: float) -> np.ndarray:
    return render_frame(preview_camera(window.canvas.preview_view()), window.evaluator.frame(t))


def test_a_heavy_project_plays_from_frames_rendered_ahead(window, qt_app) -> None:
    ahead = window.render_ahead
    total = ahead.store.total
    assert total == 120
    wait_until(qt_app, lambda: len(ahead.store) == total, timeout=240)

    # playback: every frame comes from the cache and is the live frame
    fps = window.project.canvas.fps
    costs = []
    for index in range(0, total, 7):
        start = time.perf_counter()
        window.seek(index / fps)
        costs.append((time.perf_counter() - start) * 1000)
        assert window.canvas.from_cache, index
        assert np.array_equal(shown(window), live(window, index / fps)), index
    live_costs = []
    for index in range(0, total, 30):
        start = time.perf_counter()
        live(window, index / fps)
        live_costs.append((time.perf_counter() - start) * 1000)
    print(
        f"cached seek median {statistics.median(costs):.1f} ms, "
        f"live frame {statistics.median(live_costs):.1f} ms"
    )
    assert statistics.median(costs) < statistics.median(live_costs) / 2

    # editing the late title keeps every frame before it
    window.selection.set("title")
    window.properties.fields["params.text"].commit("Fin")
    wait_until(qt_app, lambda: window.project.layer("title").spec.params["text"] == "Fin", timeout=60)
    assert sorted(ahead.store.frames)[:90] == list(range(90))  # 0-3 s untouched
    wait_until(qt_app, lambda: len(ahead.store) == total, timeout=120)
    window.seek(3.6)
    assert window.canvas.from_cache and np.array_equal(shown(window), live(window, 3.6))

    # a new view: refilled for it
    window.canvas.zoom(1.5)
    qt_app.processEvents()
    window.refresh()
    assert len(ahead.store) < total
    wait_until(qt_app, lambda: len(ahead.store) == total, timeout=240)
    window.seek(1.0)
    assert window.canvas.from_cache and np.array_equal(shown(window), live(window, 1.0))
