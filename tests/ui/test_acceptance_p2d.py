"""P2d acceptance: a code layer end to end through the editor (ADR 0019).

A code layer drawing an updater-driven TracedPath sits under a written equation,
built from the library and edited in Properties, with the real code runner (warm
spares) and the real exporter. Scrubbing in random order shows exactly what
playing in order shows, the export shows exactly what the editor shows, and a
project whose code is not trusted runs nothing at all.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.core.code_frame import CodeFrame
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action, timeline_menu, type_latex, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.latex, pytest.mark.slow]  # starts real processes

TRACE = """class Trace(Scene):
    def construct(self):
        t = ValueTracker(0)
        dot = Dot(color=YELLOW).add_updater(
            lambda d: d.move_to([1.5 * np.cos(t.get_value()), 1.5 * np.sin(2 * t.get_value()) - 1, 0])
        )
        dot.update()
        self.add(TracedPath(dot.get_center, stroke_color=YELLOW, stroke_width=5), dot)
        self.play(t.animate.set_value(TAU), run_time=3, rate_func=linear)
"""


@pytest.fixture
def window(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    monkeypatch.setenv("MANIM_STUDIO_CODE", "1")
    monkeypatch.setenv("MANIM_STUDIO_TRUST_FILE", str(tmp_path / "trusted.json"))
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_a_code_layer_under_an_equation(window, qt_app, tmp_path, monkeypatch) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()

    # 1. an equation that writes itself in
    menu_action(window.layers.library_menu, "MathTex").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)
    eq = window.project.layers[0].id
    type_latex(window, qt_app, r"x(t),\ y(t)")
    menu_action(timeline_menu(window, eq, 0.0), "Add clip", "Appear / disappear", "Write").trigger()

    # 2. a code layer from the library, sent behind the equation, its code edited in Properties
    menu_action(window.layers.library_menu, "Code").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 2)
    code = window.project.layers[1].id
    window.layers.select(code)
    window.layers.shift_selected(-1)
    assert [layer.id for layer in window.project.layers] == [code, eq]
    window.selection.select_layer(code)
    window.properties.fields["params.code"].commit(TRACE)
    assert window.trust.is_trusted(TRACE)
    wait_until(qt_app, lambda: window.properties.code_label.text().startswith("Ready"), timeout=120)
    assert window.properties.code_label.text() == "Ready - 90 frames"

    # 3. scrubbing in any order shows what playing in order shows
    project = window.project
    camera = make_camera(project.canvas)
    times = [i / project.canvas.fps for i in range(0, 120, 3)]
    sequential = {t: render_frame(camera, window.evaluator.frame(t)) for t in times}
    assert isinstance(dict(window.evaluator.frame_layers(2.0))[code], CodeFrame)
    shuffled = times[:]
    random.Random(3).shuffle(shuffled)
    for t in shuffled:
        assert np.array_equal(render_frame(camera, window.evaluator.frame(t)), sequential[t]), t

    # 4. the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p2d.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    all_times = frame_times(project.canvas)
    assert len(frames) == len(all_times)
    for i in (15, 45, 75, 100):
        expected = render_frame(camera, window.evaluator.frame(all_times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, all_times[i]
    trail_early = np.abs(frames[15].astype(int) - frames[0].astype(int)).sum()
    trail_late = np.abs(frames[85].astype(int) - frames[0].astype(int)).sum()
    assert trail_late > trail_early  # the trace grows: frames come from the code's own clock

    # 5. the same project from someone else: its code must not run
    marker = tmp_path / "ran.txt"
    sneaky = TRACE.replace(
        "    def construct(self):\n",
        f"    def construct(self):\n        open(r'{marker}', 'w').write('ran')\n",
    )
    shared = project.model_copy(deep=True)
    shared.layers[0].spec.params["code"] = sneaky
    path = tmp_path / "shared.json"
    path.write_text(shared.model_dump_json(by_alias=True), encoding="utf-8")
    window.close()
    monkeypatch.setenv("MANIM_STUDIO_TRUST_FILE", str(tmp_path / "someone-else.json"))
    other = MainWindow()
    asked = []
    other.ask_trust = lambda names: asked.append(names) or "skip"
    other.show()
    other.load(path)
    try:
        assert asked == [[shared.layers[0].name or shared.layers[0].id]]
        assert other.code.status(code).state == "untrusted" and other.code.spare_count == 0
        assert not isinstance(dict(other.evaluator.frame_layers(2.0))[code], CodeFrame)  # placeholder
        other.show_export_dialog()
        other.export_dialog.path.setText(str(tmp_path / "shared.mp4"))
        other.export_dialog.start()
        wait_until(qt_app, lambda: not other.export_dialog.running, timeout=180)
        assert other.export_dialog.job.trust_code is False
        assert not marker.exists()  # neither the editor nor the export ran it
    finally:
        other.export_dialog.close()
        other.close()
