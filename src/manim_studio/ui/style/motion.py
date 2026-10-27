"""Calm motion (Lumen, ADR 0063): short property animations that explain a change, and nothing else.

Three durations - 90 ms for hover and press, 160 ms for the page indicator and toggles, 220 ms for panels and
toasts - and one easing curve, ease-out. Everything goes through ``animate`` so that *Reduce motion* (a
preference), the environment variable ``MANIM_STUDIO_MOTION=0`` (the tests set it) and an animation that has
nowhere to run all mean the same thing: the property is set at once and no one waits.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPauseAnimation,
    QPropertyAnimation,
    QSequentialAnimationGroup,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

FAST = 90
BASE = 160
SLOW = 220

_reduced = False


def set_reduced(on: bool) -> None:
    """Turn *Reduce motion* on or off (the preference)."""
    global _reduced
    _reduced = bool(on)


def enabled() -> bool:
    """Whether animations run: not when motion is reduced or ``MANIM_STUDIO_MOTION`` is ``0``."""
    return not _reduced and os.environ.get("MANIM_STUDIO_MOTION") != "0"


def curve() -> QEasingCurve:
    easing = QEasingCurve(QEasingCurve.Type.BezierSpline)
    easing.addCubicBezierSegment(_p(0.2, 0.8), _p(0.2, 1.0), _p(1.0, 1.0))
    return easing


def _p(x: float, y: float):
    from PySide6.QtCore import QPointF

    return QPointF(x, y)


def animate(
    target: QObject,
    prop: bytes | str,
    end: Any,
    duration: int = BASE,
    *,
    start: Any = None,
    finished: Callable[[], None] | None = None,
) -> QPropertyAnimation | None:
    """Move ``target``'s Qt property ``prop`` to ``end`` (from ``start``, or from where it is).

    Returns the running animation (keep nothing: it deletes itself), or None when motion is off, in
    which case the value is set at once and ``finished`` is called."""
    name = prop if isinstance(prop, bytes) else prop.encode()
    if not enabled():
        target.setProperty(name.decode(), end)
        if finished is not None:
            finished()
        return None
    animation = QPropertyAnimation(target, name, target)
    animation.setDuration(duration)
    animation.setEasingCurve(curve())
    if start is not None:
        animation.setStartValue(start)
    animation.setEndValue(end)
    if finished is not None:
        animation.finished.connect(finished)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def stagger_in(
    owner: QObject, widgets: list[QWidget], *, step: int = 55, duration: int = 340
) -> QParallelAnimationGroup | None:
    """Fade ``widgets`` in one after the other, ``step`` ms apart (an entrance, used once when a page opens).

    Each widget gets an opacity effect that is removed again when it is done, so nothing keeps paying for it.
    Returns the running group (parented to ``owner``), or None when motion is off, in which case nothing
    changes: the widgets are simply there."""
    if not enabled() or not widgets:
        return None
    group = QParallelAnimationGroup(owner)
    effects: list[QGraphicsOpacityEffect] = []
    for index, widget in enumerate(widgets):
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        effects.append(effect)
        fade = QPropertyAnimation(effect, b"opacity", effect)
        fade.setDuration(duration)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(curve())
        run = QSequentialAnimationGroup(group)
        run.addAnimation(QPauseAnimation(index * step))
        run.addAnimation(fade)
        group.addAnimation(run)

    def done() -> None:
        for widget in widgets:
            with contextlib.suppress(
                RuntimeError
            ):  # the widget went away meanwhile (a list that was rebuilt)
                widget.setGraphicsEffect(None)  # also deletes the effect
        group.deleteLater()

    group.finished.connect(done)
    group.start()
    return group
