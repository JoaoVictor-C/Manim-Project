"""Cards and chips (Lumen, ADR 0063)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel, QToolButton

from manim_studio.ui.style.card import Card, Chip, Pill

pytestmark = pytest.mark.ui


def test_a_card_shows_an_uppercase_title_and_keeps_the_real_one_for_assistive_tools(qt_app) -> None:
    card = Card("Layers")
    assert card.title_label.text() == "LAYERS" and card.title() == "Layers"
    assert card.title_label.accessibleName() == "Layers"
    seen = []
    card.titleChanged.connect(seen.append)
    card.set_title("Timeline")
    assert card.title_label.text() == "TIMELINE" and seen == ["Timeline"]
    assert card.objectName() == "card"


def test_a_card_holds_one_body_and_header_actions(qt_app) -> None:
    card = Card("Stage")
    body = QLabel("content")
    card.set_body(body)
    button = card.add_action(QToolButton())
    card.add_title_widget(Chip("8"))
    assert card.body() is body and body.parentWidget() is card
    assert button.parentWidget() is card.header
    other = QLabel("other")
    card.set_body(other)
    assert card.body() is other and body.parentWidget() is None
    card.set_body(None)
    assert card.body() is None


def test_a_card_without_a_header_has_no_rule(qt_app) -> None:
    card = Card("x", header=False)
    card.show()
    assert card.header.isHidden() and card.rule.isHidden()
    card.set_header_visible(True)
    assert not card.header.isHidden() and not card.rule.isHidden()


def test_a_clipping_card_masks_its_corners(qt_app) -> None:
    card = Card("Stage", clip=True)
    card.resize(300, 200)
    card.show()
    qt_app.processEvents()
    mask = card.mask()
    assert not mask.isEmpty() and not mask.contains(card.rect().topLeft())
    assert mask.contains(card.rect().center())


def test_a_chip_has_a_tone_the_stylesheet_reads(qt_app) -> None:
    chip = Chip("cached", "ok")
    assert chip.property("chip") is True and chip.property("tone") == "ok"
    chip.set_tone("warn")
    assert chip.property("tone") == "warn"


def test_a_pill_is_a_styled_floating_frame(qt_app) -> None:
    pill = Pill()
    assert pill.objectName() == "pill"
