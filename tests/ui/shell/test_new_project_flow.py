"""Starting a project like a game engine's hub does (the New project dialog, the file it writes, the welcome's
entrance): templates on the left, name, folder and canvas on the right."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.new_project import NewProjectSettings
from manim_studio.core.model.schema import Project
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.shell import new_project_dialog as dialogs
from manim_studio.ui.shell import welcome
from manim_studio.ui.style import motion, theme

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def back_to_ink(qt_app):
    theme.set_theme(qt_app, "ink")
    yield
    theme.set_theme(qt_app, "ink")


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


# -- the dialog -----------------------------------------------------------------------------------


def test_the_dialog_starts_on_a_blank_scene_with_a_free_name_and_the_canvas_open(qt_app, tmp_path) -> None:
    (tmp_path / "Untitled.json").write_text("{}")
    dialog = dialogs.NewProjectDialog(folder=tmp_path)
    assert dialog.template.key == "blank" and dialog.template_cards["blank"].isChecked()
    assert dialog.name_edit.text() == "Untitled 2"  # the first is taken
    assert dialog.size_box.isEnabled() and dialog.length_box.isEnabled()
    settings = dialog.settings()
    assert (settings.width_px, settings.height_px, settings.fps, settings.duration) == (1280, 720, 30, 5.0)
    assert settings.path == tmp_path / "Untitled 2.json" and dialog.ok_button.isEnabled()


def test_the_canvas_the_dialog_shows_is_the_canvas_it_answers(qt_app, tmp_path) -> None:
    dialog = dialogs.NewProjectDialog(folder=tmp_path)
    dialog.size_box.setCurrentIndex(4)  # vertical
    dialog.fps_box.setCurrentIndex(2)  # 60
    dialog.length_box.setValue(12.0)
    dialog.set_background("#10142a")
    settings = dialog.settings()
    assert (settings.width_px, settings.height_px, settings.fps) == (1080, 1920, 60)
    assert settings.duration == 12.0 and settings.background == "#10142a"
    assert dialog.preview.size_px == (1080, 1920) and dialog.preview.background == "#10142a"
    assert [s.isChecked() for s in dialog.swatches].count(True) == 1


def test_a_template_brings_its_own_canvas_and_locks_the_fields(qt_app, tmp_path) -> None:
    templates = [t for t in dialogs.available_templates() if t.source is not None]
    if not templates:
        pytest.skip("no example projects in this install")
    dialog = dialogs.NewProjectDialog(folder=tmp_path, template=templates[0].key)
    assert dialog.template.key == templates[0].key and dialog.template_cards[templates[0].key].isChecked()
    assert not dialog.size_box.isEnabled() and not dialog.length_box.isEnabled()
    assert not any(swatch.isEnabled() for swatch in dialog.swatches)
    wanted = dialogs.template_canvas(templates[0])
    settings = dialog.settings()
    assert (settings.width_px, settings.height_px, settings.fps) == (
        wanted["width_px"],
        wanted["height_px"],
        wanted["fps"],
    )
    dialog.choose_template("blank")  # back to a scene of your own: editable again
    assert dialog.size_box.isEnabled() and dialog.length_box.isEnabled()


def test_a_name_that_is_taken_or_not_a_file_name_cannot_be_created(qt_app, tmp_path) -> None:
    (tmp_path / "Intro.json").write_text("{}")
    dialog = dialogs.NewProjectDialog(folder=tmp_path)
    dialog.name_edit.setText("Intro")
    assert not dialog.ok_button.isEnabled() and "already exists" in dialog.path_hint.text()
    dialog.name_edit.setText("a/b")
    assert not dialog.ok_button.isEnabled()
    dialog.name_edit.setText("Outro")
    assert dialog.ok_button.isEnabled() and str(tmp_path / "Outro.json") in dialog.path_hint.text()


def test_the_dialog_fits_a_small_screen_in_both_themes(qt_app, tmp_path) -> None:
    for name in ("ink", "paper"):
        theme.set_theme(qt_app, name)
        dialog = dialogs.NewProjectDialog(folder=tmp_path)
        dialog.show()
        qt_app.processEvents()
        assert dialog.height() <= 640 and dialog.width() <= 1024, (name, dialog.size())
        dialog.close()


# -- the window -----------------------------------------------------------------------------------


def test_creating_a_project_writes_its_file_and_opens_it_clean(window, tmp_path, monkeypatch) -> None:
    settings = NewProjectSettings(
        name="Intro", folder=tmp_path / "films", width_px=1920, height_px=1080, fps=60
    )
    monkeypatch.setattr(window, "ask_new_project", lambda remembered, template="blank": settings)
    window.new_project()
    path = tmp_path / "films" / "Intro.json"
    assert path.is_file() and window.path == path
    saved = Project.model_validate_json(path.read_text(encoding="utf-8"))
    assert (saved.canvas.width_px, saved.canvas.fps) == (1920, 60)
    assert window.project.canvas.fps == 60 and window.document.undo_stack.isClean()
    assert window.recent_paths()[0] == path and "Intro" in window.windowTitle()


def test_creating_from_a_template_starts_from_its_project_with_the_chosen_morphs(
    window, tmp_path, monkeypatch
) -> None:
    templates = [t for t in dialogs.available_templates() if t.source is not None]
    if not templates:
        pytest.skip("no example projects in this install")
    source = Project.model_validate_json(templates[0].source.read_text(encoding="utf-8"))
    settings = NewProjectSettings(
        name="Mine", folder=tmp_path, template=templates[0].key, morph_matching="classic"
    )
    monkeypatch.setattr(window, "ask_new_project", lambda remembered, template="blank": settings)
    window.new_project()
    assert len(window.project.layers) == len(source.layers) > 0
    assert window.project.morph_matching == "classic" and (tmp_path / "Mine.json").is_file()


def test_a_folder_that_cannot_be_made_keeps_the_current_project(window, tmp_path, monkeypatch) -> None:
    window.new_project()
    before = window.project
    (tmp_path / "blocker").write_text("a file where the folder should go")
    settings = NewProjectSettings(name="X", folder=tmp_path / "blocker" / "inside")
    monkeypatch.setattr(window, "ask_new_project", lambda remembered, template="blank": settings)
    shown = []
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "critical", lambda *args: shown.append(args[2]))
    window.new_project()
    assert shown and window.project is before and window.path is None


def test_the_welcomes_template_cards_ask_for_that_template(window, monkeypatch) -> None:
    asked = []
    monkeypatch.setattr(
        window,
        "ask_new_project",
        lambda remembered, template="blank": asked.append(template) or None,
    )
    window.welcome._example.click()
    window.welcome.new_button.click()
    assert asked == ["showcase", "blank"]
    offered = [c.text() for c in window.welcome.template_cards]
    assert offered == [t.name for t in dialogs.available_templates() if t.key not in ("blank", "showcase")]


# -- the welcome's entrance -----------------------------------------------------------------------


def test_with_motion_off_the_welcome_is_simply_there(qt_app) -> None:
    panel = welcome.WelcomePanel()
    panel.resize(1200, 800)
    panel.show()
    qt_app.processEvents()
    assert panel.intro == 1.0 and not panel._ticker.isActive() and panel._reveal is None
    panel.close()


def test_with_motion_on_the_curves_draw_themselves_and_the_dot_runs_only_while_shown(
    qt_app, monkeypatch
) -> None:
    monkeypatch.delenv("MANIM_STUDIO_MOTION", raising=False)
    assert motion.enabled()
    panel = welcome.WelcomePanel()
    panel.resize(1200, 800)
    panel.show()
    qt_app.processEvents()
    assert panel._played and panel._ticker.isActive()
    assert panel._reveal is not None and panel.new_button.graphicsEffect() is not None  # fading in
    panel.hide()
    assert not panel._ticker.isActive()  # nothing runs behind a project
    panel.close()


def test_the_picture_slows_down_when_nothing_moves_and_stops_when_the_program_is_not_in_use(
    qt_app, monkeypatch
) -> None:
    from PySide6.QtCore import QPoint, Qt

    monkeypatch.delenv("MANIM_STUDIO_MOTION", raising=False)
    panel = welcome.WelcomePanel()
    panel.resize(1200, 800)
    panel.show()
    qt_app.processEvents()
    panel._intro = 1.0  # the entrance is over
    panel._tick()
    assert panel._ticker.interval() == welcome.LIVELY_MS  # the pointer has only just been seen
    panel._moved_at -= welcome.CALM_AFTER + 1  # ... and then it rests
    panel._tick()
    assert panel._ticker.interval() == welcome.CALM_MS
    panel._mouse = QPoint(-5, -5)  # it moves again
    panel._tick()
    assert panel._ticker.interval() == welcome.LIVELY_MS
    panel._on_application_state(Qt.ApplicationState.ApplicationInactive)  # another program has the focus
    assert not panel._ticker.isActive()
    panel._on_application_state(Qt.ApplicationState.ApplicationActive)
    assert panel._ticker.isActive()
    panel.hide()
    panel._on_application_state(Qt.ApplicationState.ApplicationActive)
    assert not panel._ticker.isActive()  # hidden behind a project: it stays stopped
    panel.close()


def test_a_welcome_left_alone_stops_drawing_until_the_pointer_moves(qt_app, monkeypatch) -> None:
    from PySide6.QtCore import QPoint

    monkeypatch.delenv("MANIM_STUDIO_MOTION", raising=False)
    panel = welcome.WelcomePanel()
    panel.resize(1200, 800)
    panel.show()
    qt_app.processEvents()
    panel._intro = 1.0
    panel._moved_at -= welcome.REST_AFTER + 1
    clock = panel.scene.t
    panel._tick()
    assert panel._ticker.interval() == welcome.REST_MS and panel.scene.t == clock  # no step, no frame
    panel._tick()
    assert panel.scene.t == clock
    panel._mouse = QPoint(-9, -9)  # the pointer moves: it is lively again
    panel._tick()
    assert panel._ticker.interval() == welcome.LIVELY_MS and panel.scene.t > clock
    panel.close()
