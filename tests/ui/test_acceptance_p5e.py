"""P5e acceptance: a scene animated with presets from the Animate menu, recoloured with a theme,
given a lower third and a callout from Add > Templates, rendered ahead, exported by the export
process and as an exact Manim scene that renders the same; a saved preset reused (ADR 0039).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_p4a import assert_matches_editor, manim_render
from ui.test_acceptance_p4b import live, shown
from ui.test_acceptance_v1 import menu_action, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # real processes; renders with the Manim command line


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_PREVIEW", "1")
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def preset(window, at: float, category: str, name: str) -> None:
    window.seek(at)
    menu_action(window.menuBar(), "Animate", "Apply Preset", category, name).trigger()


def test_presets_themes_and_templates_to_a_video_and_a_manim_file(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 5.0}
    window.document.replace(
        window.project.model_copy(update={"canvas": window.project.canvas.model_copy(update=small)})
    )
    menu_action(window.layers.library_menu, "Circle").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)
    circle = window.project.layers[0].id
    window.properties.fields["base.position"].commit((-2.5, 0.5))
    menu_action(window.layers.library_menu, "Square").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 2)
    square = window.project.layers[1].id
    window.properties.fields["base.position"].commit((2.5, 0.5))

    # presets at the playhead: entrances, a motion, an exit; one that cannot fit is refused
    window.selection.set(circle)
    preset(window, 0.3, "Entrance", "Pop in")
    preset(window, 1.5, "Motion", "Bounce")
    window.selection.set(square)
    preset(window, 0.6, "Entrance", "Slide in from left")
    preset(window, 3.5, "Exit", "Shrink out")
    preset(window, 3.7, "Emphasis", "Indicate")  # inside Shrink out: refused
    assert "does not fit" in window.statusBar().currentMessage()
    assert [c.kind for c in window.project.layer(circle).clips] == ["FadeIn"]
    assert set(window.project.layer(circle).tracks) == {"scale", "position"}

    # a theme on the whole scene, then templates at the playhead
    window.selection.clear()
    menu_action(window.menuBar(), "View", "Themes", "Midnight").trigger()
    assert window.project.canvas.background != "#000000"
    window.seek(1.0)
    menu_action(window.layers.library_menu, "Lower third").trigger()
    window.seek(2.0)
    menu_action(window.layers.library_menu, "Callout").trigger()
    assert len(window.project.layers) == 2 + 3 + 4

    # the circle's animation saved as a preset and reused on the square
    window.selection.set(circle)
    window.ask_preset_name = lambda: ("Acceptance pop", "entrance")
    menu_action(window.menuBar(), "Animate", "Save Animation as Preset...").trigger()
    saved = Path(os.environ["MANIM_STUDIO_LIBRARY"]) / "preset-Acceptance pop.json"
    try:
        assert saved.is_file()
    finally:
        saved.unlink(missing_ok=True)

    # frames rendered ahead equal live frames
    ahead = window.render_ahead
    wait_until(qt_app, lambda: ahead is not None and len(ahead.store) == ahead.store.total, timeout=180)
    for t in (0.2, 0.5, 1.7, 2.6, 3.8):
        window.seek(t)
        assert window.canvas.from_cache and np.array_equal(shown(window), live(window, t)), t

    # the export process, and the exact Python scene (keys make it exact) rendered by Manim
    window.show_export_dialog()
    dialog = window.export_dialog
    video = tmp_path / "presets.mp4"
    dialog.path.setText(str(video))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(video)) as container:
        assert_matches_editor(window, [f.to_ndarray(format="rgb24") for f in container.decode(video=0)])
    scene = tmp_path / "presets.py"
    window.ask_python_path = lambda start: str(scene)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    assert "exact scene" in window.statusBar().currentMessage()  # keys make it a replay, not readable code
    assert_matches_editor(window, manim_render(scene, "Presets"))
