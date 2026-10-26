"""P4b acceptance: a plugin object, from the plugin folder to a video and a Manim file (ADR 0032).

The example plugin (examples/plugins/pendulum.py) is put in a plugin folder.
In the editor - with its real build worker and preview process, which load
plugins themselves - a pendulum is added from Add > Physics, its angle edited,
given a clip and exported: the video (rendered by the export process) and the
exact Python scene (rendered by ``manim render``) both match the editor.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
from pathlib import Path

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_p4a import assert_matches_editor, manim_render
from acceptance.test_acceptance_v1 import menu_action, timeline_menu, wait_until
from manim_studio import plugins
from manim_studio.render.cairo_export import render_frame
from manim_studio.render.preview import preview_camera
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # real processes; renders with the Manim command line

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "plugins" / "pendulum.py"


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    folder = tmp_path / "plugins"
    folder.mkdir()
    shutil.copy(EXAMPLE, folder)
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(folder))  # helper processes load it from here
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    monkeypatch.setenv("MANIM_STUDIO_PREVIEW", "1")
    plugins.load_plugins()  # this process loaded its plugins (none) at import
    assert plugins.loaded == {str(folder / "pendulum.py"): ["Pendulum"]}, plugins.problems
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()
    plugins.unregister("Pendulum")
    plugins.loaded.clear()


def shown(window) -> np.ndarray:
    image = window.canvas._image
    return np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes()).reshape(
        image.height(), image.width(), 4
    )


def live(window, t: float) -> np.ndarray:
    return render_frame(preview_camera(window.canvas.preview_view()), window.evaluator.frame(t))


def test_a_plugin_object_animates_exports_and_becomes_a_manim_file(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 2.0}
    canvas = window.project.canvas.model_copy(update=small)
    window.document.replace(window.project.model_copy(update={"canvas": canvas}))
    menu_action(window.layers.library_menu, "Pendulum").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)
    pendulum = window.project.layers[0].id
    window.properties.fields["params.angle"].commit(45.0)
    menu_action(timeline_menu(window, pendulum, 0.0), "Add clip", "Appear / disappear", "Create").trigger()
    assert window.evaluator.build_errors() == {}
    assert "Cannot draw" not in window.statusBar().currentMessage()

    # the preview process renders the plugin object too, equal to the live frame
    ahead = window.render_ahead
    wait_until(qt_app, lambda: ahead is not None and len(ahead.store) == ahead.store.total, timeout=120)
    for t in (0.5, 1.5):
        window.seek(t)
        assert window.canvas.from_cache and np.array_equal(shown(window), live(window, t)), t

    # the export process builds it from the plugin folder
    window.show_export_dialog()
    dialog = window.export_dialog
    video = tmp_path / "pendulum.mp4"
    dialog.path.setText(str(video))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=120)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(video)) as container:
        assert_matches_editor(window, [f.to_ndarray(format="rgb24") for f in container.decode(video=0)])

    # and the Python export is the exact scene, rendered with the plugin by `manim render`
    scene = tmp_path / "swing.py"
    window.ask_python_path = lambda start: str(scene)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    assert "a plugin object" in window.statusBar().currentMessage()
    frames = manim_render(scene, "Swing")
    assert_matches_editor(window, frames)
    assert np.abs(frames[-1].astype(int) - frames[0].astype(int)).sum() > 0  # it was drawn on
