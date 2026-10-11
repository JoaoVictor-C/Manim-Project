"""P5a acceptance: subtitles imported from an .srt, edited and styled in the editor, rendered ahead,
burned into the exported video with an .srt beside it, and carried by the exact Python scene
(ADR 0035).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.core import subtitles
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_p4a import assert_matches_editor, manim_render
from ui.test_acceptance_p4b import live, shown
from ui.test_acceptance_v1 import menu_action, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # real processes; renders with the Manim command line

SRT = """1
00:00:00,300 --> 00:00:01,400
Every day we ask: how fast is something changing?

2
00:00:01,600 --> 00:00:02,800
Speed, growth, cooling... all rates of change.
"""


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_PREVIEW", "1")
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_subtitles_from_an_srt_to_a_video_and_a_manim_file(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 3.0}
    window.document.replace(
        window.project.model_copy(update={"canvas": window.project.canvas.model_copy(update=small)})
    )
    menu_action(window.layers.library_menu, "Circle").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)

    source = tmp_path / "talk.srt"
    source.write_text(SRT, encoding="utf-8")
    window.ask_subtitles_path = lambda: str(source)
    menu_action(window.menuBar(), "File", "Import Subtitles...").trigger()
    assert len(window.project.subtitles) == 2

    # edit the second cue and the style in Properties
    window.selection.set_subtitle(window.project.subtitles[1].id)
    window.properties.fields["cue.text"].commit("Speed, growth, cooling...\nall rates of change.")
    window.properties.fields["subtitle_style.colour"].commit("#facc15")
    window.properties.fields["subtitle_style.font_size"].commit(22.0)
    assert window.project.subtitle_style.font_size == 22

    # frames rendered ahead show the edited subtitles, equal to live frames
    ahead = window.render_ahead
    wait_until(qt_app, lambda: ahead is not None and len(ahead.store) == ahead.store.total, timeout=120)
    for t in (0.8, 2.2):
        window.seek(t)
        assert window.canvas.from_cache and np.array_equal(shown(window), live(window, t)), t

    # the export process burns them in and writes the .srt beside the video
    window.show_export_dialog()
    dialog = window.export_dialog
    video = tmp_path / "talk.mp4"
    dialog.path.setText(str(video))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=120)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(video)) as container:
        assert_matches_editor(window, [f.to_ndarray(format="rgb24") for f in container.decode(video=0)])
    assert subtitles.read_srt((tmp_path / "talk.srt").read_text(encoding="utf-8")) == window.project.subtitles

    # the exact Python scene draws them and Manim writes the same .srt
    scene = tmp_path / "talk.py"
    window.ask_python_path = lambda start: str(scene)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    assert "subtitles: burned into the frames" in window.statusBar().currentMessage()
    assert_matches_editor(window, manim_render(scene, "Talk"))
    srt = next((tmp_path / "media").rglob("Talk.srt")).read_text(encoding="utf-8")
    assert subtitles.read_srt(srt) == window.project.subtitles
