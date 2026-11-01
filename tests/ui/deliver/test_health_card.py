"""The health card's items and chips (ADR 0066, 0084), and the segment strip of the resume card."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.processes import export_health
from manim_studio.ui.deliver.health_card import HealthCard, HealthItem, health_items
from manim_studio.ui.deliver.queue_view import ProgressRing, ResumeCard, SegmentStrip
from manim_studio.ui.style.chip_button import ChipButton

pytestmark = pytest.mark.ui

PROJECT = Project(canvas=Canvas(width_px=160, height_px=90, fps=10, duration=2.0), layers=[])


def report(*findings: export_health.Finding) -> export_health.Report:
    return export_health.Report(tuple(findings), 20, 0.0)


def by_key(items: list[HealthItem]) -> dict[str, HealthItem]:
    return {item.key: item for item in items}


def test_no_report_is_all_ok_and_nothing_to_open() -> None:
    items = health_items(PROJECT, None)
    assert [i.key for i in items] == ["fonts", "media", "python", "sound"]
    assert all(i.tone == "ok" and not i.actionable for i in items)


def test_slow_code_layers_count_and_lead_to_the_first() -> None:
    slow = export_health.Finding(
        export_health.WARNING,
        "2 code layer(s) must be rendered",
        "a, b",
        75.0,
        kind="code",
        layers=("a", "b"),
    )
    item = by_key(health_items(PROJECT, report(slow)))["python"]
    assert (item.text, item.tone, item.page, item.layer) == ("Python layers 2 slow", "warn", "code", "a")
    assert "1 min 15 s" in item.tip and item.actionable


def test_untrusted_layers_are_not_called_slow() -> None:
    gone = export_health.Finding(
        export_health.WARNING,
        "1 Python object(s) will be drawn as placeholders",
        "p",
        kind="untrusted",
        layers=("p",),
    )
    item = by_key(health_items(PROJECT, report(gone)))["python"]
    assert item.text == "Python layers: 1 not run" and item.page == "code" and item.layer == "p"


def test_text_to_build_is_a_fonts_warning_and_a_missing_compiler_a_bad_one(monkeypatch) -> None:
    from manim_studio.core.engine import adapter

    text = export_health.Finding(
        export_health.INFO, "3 LaTeX object(s)", "slow once", kind="text", layers=("t",)
    )
    monkeypatch.setattr(adapter, "latex_problem", lambda: None)
    item = by_key(health_items(PROJECT, report(text)))["fonts"]
    assert (item.text, item.tone, item.page) == ("Fonts: 1 to build", "warn", "compose")
    monkeypatch.setattr(adapter, "latex_problem", lambda: "LaTeX is not installed")
    item = by_key(health_items(PROJECT, report(text)))["fonts"]
    assert item.tone == "bad" and item.text == "Fonts: LaTeX missing"


def test_a_picture_that_is_not_there_is_missing_media(tmp_path) -> None:
    here = tmp_path / "here.png"
    here.write_bytes(b"x")
    project = Project(
        canvas=PROJECT.canvas,
        layers=[
            Layer(id="ok", spec=Spec(type="ImageMobject", params={"path": str(here)})),
            Layer(id="bad", spec=Spec(type="ImageMobject", params={"path": str(tmp_path / "no.png")})),
        ],
    )
    item = by_key(health_items(project, None))["media"]
    assert (item.text, item.tone, item.page, item.layer) == ("Media: 1 missing", "bad", "compose", "bad")


def test_the_card_emits_only_for_chips_that_are_not_ok(qt_app) -> None:
    card = HealthCard()
    card.show_items(
        [
            HealthItem("fonts", "Fonts ok", "ok"),
            HealthItem("media", "Media: 1 missing", "bad", "tip", "audio", "s1"),
            HealthItem("python", "Python layers ok", "ok", "", "code", "x"),
            HealthItem("sound", "Sound ok", "ok"),
        ]
    )
    asked: list[tuple[str, str]] = []
    card.openRequested.connect(lambda page, layer: asked.append((page, layer)))
    for chip in card.chips.values():
        assert isinstance(chip, ChipButton)
        chip.click()
    assert asked == [("audio", "s1")]
    assert "Click to open" in card.chips["media"].toolTip() and "Click" not in card.chips["fonts"].toolTip()
    assert card.chips["media"].tone() == "bad" and card.chips["python"].tone() == "ok"


def test_the_chips_wrap_when_the_card_is_narrow(qt_app) -> None:
    card = HealthCard()
    card.show_items(health_items(PROJECT, None))
    card.resize(600, 10)
    card.show()
    qt_app.processEvents()
    assert card.chips["sound"].y() == card.chips["fonts"].y()
    card.resize(130, 10)
    qt_app.processEvents()
    assert card.chips["sound"].y() > card.chips["fonts"].y()
    card.close()


def test_the_segment_strip_marks_what_is_done_and_the_next_one(qt_app) -> None:
    strip = SegmentStrip()
    strip.set_segments((True, True, False, False))
    assert strip.next_index() == 2
    strip.set_segments((True, True))
    assert strip.next_index() is None
    strip.resize(200, 10)
    assert not strip.grab().isNull()


def test_the_ring_can_read_6_of_9_and_the_resume_card_shows_a_pending_export(qt_app) -> None:
    ring = ProgressRing(52)
    ring.set_state("running", 6 / 9, "6 of 9")
    assert ring.percent_text() == "6 of 9"
    ring.set_state("running", 0.5)
    assert ring.percent_text() == "50%"
    card = ResumeCard()
    card.show_pending("clip.mp4", (True,) * 6 + (False,) * 3, "clip.export")
    assert card.ring.percent_text() == "6 of 9" and "6 of 9 segments" in card.detail.text()
    asked = []
    card.resumeRequested.connect(lambda: asked.append("resume"))
    card.startOverRequested.connect(lambda: asked.append("fresh"))
    card.resume_button.click()
    card.start_over_button.click()
    assert asked == ["resume", "fresh"]
