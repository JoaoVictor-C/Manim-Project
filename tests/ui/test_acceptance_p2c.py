"""P2c acceptance: the terms of an equation as their own layers, end to end through the UI.

Write an equation, split it into terms, indicate one term, move another with
keyframes, fade a third out, and export — every step through the editor's
panels, timeline menus and canvas, with the real build worker (LaTeX) and the
real renderer. The exported video must show exactly that: checked against
hand-built Manim (the same animations on the same glyphs of a plain equation).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import uuid

import av
import manim as m
import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent

from manim_studio.core import adapter, parts
from manim_studio.core.schema import Spec
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action, timeline_menu, type_latex, wait_until
from ui.test_canvas_tools import drag, mouse, px
from ui.test_part_canvas import glyph

pytestmark = [pytest.mark.ui, pytest.mark.latex]


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_terms_of_an_equation_animate_as_layers(window, qt_app, tmp_path) -> None:
    tag = uuid.uuid4().hex[:4]  # fresh LaTeX, so the worker really builds it
    menu_action(window.menuBar(), "File", "New").trigger()

    # 1. an equation that writes itself in
    menu_action(window.layers.library_menu, "MathTex").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)
    eq = window.project.layers[0].id
    text = rf"a^2 + b^2 = c^2 \;\, \text{{{tag}}}"
    type_latex(window, qt_app, text)
    menu_action(timeline_menu(window, eq, 0.0), "Add clip", "Appear / disappear", "Write").trigger()

    # 2. split it into terms (one undo step, one rebuild in the worker)
    window.layers.select(eq)
    menu_action(window.layers.part_button.menu(), "Split into terms").trigger()
    wait_until(qt_app, lambda: len(window.project.children(eq)) == 3)
    a, b, c = (layer.id for layer in window.project.children(eq))
    assert [window.project.layer(i).part.tex for i in (a, b)] == ["a^2", "b^2"]

    # 3. indicate b^2, fade the c^2 term out (timeline menus on the part rows)
    menu_action(timeline_menu(window, b, 1.5), "Add clip", "Emphasis", "Indicate").trigger()
    menu_action(timeline_menu(window, c, 3.0), "Add clip", "Appear / disappear", "FadeOut").trigger()

    # 4. move a^2 up with keyframes: auto-key, drill into the term, drag it
    menu_action(window.menuBar(), "Edit", "Auto-key").trigger()
    window.seek(2.0)
    grab = glyph(window, a)
    mouse(window, QEvent.Type.MouseButtonPress, px(window, *grab))
    mouse(window, QEvent.Type.MouseButtonRelease, px(window, *grab))
    mouse(window, QEvent.Type.MouseButtonDblClick, px(window, *grab))
    mouse(window, QEvent.Type.MouseButtonRelease, px(window, *grab))
    assert window.selection.layer_id == a
    drag(window, px(window, *grab), px(window, grab[0], grab[1] + 1.0), qt_app)
    track = window.project.layer(a).tracks["position"]
    assert [k.t for k in track] == pytest.approx([0.0, 2.0])
    assert track[-1].value == pytest.approx((0.0, 1.0), abs=0.03)
    assert window.project.layer(eq).base.position == (0.0, 0.0)  # the object itself did not move

    # 5. export, and compare with hand-built Manim
    project = window.project
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p2c.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    times = frame_times(project.canvas)
    assert len(frames) == len(times)

    resolution = parts.resolve(project, eq)
    regions = dict(zip(resolution.order, adapter.part_regions(parts.build_spec(project, eq)), strict=True))
    plain = Spec(type="MathTex", params=project.layer(eq).spec.params)
    camera = make_camera(project.canvas)

    def written() -> m.Mobject:
        mob = adapter.build_mobject(plain)
        anim = adapter.make_animation("Write", mob, None, {})
        anim.begin()
        anim.finish()
        return mob

    def glyphs(mob: m.Mobject, layer_id: str) -> m.VGroup:
        leaves = mob.family_members_with_points()
        return m.VGroup(*(leaves[i] for i in regions[layer_id]))

    def play(mob: m.Mobject, kind: str, alpha: float) -> None:
        anim = adapter.make_animation(kind, mob, None, {})
        anim.begin()
        anim.interpolate(alpha)

    def exported(t: float) -> np.ndarray:
        return frames[min(range(len(times)), key=lambda i: abs(times[i] - t))].astype(int)

    def expect(t: float, mob: m.Mobject) -> None:
        expected = render_frame(camera, [mob])[:, :, :3].astype(int)
        # H.264 + yuv420p chroma subsampling: compare on average, not per pixel.
        assert np.abs(exported(t) - expected).mean() < 3, f"t={t}"

    smooth = adapter.rate_func(track[0].ease)
    indicated = written()
    play(glyphs(indicated, b), "Indicate", 0.5)
    glyphs(indicated, a).shift((0.0, float(track[-1].value[1]) * smooth(2.0 / 2.0), 0.0))
    expect(2.0, indicated)  # Indicate halfway; a^2 at its new key

    fading = written()
    glyphs(fading, a).shift((0.0, float(track[-1].value[1]), 0.0))
    play(glyphs(fading, c), "FadeOut", 0.5)
    expect(3.5, fading)

    gone = written()
    glyphs(gone, a).shift((0.0, float(track[-1].value[1]), 0.0))
    remaining = [i for i in range(len(gone.family_members_with_points())) if i not in regions[c]]
    expect(4.5, m.VGroup(*(gone.family_members_with_points()[i] for i in remaining)))
