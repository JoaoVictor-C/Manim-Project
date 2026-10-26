"""The easing curve editor (P2b.4)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.engine import adapter
from manim_studio.core.model.schema import Easing
from manim_studio.ui.timeline.curve_editor import CurveDialog, CurveEditor, ease_label, from_widget, to_widget

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("name", sorted(adapter.EASE_BEZIER_FITS))
def test_every_fitted_bezier_follows_its_manim_ease(name: str) -> None:
    """B27: the table must stay within 0.025 of Manim's rate function (rechecked on upgrades)."""
    x1, y1, x2, y2 = adapter.EASE_BEZIER_FITS[name]
    s = np.linspace(0, 1, 41)
    x = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s**2 * x2 + s**3
    y = 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s**2 * y2 + s**3
    rate = adapter.rate_func(Easing(name=name))
    error = max(abs(float(rate(float(xi))) - yi) for xi, yi in zip(x, y, strict=True))
    assert error <= 0.025, f"{name}: {error:.4f}"


def test_named_eases_start_from_their_fit_or_are_refused() -> None:
    assert adapter.ease_as_bezier(Easing(name="smooth")) == adapter.EASE_BEZIER_FITS["smooth"]
    assert adapter.ease_as_bezier(Easing(name=None, bezier=(0.1, 0.2, 0.3, 0.4))) == (0.1, 0.2, 0.3, 0.4)
    for name in ("there_and_back", "ease_out_bounce", "ease_out_elastic", "double_smooth"):
        assert adapter.ease_as_bezier(Easing(name=name)) is None


def test_widget_mapping_round_trips_and_clamps() -> None:
    rect = QRectF(10, 10, 200, 200)
    for x, y in ((0, 0), (1, 1), (0.25, 1.3), (0.7, -0.4)):
        assert from_widget(rect, to_widget(rect, x, y)) == pytest.approx((x, y))
    assert from_widget(rect, QPointF(-50, -50)) == (0.0, 1.5)  # x clamped to 0..1, y to the range


def test_labels() -> None:
    assert ease_label(None) == "Animation default"
    assert ease_label(Easing(name="ease_in_out_sine")) == "ease in out sine"
    assert ease_label(Easing(name=None, bezier=adapter.BEZIER_PRESETS["Overshoot"])) == "Overshoot"
    assert ease_label(Easing(name=None, bezier=(0.1, 0.2, 0.3, 0.4))).startswith("Custom curve")


def drag(widget, a: QPointF, b: QPointF) -> None:
    for kind, pos in (
        (QEvent.Type.MouseButtonPress, a),
        (QEvent.Type.MouseMove, b),
        (QEvent.Type.MouseButtonRelease, b),
    ):
        buttons = (
            Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        )
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        QApplication.sendEvent(
            widget,
            QMouseEvent(
                kind,
                pos,
                QPointF(widget.mapToGlobal(pos.toPoint())),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            ),
        )


def test_dragging_a_handle_makes_a_bezier(qt_app) -> None:
    editor = CurveEditor(Easing(name="smooth"))
    editor.resize(300, 300)
    changes = []
    editor.changed.connect(changes.append)
    p1, _ = editor.handle_positions()
    target = to_widget(editor.plot_rect(), 0.2, 0.0)
    drag(editor, p1, target)
    assert changes and changes[-1].bezier[:2] == pytest.approx((0.2, 0.0), abs=0.01)
    assert changes[-1].bezier[2:] == adapter.EASE_BEZIER_FITS["smooth"][2:]  # the other handle kept


def test_curves_that_are_not_beziers_cannot_be_dragged(qt_app) -> None:
    editor = CurveEditor(Easing(name="there_and_back"))
    editor.resize(300, 300)
    assert not editor.editable
    assert editor.handle_at(QPointF(150, 150)) is None
    dialog = CurveDialog(Easing(name="ease_out_bounce"))
    assert "cannot be edited" in dialog.hint.text()
    dialog._pick(Easing(name=None, bezier=adapter.BEZIER_PRESETS["CSS ease"]))
    assert dialog.editor.editable and "Drag" in dialog.hint.text()
