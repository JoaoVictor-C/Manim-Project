"""Deliver's "Slide deck (HTML)" destination (ADR 0087): an .html output, the whole scene, a --deck job.

The page is driven through the real main window with the fake ExportJob of the Deliver page's tests; the
real renderer making a deck is exercised by tests/render/test_slide_deck.py and test_export_job.py.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Marker
from manim_studio.render.options import RenderOptions
from manim_studio.ui.deliver.render_queue import RenderQueue
from manim_studio.ui.pages import deliver
from ui.pages import test_deliver_page as base

make_project, page, pick = base.make_project, base.page, base.pick
fake_export, window = base.fake_export, base.window  # the Deliver page's fixtures: a fake ExportJob, a window

pytestmark = pytest.mark.ui

STOPS = [
    Marker(id="a", t=1.0, name="one", slide="stop"),
    Marker(id="b", t=2.5, name="two", slide="stop", loop=0.5),
]


def test_the_deck_is_a_destination_with_an_html_output(window) -> None:
    p = page(window(make_project(markers=STOPS), name="talk"))
    assert "deck" in p.destinations
    assert p.path.text().endswith(os.path.join("out", "talk.mp4"))
    p.choose_destination("deck")
    assert Path(p.path.text()).name == "talk.html"
    assert p.render_button.text() == "Render deck"
    p.choose_destination("web")
    assert Path(p.path.text()).name == "talk.mp4"  # back to a video
    assert p.render_button.text() == "Render video"


def test_a_typed_path_keeps_its_name_and_takes_the_suffix(window) -> None:
    p = page(window(make_project(markers=STOPS)))
    p.path.setText("E:/talks/final.mp4")
    p.choose_destination("deck")
    assert Path(p.path.text()) == Path("E:/talks/final.html")
    p.path.setText("E:/talks/notes.txt")  # not a video or a page: left alone
    p.choose_destination("web")
    assert p.path.text() == "E:/talks/notes.txt"


def test_a_deck_is_the_whole_scene(window) -> None:
    p = page(window(make_project(markers=STOPS)))
    pick(p.range, "times")
    p.start.setValue(1.0)
    p.end.setValue(2.0)
    assert (p.options().start, p.options().end) == (1.0, 2.0)
    p.choose_destination("deck")
    assert not p.range.isEnabled() and not p.start.isEnabled() and not p.end.isEnabled()
    assert (p.options().start, p.options().end) == (0.0, None)
    p.choose_destination("web")
    assert p.range.isEnabled() and p.start.isEnabled()


def test_the_hint_counts_the_slides_or_says_how_to_make_them(window) -> None:
    p = page(window(make_project(markers=STOPS)))
    assert p.deck_hint.isHidden()
    p.choose_destination("deck")
    assert not p.deck_hint.isHidden()
    assert p.deck_hint.text().startswith("3 slides")
    plain = page(window(make_project(markers=[Marker(id="m", t=1.0)]), name="plain"))
    plain.choose_destination("deck")
    assert plain.deck_hint.text() == "No slide stops: the deck has one slide. Mark stops on the ruler."
    plain.choose_destination("hd")
    assert plain.deck_hint.isHidden()


def test_render_deck_queues_a_deck_job_that_runs_with_deck(window, fake_export) -> None:
    p = page(window(make_project(markers=STOPS), name="talk"))
    p.choose_destination("deck")
    p.render_now()
    job = p.queue.jobs[-1]
    assert job.deck and job.output.name == "talk.html"
    assert job.summary == "320x180 10 fps, 3 slides"
    export = fake_export.instances[-1]
    assert export.deck is True and export.output == job.output
    p.choose_destination("web")
    p.add_to_queue()
    assert not p.queue.jobs[-1].deck and p.queue.jobs[-1].output.suffix == ".mp4"


def test_browse_offers_html_for_a_deck(window, monkeypatch) -> None:
    p = page(window(make_project(markers=STOPS)))
    asked = []

    def ask(*args, **_kwargs):
        asked.append(args[-1])
        return ("E:/x/talk.html", "")

    monkeypatch.setattr(deliver.QFileDialog, "getSaveFileName", ask)
    p.choose_destination("deck")
    p._browse()
    p.choose_destination("web")
    p._browse()
    assert asked == ["HTML slide deck (*.html)", "MP4 video (*.mp4)"]


def test_the_queue_writes_a_deck_to_an_html_page() -> None:
    queue = RenderQueue()
    project = make_project(markers=STOPS)
    assert queue.add(project, RenderOptions(), Path("out/talk"), deck=True).output == Path("out/talk.html")
    assert queue.add(project, RenderOptions(), Path("out/talk.mp4"), deck=True).output == Path(
        "out/talk (2).html"
    )
    assert queue.add(project, RenderOptions(), Path("out/talk.html")).output == Path("out/talk.mp4")
    assert queue.output_for(Path("x.HTML"), deck=True) == Path("x.HTML")
