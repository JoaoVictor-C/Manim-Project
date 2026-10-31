"""What kind of thing a layer is, as the Lumen panels show it (P17.4a): a rounded icon chip in the colour
family of its kind (text, maths, shape, code, Python object, group, sound...) and, for some, a word chip.

The chip's gradient runs between two theme tokens (the clip colours of the timeline and the accent), read
when it is painted, so a theme switch repaints it. The Layers rows and the Properties header share it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, QRectF, QSize
from PySide6.QtGui import QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ... import plugins
from ...core.model.schema import (
    AXES_OBJECTS,
    CAMERA_TYPES,
    CHILD_TYPES,
    CODE_TYPES,
    CONNECTOR_TYPES,
    GROUP_TYPES,
    MEDIA_TYPES,
    NUMBER_TYPES,
    PYTHON_TYPES,
    SHAPE_TYPES,
    TRACE_TYPES,
    Layer,
)
from ..style import icons, theme


@dataclass(frozen=True)
class Kind:
    key: str  # "text", "maths", "shape", ...
    icon: str  # a name in ``icons.NAMES``
    start: str  # theme token at the top left of the chip
    end: str  # theme token at the bottom right ("" for a flat chip)
    chip: str = ""  # a word shown beside the name in the Layers list ("code", "object", "group")


KINDS: dict[str, Kind] = {
    "text": Kind("text", "text", "content", "accent"),
    "maths": Kind("maths", "maths", "content", "accent_2"),
    "shape": Kind("shape", "shape", "motion", "accent_2"),
    "line": Kind("line", "line", "motion", "accent_2"),
    "axes": Kind("axes", "axes", "motion", "content"),
    "plot": Kind("plot", "axes", "motion", ""),  # an object on axes
    "number": Kind("number", "number", "content", "morph"),
    "image": Kind("image", "image", "morph", "content"),
    "code": Kind("code", "code", "emphasis", "sound", "code"),
    "python": Kind("python", "object", "key", "emphasis", "object"),
    "group": Kind("group", "group", "motion", "content", "group"),
    "camera": Kind("camera", "film", "accent", "accent_2", "camera"),
    "trace": Kind("trace", "trace", "emphasis", "key"),
    "simulation": Kind("simulation", "simulation", "morph", "sound"),
    "part": Kind("part", "part", "content", ""),
    "frozen": Kind("frozen", "shape", "morph", "accent"),
    # not layers: what else Properties can show
    "scene": Kind("scene", "scene", "accent", "accent_2"),
    "sound": Kind("sound", "sound", "sound", "emphasis"),
    "subtitle": Kind("subtitle", "text", "cue", "muted"),
    "marker": Kind("marker", "marker", "key", "emphasis"),
    "clip": Kind("clip", "animate", "content", "accent"),
    "keys": Kind("keys", "keyframe", "key", "emphasis"),
}

LINES = frozenset({"Line", "Arrow", "DashedLine", "Vector"}) | CONNECTOR_TYPES


def kind_of(layer: Layer | None) -> Kind:
    """The kind a layer is shown as."""
    if layer is None:
        return KINDS["scene"]
    if layer.is_part:
        return KINDS["part"]
    spec = layer.spec
    kind_type = spec.type if spec is not None else ""
    if kind_type in GROUP_TYPES:
        return KINDS["group"]
    if kind_type in CAMERA_TYPES:
        return KINDS["camera"]
    if kind_type == "Text":
        return KINDS["text"]
    if kind_type in ("MathTex", "Tex"):
        return KINDS["maths"]
    if kind_type in CODE_TYPES:
        return KINDS["code"]
    if kind_type in PYTHON_TYPES:
        return KINDS["python"]
    if kind_type in SHAPE_TYPES:
        return KINDS["frozen"]
    if kind_type in CHILD_TYPES:
        return KINDS["axes"]
    if kind_type in AXES_OBJECTS:
        return KINDS["plot"]
    if kind_type in MEDIA_TYPES:
        return KINDS["image"]
    if kind_type in NUMBER_TYPES:
        return KINDS["number"]
    if kind_type in TRACE_TYPES:
        return KINDS["trace"]
    if kind_type in plugins.SIMULATIONS:
        return KINDS["simulation"]
    if kind_type in LINES:
        return KINDS["line"]
    return KINDS["shape"]


def paint_chip(painter: QPainter, rect: QRectF, kind: Kind, radius: float, enabled: bool = True) -> None:
    """The kind's chip: a rounded square with its gradient and its glyph in white."""
    c = theme.THEME
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    start = theme.qcolor(getattr(c, kind.start))
    if kind.end:
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, start)
        gradient.setColorAt(1.0, theme.qcolor(getattr(c, kind.end)))
        painter.fillPath(path, gradient)
    else:
        painter.fillPath(path, start)
    if not enabled:
        painter.fillPath(path, theme.qcolor(c.panel + "99"))
    side = round(rect.width() * 0.64)
    glyph = QRect(round(rect.center().x() - side / 2), round(rect.center().y() - side / 2), side, side)
    icons.icon(kind.icon, tint="on_accent").paint(painter, glyph)


class KindChip(QWidget):
    """The chip as a widget (the Properties header shows a 32 px one)."""

    def __init__(self, size: int = 32, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = KINDS["scene"]
        self.setFixedSize(size, size)

    def set_kind(self, kind: Kind) -> None:
        if kind != self.kind:
            self.kind = kind
            self.update()

    def sizeHint(self) -> QSize:
        return self.size()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_chip(painter, QRectF(self.rect()), self.kind, 10 if self.width() >= 30 else 7)
        painter.end()
