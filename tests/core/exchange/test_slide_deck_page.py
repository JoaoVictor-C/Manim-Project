"""The HTML deck's page (ADR 0087): built from a manifest, self-contained, names its files in order."""

from __future__ import annotations

import json
import re

import pytest

from manim_studio.core.exchange.slide_deck import Deck, deck_slide, files_folder, page


def deck(title: str = "Euler", loops: tuple[bool, ...] = (False, True, False), stem: str = "talk") -> Deck:
    folder = files_folder(stem)
    slides = tuple(deck_slide(folder, n, loop, f"stop {n}") for n, loop in enumerate(loops, 1))
    return Deck(title=title, width=320, height=180, slides=slides)


def manifest(html: str) -> list[dict]:
    found = re.search(r'<script id="deck" type="application/json">(.*?)</script>', html, re.S)
    assert found is not None
    return json.loads(found.group(1))["slides"]


def test_files_are_named_per_slide_in_a_sibling_folder() -> None:
    slide = deck_slide(files_folder("talk"), 3, True, "")
    assert (slide.video, slide.end, slide.loop) == (
        "talk_files/slide-03.mp4",
        "talk_files/slide-03-end.png",
        "talk_files/slide-03-loop.mp4",
    )
    assert deck_slide("talk_files", 12, False, "").loop is None
    assert deck_slide("talk_files", 12, False, "").video == "talk_files/slide-12.mp4"


def test_page_lists_the_videos_in_order() -> None:
    slides = manifest(page(deck()))
    assert [s["video"] for s in slides] == [f"talk_files/slide-0{n}.mp4" for n in (1, 2, 3)]
    assert [s["end"] for s in slides] == [f"talk_files/slide-0{n}-end.png" for n in (1, 2, 3)]


def test_only_looping_slides_name_a_loop() -> None:
    slides = manifest(page(deck(loops=(False, True, False))))
    assert [s["loop"] for s in slides] == [None, "talk_files/slide-02-loop.mp4", None]
    assert page(deck(loops=(False, False))).count("-loop.mp4") == 0


def test_title_is_escaped() -> None:
    html = page(deck(title='<b>A & "B"</b></script>'))
    assert "<b>A" not in html
    assert "&lt;b&gt;A &amp; &quot;B&quot;&lt;/b&gt;&lt;/script&gt;" in html
    assert html.count("</script>") == html.count("<script")


def test_file_names_cannot_close_the_script() -> None:
    html = page(deck(stem="x</script><img src=y>"))
    assert html.count("</script>") == html.count("<script")
    slides = manifest(html)  # still the same names once parsed
    assert slides[0]["video"] == "x%3C/script%3E%3Cimg%20src%3Dy%3E_files/slide-01.mp4"


def test_stop_names_cannot_close_the_script() -> None:
    slide = deck_slide("talk_files", 1, False, "a </script><b>x & y</b>")
    html = page(Deck(title="t", width=320, height=180, slides=(slide,)))
    assert html.count("</script>") == html.count("<script")
    assert manifest(html)[0]["stop"] == "a </script><b>x & y</b>"
    # "</script" then a space ends a script element too, with no ">" at all
    spaced = page(Deck(title="t", width=320, height=180, slides=(deck_slide("f", 1, False, "</script x"),)))
    assert "</script x" not in spaced and "</SCRIPT" not in spaced.upper().replace("</SCRIPT>", "")


def test_names_are_url_quoted() -> None:
    slides = manifest(page(deck(stem="my talk #2")))
    assert slides[0]["video"] == "my%20talk%20%232_files/slide-01.mp4"


def test_page_is_self_contained() -> None:
    html = page(deck())
    assert html.startswith("<!DOCTYPE html>")
    assert not re.search(r"https?:|ftp:|[\"'(]//", html, re.I)  # no external URL at all
    assert "<link" not in html and 'src="http' not in html
    assert "<style>" in html and "<script>" in html


def test_cover_says_the_title_and_slide_count() -> None:
    html = page(deck(title="Euler"))
    assert "<title>Euler</title>" in html
    assert "3 slides" in html
    assert "1 slide<" in page(deck(loops=(False,)))


def test_two_videos_and_the_keys() -> None:
    html = page(deck())
    assert html.count("<video") == 2
    for key in ("ArrowRight", "PageDown", "ArrowLeft", "PageUp", "Backspace", "Home", "End", "Enter"):
        assert f'"{key}"' in html
    assert "requestFullscreen" in html


def test_a_deck_needs_a_slide() -> None:
    with pytest.raises(ValueError):
        page(Deck(title="x", width=320, height=180, slides=()))
