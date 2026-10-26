"""Getting presets from a link (P12.6): the window with injected network functions, and the importer."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from manim_studio.core.exchange import code_import as ci
from manim_studio.core.exchange.code_import import ImportChoice
from manim_studio.core.exchange.preset_online import OnlineEntry, OnlineError
from manim_studio.ui.exchange import online_presets_dialog as opd
from manim_studio.ui.exchange.online_presets_dialog import OnlinePresetsDialog
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

OBJECT = "PARAMS = {}\n\ndef build(p):\n    return Circle()\n"
SCENE = "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
ENTRIES = [
    OnlineEntry("Wheel", "https://example.com/p/Wheel.py", "object", "A wheel"),
    OnlineEntry("Orbit", "https://example.com/p/Orbit.py", "scene", "A dot"),
]
TEXTS = {ENTRIES[0].url: OBJECT, ENTRIES[1].url: SCENE}


def make(sources=None, resolver=None, fetcher=None) -> OnlinePresetsDialog:
    return OnlinePresetsDialog(
        sources,
        resolver=resolver or (lambda url: ENTRIES),
        fetcher=fetcher or (lambda entry: TEXTS[entry.url]),
        threaded=False,
    )


def test_the_saved_links_round_trip_and_bad_ones_are_dropped() -> None:
    assert opd.load_sources(json.dumps(["https://a", "https://b"])) == ["https://a", "https://b"]
    assert opd.load_sources("not json") == [] and opd.load_sources(json.dumps({"a": 1})) == []
    assert opd.load_sources(json.dumps(["https://a", 3, "", None])) == ["https://a"]
    assert opd.remember(["https://a", "https://b"], "https://b") == ["https://b", "https://a"]
    assert len(opd.remember([str(i) for i in range(50)], "new")) == opd.MAX_SOURCES


def test_finding_lists_the_presets_and_keeps_the_link(qt_app) -> None:
    dialog = make(["https://old"])
    assert dialog.link.count() == 1
    dialog.link.setCurrentText("https://example.com/p")
    dialog.fetch_list()
    assert [e.name for e in dialog.entries] == ["Wheel", "Orbit"] and dialog.list.count() == 2
    assert dialog.sources[0] == "https://example.com/p" and "Found 2" in dialog.status.text()
    assert not dialog.import_button.isEnabled()  # nothing ticked yet


def test_the_first_preset_is_previewed_and_other_rows_load_when_chosen(qt_app) -> None:
    dialog = make()
    dialog.link.setCurrentText("https://example.com/p")
    dialog.fetch_list()
    assert dialog.preview.text() == OBJECT and "A wheel" in dialog.detail.text()
    dialog.list.setCurrentRow(1)
    assert dialog.preview.text() == SCENE


def test_an_empty_link_and_a_failing_link_say_so(qt_app) -> None:
    dialog = make()
    dialog.fetch_list()
    assert "Paste a link" in dialog.status.text()

    def broken(url):
        raise OnlineError("Not found (404)")

    failing = make(resolver=broken)
    failing.link.setCurrentText("https://example.com/none")
    failing.fetch_list()
    assert "404" in failing.status.text() and failing.entries == []


def test_a_preview_that_fails_is_shown_as_a_comment(qt_app) -> None:
    def fetch(entry):
        raise OnlineError("too large")

    dialog = make(fetcher=fetch)
    dialog.link.setCurrentText("https://example.com/p")
    dialog.fetch_list()
    assert "too large" in dialog.preview.text()


def test_downloading_ticked_presets_gives_import_items_with_their_link(qt_app) -> None:
    dialog = make()
    dialog.link.setCurrentText("https://example.com/p")
    dialog.fetch_list()
    dialog.list.item(1).setCheckState(Qt.CheckState.Checked)
    assert dialog.import_button.isEnabled() and [e.name for e in dialog.checked()] == ["Orbit"]
    dialog.download_checked()
    items = dialog.items()
    assert [(i.origin, i.source) for i in items] == [(ENTRIES[1].url, SCENE)]
    assert dialog.result() == dialog.DialogCode.Accepted


def test_forgetting_a_link_removes_it(qt_app) -> None:
    dialog = make(["https://a", "https://b"])
    dialog.link.setCurrentText("https://a")
    dialog.forget()
    assert dialog.sources == ["https://b"] and dialog.link.findText("https://a") == -1


def test_the_threaded_path_delivers_the_list(qt_app) -> None:
    dialog = OnlinePresetsDialog(resolver=lambda url: ENTRIES, fetcher=lambda e: TEXTS[e.url])
    dialog.link.setCurrentText("https://example.com/p")
    dialog.fetch_list()
    for _ in range(300):
        qt_app.processEvents()
        if dialog.entries:
            break
        import time

        time.sleep(0.01)
    assert [e.name for e in dialog.entries] == ["Wheel", "Orbit"]


# -- the importer -----------------------------------------------------------------------------


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1400, 800)
    win.show()
    qt_app.processEvents()
    yield win
    win.close()


def test_online_items_arrive_as_presets_with_their_link(window) -> None:
    from manim_studio.core.exchange.code_import import ImportItem

    window.importer.ask_online = lambda: [ImportItem(OBJECT, ENTRIES[0].url, "Wheel.py")]
    seen = {}

    def ask(items, at, position, **kw):
        seen.update(kw)
        return [ImportChoice(items[0], "Online wheel", ci.PRESET)]

    window.importer.ask = ask
    window.importer.get_online()
    assert seen == {"prefer_preset": True}
    preset = next(p for p in window.code_presets.presets() if p.name == "Online wheel")
    assert (preset.origin, preset.source_url) == ("online", ENTRIES[0].url)


def test_a_folder_of_files_is_offered_as_presets(window, tmp_path) -> None:
    (tmp_path / "Wheel.py").write_text(OBJECT, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    seen = {}

    def ask(items, at, position, **kw):
        seen["origins"] = [i.origin for i in items]
        seen.update(kw)
        return [ImportChoice(items[0], "From folder", ci.PRESET)]

    window.importer.ask = ask
    window.importer.import_folder(tmp_path)
    assert seen == {"origins": ["Wheel.py"], "prefer_preset": True}
    assert any(p.name == "From folder" for p in window.code_presets.presets())


def test_an_empty_folder_says_so(window, tmp_path) -> None:
    assert "No .py files" in window.importer.import_folder(tmp_path)


def test_a_missing_folder_says_so(window, tmp_path) -> None:
    assert "Could not read" in window.importer.import_folder(tmp_path / "nowhere")
