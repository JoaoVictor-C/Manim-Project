"""Preferences (P6d.1, ADR 0044): the recent-file rules, the settings file, and the editor
remembering how it was left - recent files, window, panel sizes, view toggles, the last page -
plus the welcome on the empty viewer."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QFileDialog

from acceptance.test_acceptance_v1 import menu_action
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.session import preferences
from manim_studio.ui.session.preferences import MAX_RECENT, Preferences, existing, push_recent

pytestmark = pytest.mark.ui


# -- the recent-file rules (no Qt) ---------------------------------------------------------


def test_push_puts_the_newest_first(tmp_path) -> None:
    a, b = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    items = push_recent(push_recent([], a), b)
    assert items == [str((tmp_path / "b.json").resolve()), str((tmp_path / "a.json").resolve())]


def test_push_moves_a_known_file_to_the_front_without_a_duplicate(tmp_path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    items = push_recent(push_recent(push_recent([], a), b), a)
    assert items == [str(a.resolve()), str(b.resolve())]


def test_push_sees_through_another_spelling_of_the_same_file(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    a = tmp_path / "a.json"
    items = push_recent(push_recent([], a), tmp_path / "sub" / ".." / "a.json")
    assert items == [str(a.resolve())]


def test_push_recognises_a_stored_spelling_of_the_same_file(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    stored = str(tmp_path / "sub" / ".." / "a.json")  # a list written by hand or an older version
    assert push_recent([stored], tmp_path / "a.json") == [str((tmp_path / "a.json").resolve())]


def test_push_keeps_at_most_ten_and_drops_the_oldest(tmp_path) -> None:
    items: list[str] = []
    for i in range(MAX_RECENT + 3):
        items = push_recent(items, tmp_path / f"{i}.json")
    assert MAX_RECENT == 10
    assert len(items) == 10
    assert items[0] == str((tmp_path / "12.json").resolve())
    assert items[-1] == str((tmp_path / "3.json").resolve())


def test_push_honours_a_smaller_limit(tmp_path) -> None:
    items = push_recent([], tmp_path / "a.json", limit=2)
    items = push_recent(items, tmp_path / "b.json", limit=2)
    items = push_recent(items, tmp_path / "c.json", limit=2)
    assert [Path(i).name for i in items] == ["c.json", "b.json"]


def test_existing_drops_missing_files_and_folders_and_keeps_the_order(tmp_path) -> None:
    here, there = tmp_path / "here.json", tmp_path / "there.json"
    here.write_text("{}")
    there.write_text("{}")
    (tmp_path / "folder").mkdir()
    items = [str(there), str(tmp_path / "gone.json"), str(tmp_path / "folder"), str(here)]
    assert existing(items) == [str(there), str(here)]


# -- the settings file ---------------------------------------------------------------------


def test_every_test_starts_from_a_fresh_settings_file(tmp_path) -> None:
    settings = Path(os.environ["MANIM_STUDIO_SETTINGS"])
    assert not settings.exists() or settings.read_text(encoding="utf-8").strip() == ""
    prefs = Preferences()
    assert prefs.path == settings
    assert prefs.recent() == [] and prefs.last_page() is None and prefs.window() == (None, None)


def test_the_settings_path_is_the_environment_one_unless_given(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MANIM_STUDIO_SETTINGS", str(tmp_path / "env.ini"))
    assert Preferences().path == tmp_path / "env.ini"
    assert Preferences(tmp_path / "given.ini").path == tmp_path / "given.ini"


def test_the_default_settings_file_is_in_the_user_config_folder(monkeypatch) -> None:
    monkeypatch.delenv("MANIM_STUDIO_SETTINGS")
    assert preferences.default_path().name == "manim-studio.ini"


def test_recent_files_survive_a_new_instance_and_missing_ones_are_dropped(tmp_path) -> None:
    ini = tmp_path / "p.ini"
    files = [tmp_path / n for n in ("a.json", "b.json", "c.json")]
    for f in files:
        f.write_text("{}")
    prefs = Preferences(ini)
    for f in files:
        prefs.add_recent(f)
    assert Preferences(ini).recent() == [f.resolve() for f in reversed(files)]
    files[1].unlink()
    assert Preferences(ini).recent() == [files[2].resolve(), files[0].resolve()]


def test_a_vanished_file_does_not_take_a_place_from_the_ten(tmp_path) -> None:
    prefs = Preferences(tmp_path / "p.ini")
    files = [tmp_path / f"{i}.json" for i in range(MAX_RECENT + 1)]
    for f in files:
        f.write_text("{}")
    for f in files[:MAX_RECENT]:
        prefs.add_recent(f)
    files[4].unlink()
    prefs.add_recent(files[MAX_RECENT])
    assert len(prefs.recent()) == MAX_RECENT  # the new one and the nine still there


def test_clear_recent_empties_the_list(tmp_path) -> None:
    f = tmp_path / "a.json"
    f.write_text("{}")
    prefs = Preferences(tmp_path / "p.ini")
    prefs.add_recent(f)
    prefs.clear_recent()
    assert prefs.recent() == [] and Preferences(tmp_path / "p.ini").recent() == []


def test_the_window_pages_toggles_and_last_page_round_trip(tmp_path) -> None:
    ini = tmp_path / "p.ini"
    prefs = Preferences(ini)
    assert prefs.toggle("snap", True) is True and prefs.toggle("half", False) is False
    prefs.set_toggle("snap", False)
    prefs.set_toggle("half", True)
    prefs.set_last_page("audio")
    prefs.save_window(QByteArray(b"geometry"), QByteArray(b"state"))
    prefs.set_page_sizes("compose", [QByteArray(b"one"), None, QByteArray(b"three")])
    again = Preferences(ini)
    assert again.toggle("snap", True) is False and again.toggle("half", False) is True
    assert again.last_page() == "audio"
    geometry, state = again.window()
    assert bytes(geometry) == b"geometry" and bytes(state) == b"state"
    sizes = again.page_sizes("compose")
    assert [None if s is None else bytes(s) for s in sizes] == [b"one", None, b"three"]
    assert again.page_sizes("animate") == []


def test_page_sizes_replace_the_older_ones(tmp_path) -> None:
    prefs = Preferences(tmp_path / "p.ini")
    prefs.set_page_sizes("compose", [QByteArray(b"a"), QByteArray(b"b"), QByteArray(b"c")])
    prefs.set_page_sizes("compose", [QByteArray(b"z")])
    assert [bytes(s) for s in Preferences(tmp_path / "p.ini").page_sizes("compose")] == [b"z"]


# -- the editor ------------------------------------------------------------------------------


def write_project(folder: Path, name: str = "scene.json", layers: int = 1) -> Path:
    project = Project(
        canvas=Canvas(width_px=320, height_px=180),
        layers=[Layer(id=f"c{i}", spec=Spec(type="Circle")) for i in range(layers)],
    )
    path = folder / name
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    return path


def start(qt_app, width: int = 1200, height: int = 800) -> MainWindow:
    win = MainWindow()
    win.resize(width, height)
    win.show()
    qt_app.processEvents()
    return win


def recent_texts(win: MainWindow) -> list[str]:
    win.open_recent_menu.aboutToShow.emit()
    return [a.text() for a in win.open_recent_menu.actions() if a.data()]


def test_a_fresh_start_is_todays_defaults(qt_app) -> None:
    win = start(qt_app)
    try:
        assert win.page == "compose"
        assert win.snap_action.isChecked() and win.move_tool.snapping
        assert not win.half_action.isChecked() and not win.canvas.half_resolution
        assert win.render_ahead_action.isChecked()
        assert not win.open_recent_menu.menuAction().isEnabled()
        assert win.welcome.isVisible() and not win.canvas.isVisible()
        assert win.welcome.recent_links == [] and not win.welcome.recent_heading.isVisible()
    finally:
        win.close()


def test_the_welcome_goes_when_a_project_opens(qt_app, tmp_path) -> None:
    win = start(qt_app)
    try:
        win.load(write_project(tmp_path))
        qt_app.processEvents()
        assert not win.welcome.isVisible() and win.canvas.isVisible()
    finally:
        win.close()


def test_a_new_project_also_removes_the_welcome(qt_app) -> None:
    win = start(qt_app)
    try:
        win.welcome.new_button.click()
        assert win.project is not None and not win.welcome.isVisible()
    finally:
        win.close()


def test_the_welcome_opens_the_example_as_an_untitled_project(qt_app) -> None:
    win = start(qt_app)
    try:
        assert win.welcome.example_button.isVisible()
        win.welcome.example_button.click()
        assert win.project is not None and len(win.project.layers) > 3
        assert win.path is None and win.document.undo_stack.isClean()
        assert not win.welcome.isVisible()
        assert win.recent_paths() == []  # the example is not a recent file
    finally:
        win.close()


def test_opening_the_example_over_a_saved_project_makes_it_untitled(qt_app, tmp_path) -> None:
    win = start(qt_app)
    try:
        win.load(write_project(tmp_path))
        menu_action(win.menuBar(), "File", "Open Example").trigger()
        assert win.path is None and len(win.project.layers) > 3
        assert [p.name for p in win.recent_paths()] == ["scene.json"]
    finally:
        win.close()


def test_the_welcome_open_button_asks_for_a_file(qt_app, tmp_path, monkeypatch) -> None:
    path = write_project(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    win = start(qt_app)
    try:
        win.welcome.open_button.click()
        assert win.path == path
    finally:
        win.close()


def test_opening_a_file_records_it_and_the_next_start_lists_it(qt_app, tmp_path) -> None:
    path = write_project(tmp_path)
    win = start(qt_app)
    win.load(path)
    assert win.recent_paths() == [path.resolve()]
    win.close()

    again = start(qt_app)
    try:
        assert again.open_recent_menu.menuAction().isEnabled()
        assert recent_texts(again) == [path.name]
        assert [b.text() for b in again.welcome.recent_links] == [path.name]
        assert again.welcome.recent_links[0].toolTip() == str(path.resolve())
    finally:
        again.close()


def test_open_recent_opens_that_file(qt_app, tmp_path) -> None:
    first, second = write_project(tmp_path, "first.json"), write_project(tmp_path, "second.json", layers=2)
    win = start(qt_app)
    win.load(first)
    win.load(second)
    win.close()

    again = start(qt_app)
    try:
        assert recent_texts(again) == ["second.json", "first.json"]  # newest first
        menu_action(again.menuBar(), "File", "Open Recent", "first.json").trigger()
        assert again.path == first.resolve() and len(again.project.layers) == 1
        assert recent_texts(again) == ["first.json", "second.json"]  # and it moved to the front
    finally:
        again.close()


def test_a_welcome_link_opens_that_file(qt_app, tmp_path) -> None:
    path = write_project(tmp_path)
    win = start(qt_app)
    win.load(path)
    win.close()
    again = start(qt_app)
    try:
        again.welcome.recent_links[0].click()
        assert again.path == path.resolve() and not again.welcome.isVisible()
    finally:
        again.close()


def test_each_welcome_link_opens_its_own_file(qt_app, tmp_path) -> None:
    first, second = write_project(tmp_path, "first.json"), write_project(tmp_path, "second.json", layers=2)
    win = start(qt_app)
    win.load(first)
    win.load(second)
    win.close()
    again = start(qt_app)
    try:
        assert [b.text() for b in again.welcome.recent_links] == ["second.json", "first.json"]
        assert again.welcome.recent_heading.isVisible()
        again.welcome.recent_links[0].click()
        assert again.path == second.resolve()
        again.welcome.recent_links[1].click()  # the list was rebuilt, in the same order
        assert again.path == first.resolve()
    finally:
        again.close()


def test_a_recent_file_that_vanished_is_dropped_not_opened(qt_app, tmp_path) -> None:
    path = write_project(tmp_path)
    keep = write_project(tmp_path, "keep.json")
    win = start(qt_app)
    win.load(path)
    win.load(keep)
    win.close()
    path.unlink()
    again = start(qt_app)
    try:
        assert recent_texts(again) == ["keep.json"]  # dropped on read
        assert [b.text() for b in again.welcome.recent_links] == ["keep.json"]
        again.open_recent(path)  # a stale menu entry clicked after the file went
        assert again.project is None
        assert "no longer exists" in again.statusBar().currentMessage()
    finally:
        again.close()
    stale = start(qt_app)
    try:
        stale.load(keep)
        stale.new_project()
        keep.unlink()
        stale.open_recent(keep)  # the window was started while it was there
        assert stale.welcome.recent_links == []
        assert not stale.open_recent_menu.menuAction().isEnabled()
    finally:
        stale.close()


def test_save_as_records_the_file(qt_app, tmp_path, monkeypatch) -> None:
    target = tmp_path / "saved.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    win = start(qt_app)
    try:
        win.new_project()
        win.save_as()
        assert target.exists() and win.recent_paths() == [target.resolve()]
    finally:
        win.close()


def test_save_records_an_opened_file_again(qt_app, tmp_path) -> None:
    a, b = write_project(tmp_path, "a.json"), write_project(tmp_path, "b.json")
    win = start(qt_app)
    try:
        win.load(a)
        win.load(b)
        win.load(a)
        win.load(b)
        win.path = a
        win.save()
        assert win.recent_paths() == [a.resolve(), b.resolve()]
    finally:
        win.close()


def test_clear_recent_empties_the_menu_the_welcome_and_the_file(qt_app, tmp_path) -> None:
    path = write_project(tmp_path)
    win = start(qt_app)
    try:
        win.load(path)
        win.open_recent_menu.aboutToShow.emit()
        menu_action(win.menuBar(), "File", "Open Recent", "Clear Recent").trigger()
        assert win.recent_paths() == [] and not win.open_recent_menu.menuAction().isEnabled()
        assert win.welcome.recent_links == []
    finally:
        win.close()
    assert Preferences().recent() == []


def test_a_menu_with_nothing_recent_says_so(qt_app) -> None:
    win = start(qt_app)
    try:
        win.open_recent_menu.aboutToShow.emit()
        actions = win.open_recent_menu.actions()
        assert actions[0].text() == "No recent files" and not actions[0].isEnabled()
        assert not menu_action(win.open_recent_menu, "Clear Recent").isEnabled()
    finally:
        win.close()


def test_the_recent_list_holds_ten(qt_app, tmp_path) -> None:
    win = start(qt_app)
    try:
        paths = [write_project(tmp_path, f"p{i}.json") for i in range(12)]
        for p in paths:
            win.load(p)
        assert len(win.recent_paths()) == 10
        assert win.recent_paths()[0] == paths[-1].resolve()
        assert len(recent_texts(win)) == 10 and len(win.welcome.recent_links) == 10
    finally:
        win.close()


def test_the_window_comes_back_as_it_was_left(qt_app, monkeypatch) -> None:
    # The offscreen screen (800 x 800) is smaller than the window's minimum, so a restored size
    # cannot be told from a default one: the test watches what the window is given back.
    win = start(qt_app)
    win.close()
    geometry, state = Preferences().window()
    assert geometry is not None and state is not None
    given = {}

    def spy(name):
        original = getattr(MainWindow, name)

        def restore(self, data):
            given[name] = bytes(data)
            return original(self, data)

        monkeypatch.setattr(MainWindow, name, restore)

    spy("restoreGeometry")
    spy("restoreState")
    again = MainWindow()
    try:
        assert given == {"restoreGeometry": bytes(geometry), "restoreState": bytes(state)}
    finally:
        again.close()


def test_the_view_toggles_come_back(qt_app, tmp_path) -> None:
    win = start(qt_app)
    win.snap_action.setChecked(False)
    win.half_action.setChecked(True)
    win.render_ahead_action.setChecked(False)
    win.close()
    again = start(qt_app)
    try:
        assert not again.snap_action.isChecked() and again.move_tool.snapping is False
        assert again.half_action.isChecked() and again.canvas.half_resolution is True
        assert not again.render_ahead_action.isChecked()
        again.load(write_project(tmp_path))
        assert again.render_ahead is None  # not started: the toggle was off
    finally:
        again.close()
    # a toggle switched back on is remembered as on
    last = start(qt_app)
    last.snap_action.setChecked(True)
    last.close()
    final = start(qt_app)
    try:
        assert final.snap_action.isChecked() and final.move_tool.snapping
    finally:
        final.close()


def test_the_last_page_returns_when_a_project_opens_not_before(qt_app, tmp_path) -> None:
    path = write_project(tmp_path)
    win = start(qt_app)
    win.load(path)
    win.show_page("audio")
    win.close()
    again = start(qt_app)
    try:
        assert again.page == "compose"  # an empty start shows the first page
        again.load(path)
        assert again.page == "audio"
        again.show_page("compose")
        again.prefs.set_last_page("audio")
        again.load(path)  # a later open does not pull the user back
        assert again.page == "compose"
    finally:
        again.close()


def test_an_unknown_last_page_is_ignored(qt_app, tmp_path) -> None:
    prefs = Preferences()
    prefs.set_last_page("nonesuch")
    win = start(qt_app)
    try:
        win.load(write_project(tmp_path))
        assert win.page == "compose"
    finally:
        win.close()


def test_splitter_sizes_are_kept_per_page(qt_app, tmp_path) -> None:
    path = write_project(tmp_path)
    win = start(qt_app, 1400, 900)
    win.load(path)
    compose = win.pages.pages["compose"]
    compose.outer.setSizes([420, 700, 280])
    win.show_page("animate")
    animate = win.pages.pages["animate"]
    animate.top.setSizes([350, 700, 330])
    qt_app.processEvents()
    animate_right = animate.top.sizes()[1]
    win.show_page("compose")
    qt_app.processEvents()
    left_wide = compose.outer.sizes()[0]
    win.close()

    again = start(qt_app, 1400, 900)
    try:
        again.load(path)  # on Compose: its sizes are back
        qt_app.processEvents()
        sizes = again.pages.pages["compose"].outer.sizes()
        assert abs(sizes[0] - left_wide) <= 20 and sizes[0] > 380
        again.show_page("animate")  # on a page not yet shown this session
        qt_app.processEvents()
        right = again.pages.pages["animate"].top.sizes()[1]
        assert abs(right - animate_right) <= 20 and right > 400
    finally:
        again.close()


def test_sizes_changed_after_the_last_page_switch_are_saved_on_close(qt_app, tmp_path) -> None:
    path = write_project(tmp_path)
    win = start(qt_app, 1400, 900)
    win.load(path)
    win.pages.pages["compose"].outer.setSizes([430, 650, 320])
    qt_app.processEvents()
    kept = win.pages.pages["compose"].outer.sizes()[0]
    win.close()
    again = start(qt_app, 1400, 900)
    try:
        again.load(path)
        qt_app.processEvents()
        assert abs(again.pages.pages["compose"].outer.sizes()[0] - kept) <= 20 and kept > 400
    finally:
        again.close()


def test_every_page_keeps_every_splitter_between_runs(qt_app, tmp_path) -> None:
    """Generic: each page of the host (Deliver included) is saved and restored by the same hook."""
    path = write_project(tmp_path)

    def page_sizes(win) -> dict[str, list[list[int]]]:
        out = {}
        for name in win.pages.pages:
            win.show_page(name)
            qt_app.processEvents()
            out[name] = [s.sizes() for s in win.pages.pages[name].splitters()]
        return out

    win = start(qt_app, 1400, 900)
    win.load(path)
    names = list(win.pages.pages)
    assert len(names) >= 5 and "deliver" in names
    for name in names:  # give every splitter of every page a distinctive first size
        win.show_page(name)
        qt_app.processEvents()
        for splitter in win.pages.pages[name].splitters():
            sizes = splitter.sizes()
            if len(sizes) >= 2 and sizes[0] > 140:
                splitter.setSizes([sizes[0] - 60, sizes[1] + 60, *sizes[2:]])
    left = page_sizes(win)
    win.show_page("compose")
    win.close()
    prefs = Preferences()
    for name in names:
        saved = prefs.page_sizes(name)
        assert saved and all(state is not None for state in saved), name
        assert len(saved) == len(left[name]), name

    again = start(qt_app, 1400, 900)
    try:
        again.load(path)
        back = page_sizes(again)
        for name in names:
            for before, after in zip(left[name], back[name], strict=True):
                assert [abs(a - b) <= 25 for a, b in zip(before, after, strict=True)] == [True] * len(
                    before
                ), (
                    name,
                    before,
                    after,
                )
    finally:
        again.close()


def test_sizes_of_a_page_never_shown_are_kept_for_the_next_start(qt_app, tmp_path) -> None:
    path = write_project(tmp_path)
    win = start(qt_app, 1400, 900)
    win.load(path)
    win.show_page("animate")
    win.pages.pages["animate"].top.setSizes([350, 700, 330])
    win.show_page("compose")
    win.close()
    middle = start(qt_app, 1400, 900)  # animate is never shown in this session
    middle.load(path)
    middle.close()
    last = start(qt_app, 1400, 900)
    try:
        last.load(path)
        last.show_page("animate")
        qt_app.processEvents()
        assert last.pages.pages["animate"].top.sizes()[1] > 400
    finally:
        last.close()


def test_a_page_with_a_new_layout_ignores_sizes_that_no_longer_fit(qt_app, tmp_path) -> None:
    prefs = Preferences()
    prefs.set_page_sizes("compose", [QByteArray(b"not a splitter state")])
    win = start(qt_app)
    try:
        win.load(write_project(tmp_path))
        assert win.pages.pages["compose"].outer.sizes()[0] > 0
    finally:
        win.close()


def test_every_new_action_has_a_tooltip(qt_app) -> None:
    win = start(qt_app)
    try:
        win.open_recent_menu.aboutToShow.emit()
        for path in (("Open Recent",), ("Open Recent", "Clear Recent"), ("Open Example",)):
            assert menu_action(win.menuBar(), "File", *path).toolTip(), path
        assert win.half_action.toolTip()
    finally:
        win.close()


def test_sizes_saved_before_the_current_layout_are_dropped_once(tmp_path) -> None:
    from PySide6.QtCore import QByteArray, QSettings

    path = tmp_path / "old.ini"
    old = QSettings(str(path), QSettings.Format.IniFormat)
    old.setValue("pages/compose/0", QByteArray(b"old"))
    old.setValue("window/state", QByteArray(b"old"))
    old.setValue("window/geometry", QByteArray(b"keep"))
    old.sync()
    prefs = Preferences(path)  # no layout_version in the file: it came from before Lumen
    assert prefs.page_sizes("compose") == []
    assert prefs.window()[1] is None and prefs.window()[0] is not None  # the window's place stays
    prefs.set_page_sizes("compose", [QByteArray(b"new")])
    assert Preferences(path).page_sizes("compose") != []  # sizes saved now are kept on the next start


def test_the_insert_tools_remember_the_recent_objects_and_the_variants(tmp_path) -> None:
    """ADR 0087: the Add object card's Recent row and each insert tool's variant, kept across sessions."""
    path = tmp_path / "insert.ini"
    prefs = Preferences(path)
    assert prefs.insert_recent() == [] and prefs.insert_variants() == {}
    prefs.set_insert_recent([f"obj:T{i}" for i in range(9)])
    prefs.set_insert_variants({"shape": "Star", "line": "Arrow"})
    again = Preferences(path)
    assert again.insert_recent() == [f"obj:T{i}" for i in range(6)]  # at most six
    assert again.insert_variants() == {"shape": "Star", "line": "Arrow"}


def test_unreadable_insert_settings_read_as_nothing_and_never_raise(tmp_path) -> None:
    path = tmp_path / "bad.ini"
    prefs = Preferences(path)
    prefs._settings.setValue("insert/recent", "{not json")
    prefs._settings.setValue("insert/variants", "[1, 2]")
    assert prefs.insert_recent() == [] and prefs.insert_variants() == {}
    prefs._settings.setValue("insert/recent", '["obj:Circle", 3, null]')
    assert prefs.insert_recent() == ["obj:Circle"]
    prefs.set_insert_recent([object()])  # not storable as JSON: ignored, not raised
