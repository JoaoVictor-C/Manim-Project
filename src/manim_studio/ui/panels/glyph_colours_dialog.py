"""Colour characters... (ADR 0055): colour the glyphs of a Text, MathTex or Tex one by one.

The dialog paints the object's glyphs large, from the paths the editor builds
(``adapter.glyph_outlines``), each in its current colour. Click a glyph to select it, Shift+click
for a range, Ctrl+click to add or remove one, drag a rubber band, Ctrl+A for all, Escape to clear.
A strip of swatches under the preview mirrors the glyphs (their labels, colours and the
selection) and is driven with the arrow keys. The controls colour the selection - or, for
Gradient, Rainbow and Alternate with nothing selected, every glyph. Nothing reaches the document
until OK: the caller applies ``edits.set_glyph_colours`` as one undo step.

Chrome uses the theme's tokens; the glyphs and the background are the document's own colours.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QMouseEvent, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.engine import adapter
from ...core.model import glyph_colours as gc
from ...core.model import parts
from ...core.model.schema import Project
from ..style import theme
from ..style.fields import pick_colour

MARGIN = 24  # px around the glyphs in the preview
SWATCH = 24  # px: one square of the strip
DRAG = 4  # px a press must move to become a rubber band


def part_fills(project: Project, root_id: str) -> dict[int, str]:
    """Glyph index -> the fill of the coloured part that draws it (ADR 0049): a part's own colour
    wins over glyph colours, an inner part's over its parent's."""
    resolution = parts.resolve(project, root_id)
    if not resolution.order:
        return {}
    regions = dict(
        zip(
            resolution.order,
            adapter.part_regions(parts.build_spec(project, root_id, resolution)),
            strict=True,
        )
    )
    out: dict[int, str] = {}
    for layer in project.descendants(root_id):  # parents first
        fill = layer.style.get("fill") if layer.is_part else None
        for index in regions.get(layer.id, ()) if fill else ():
            out[index] = fill
    return out


class _Preview(QWidget):
    """The glyphs, large: click, Shift+click, Ctrl+click, rubber band; the hovered one's label."""

    def __init__(self, dialog: GlyphColoursDialog) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.setMinimumSize(420, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Click a glyph to select it; Shift+click a range; Ctrl+click adds or removes one")
        self.hovered: int | None = None
        self._press: QPointF | None = None
        self._modifiers = Qt.KeyboardModifier.NoModifier
        self.band: QRectF | None = None

    # geometry: the glyphs' paths in Manim units, mapped to the widget (y down)

    def transform(self) -> QTransform:
        bounds = QRectF()
        for path in self.dialog.paths:
            bounds = bounds.united(path.boundingRect())
        if bounds.isEmpty():
            return QTransform()
        room = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        scale = min(room.width() / max(bounds.width(), 1e-6), room.height() / max(bounds.height(), 1e-6))
        transform = QTransform()
        transform.translate(room.center().x(), room.center().y())
        transform.scale(scale, -scale)
        transform.translate(-bounds.center().x(), -bounds.center().y())
        return transform

    def glyph_rect(self, index: int) -> QRectF:
        return self.transform().mapRect(self.dialog.paths[index].boundingRect())

    def glyph_at(self, point: QPointF) -> int | None:
        """The glyph under ``point``: its outline, else the smallest box around it (a dot, a hole)."""
        inverse, ok = self.transform().inverted()
        if not ok:
            return None
        local = inverse.map(point)
        inside = [i for i, path in enumerate(self.dialog.paths) if path.contains(local)]
        if inside:
            return inside[0]
        boxes = [
            i
            for i in range(len(self.dialog.paths))
            if self.glyph_rect(i).adjusted(-2, -2, 2, 2).contains(point)
        ]
        return min(
            boxes, key=lambda i: self.glyph_rect(i).width() * self.glyph_rect(i).height(), default=None
        )

    # painting

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(self.dialog.background))  # the document's background
        transform = self.transform()
        for index, path in enumerate(self.dialog.paths):
            colour = QColor(self.dialog.shown_colour(index))
            colour.setAlphaF(max(self.dialog.opacity(index), 0.15))
            painter.fillPath(transform.map(path), colour)
        for index in sorted(self.dialog.selected):
            painter.setPen(QPen(theme.qcolor(theme.THEME.accent), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.glyph_rect(index).adjusted(-3, -3, 3, 3))
        if self.hovered is not None and self.hovered not in self.dialog.selected:
            painter.setPen(QPen(theme.qcolor(theme.THEME.muted), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self.glyph_rect(self.hovered).adjusted(-3, -3, 3, 3))
        if self.band is not None:
            painter.setPen(QPen(theme.qcolor(theme.THEME.accent), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self.band)
        painter.end()

    # the mouse

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.dialog.paths:
            return
        self.setFocus()
        self._press = event.position()
        self._modifiers = event.modifiers()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self.band is not None or (event.position() - self._press).manhattanLength() > DRAG:
                self.band = QRectF(self._press, event.position()).normalized()
                self.update()
            return
        hovered = self.glyph_at(event.position())
        if hovered != self.hovered:
            self.hovered = hovered
            self.setToolTip(self.dialog.describe(hovered) if hovered is not None else "")
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._press is None or event.button() != Qt.MouseButton.LeftButton:
            return
        adding = bool(self._modifiers & Qt.KeyboardModifier.ControlModifier)
        if self.band is not None:
            band = self.band
            self.band = None
            self.dialog.select_band(
                [i for i in range(len(self.dialog.paths)) if self.glyph_rect(i).intersects(band)], adding
            )
        else:
            index = self.glyph_at(self._press)
            self.dialog.click(index, self._modifiers)
        self._press = None
        self.update()

    def keyPressEvent(self, event) -> None:
        event.ignore()  # Ctrl+A, Escape and the arrows are the dialog's


class _Strip(QWidget):
    """One swatch per glyph (its colour and label), the selection outlined; arrow keys move."""

    def __init__(self, dialog: GlyphColoursDialog) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(
            "The glyphs in order: Left/Right selects the next, Shift+Left/Right extends the selection, "
            "Home/End jump to the ends, Space adds or removes one"
        )

    def sizeHint(self) -> QSize:
        return QSize(max(1, len(self.dialog.paths)) * (SWATCH + 2) + 4, SWATCH + 8)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def swatch(self, index: int) -> QRect:
        return QRect(2 + index * (SWATCH + 2), 4, SWATCH, SWATCH)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        for index in range(len(self.dialog.paths)):
            box = self.swatch(index)
            colour = self.dialog.shown_colour(index)
            painter.fillRect(box, QColor(colour))
            painter.setPen(QColor(theme.readable_on(colour)))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self.dialog.labels[index][:3])
            selected = index in self.dialog.selected
            current = index == self.dialog.current and self.hasFocus()
            pen = QPen(
                theme.qcolor(theme.THEME.accent if selected else theme.THEME.border), 3 if selected else 1
            )
            if current:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(box.adjusted(0, 0, -1, -1))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        index = int((event.position().x() - 2) // (SWATCH + 2))
        if 0 <= index < len(self.dialog.paths) and self.swatch(index).contains(event.position().toPoint()):
            self.dialog.click(index, event.modifiers())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        index = int((event.position().x() - 2) // (SWATCH + 2))
        if 0 <= index < len(self.dialog.paths):
            self.setToolTip(self.dialog.describe(index))

    def keyPressEvent(self, event) -> None:
        n = len(self.dialog.paths)
        if not n:
            event.ignore()
            return
        key, shift = event.key(), bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        current = self.dialog.current if self.dialog.current is not None else -1
        target = {
            Qt.Key.Key_Left: max(0, current - 1),
            Qt.Key.Key_Right: min(n - 1, current + 1),
            Qt.Key.Key_Home: 0,
            Qt.Key.Key_End: n - 1,
        }.get(key)
        if target is not None:
            modifiers = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
            self.dialog.click(target, modifiers)
        elif key == Qt.Key.Key_Space and current >= 0:
            self.dialog.click(current, Qt.KeyboardModifier.ControlModifier)
        else:
            event.ignore()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()


class TwoColoursDialog(QDialog):
    """Two colours, each on its own button: a gradient's ends, or the colours to alternate."""

    def __init__(self, title: str, labels: tuple[str, str], colours: tuple[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)
        self.buttons_ = []
        for label, colour in zip(labels, colours, strict=True):
            button = QPushButton()
            button.setToolTip(f"Choose the {label.lower()} colour")
            button.clicked.connect(lambda _=False, b=button: self._pick(b))
            self._show(button, colour)
            form.addRow(f"{label}:", button)
            self.buttons_.append(button)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def _pick(self, button: QPushButton) -> None:
        colour = pick_colour(self, button.property("colour"))
        if colour is not None:
            self._show(button, colour)

    @staticmethod
    def _show(button: QPushButton, colour: str) -> None:
        button.setProperty("colour", colour)
        button.setText(colour)
        button.setStyleSheet(f"background: {colour}; color: {theme.readable_on(colour)};")

    def colours(self) -> tuple[str, str]:
        first, second = (b.property("colour") for b in self.buttons_)
        return first, second


def _ask_two(parent: QWidget, title: str, labels: tuple[str, str], colours: tuple[str, str]):
    dialog = TwoColoursDialog(title, labels, colours, parent)
    return dialog.colours() if dialog.exec() == QDialog.DialogCode.Accepted else None


class GlyphColoursDialog(QDialog):
    changed = Signal()  # the colours or the selection changed (the preview repaints)

    def __init__(self, project: Project, layer_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Colour characters")
        layer = project.layer(layer_id)
        self.layer_id = layer_id
        self.background = project.canvas.background
        # Hooks for tests and other front-ends.
        self.ask_colour: Callable[[str | None], str | None] = lambda current: pick_colour(self, current)
        self.ask_two_colours: Callable[[str, tuple[str, str], tuple[str, str]], tuple[str, str] | None] = (
            lambda title, labels, colours: _ask_two(self, title, labels, colours)
        )
        self.paths: list[QPainterPath] = []
        self.normal: list[str] = []
        self.opacities: list[float] = []
        self.labels: list[str] = []
        self.parts: dict[int, str] = {}
        self.problem: str | None = None
        try:
            spec = parts.build_spec(project, layer_id)
            outlines = adapter.glyph_outlines(spec)
            self.labels = adapter.glyph_labels(spec)
            self.parts = part_fills(project, layer_id)
        except Exception as exc:  # no LaTeX, or a formula LaTeX refuses: the object is a placeholder
            self.problem = adapter.latex_problem() or adapter.build_failure(exc)
            outlines = []
        for outline in outlines:
            self.paths.append(_path(outline.subpaths))
            self.normal.append(outline.fill)
            self.opacities.append(outline.opacity)
        self.colours: gc.Colours = gc.resolved(layer.spec.params.get(gc.PARAM), len(self.paths))
        self.selected: set[int] = set()
        self.anchor: int | None = None
        self.current: int | None = None

        self.preview = _Preview(self)
        self.strip = _Strip(self)
        strip_area = QScrollArea()
        strip_area.setWidget(self.strip)
        strip_area.setWidgetResizable(False)
        strip_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        strip_area.setFixedHeight(SWATCH + 8 + strip_area.horizontalScrollBar().sizeHint().height())
        strip_area.setToolTip(self.strip.toolTip())
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setToolTip("How many glyphs the object draws and how many are selected")

        self.colour_button = self._button(
            "Colour...", self.colour_selection, "Choose a colour for the selected glyphs"
        )
        self.clear_button = self._button(
            "Clear", self.clear_selection, "The selected glyphs go back to the object's own colour"
        )
        self.gradient_button = self._button(
            "Gradient...",
            self.gradient,
            "A gradient from a start colour to an end colour across the selected glyphs (all of them "
            "when none is selected)",
        )
        self.rainbow_button = self._button(
            "Rainbow", self.rainbow, "The colours of the rainbow across the selected glyphs (or all)"
        )
        self.alternate_button = self._button(
            "Alternate...", self.alternate, "Two colours in turn across the selected glyphs (or all)"
        )
        self.reset_button = self._button(
            "Reset all", self.reset_all, "Every glyph back to the object's colour"
        )
        controls = QHBoxLayout()
        for button in (
            self.colour_button,
            self.clear_button,
            self.gradient_button,
            self.rainbow_button,
            self.alternate_button,
            self.reset_button,
        ):
            controls.addWidget(button)
        controls.addStretch(1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setToolTip("Apply the colours (one undo step)")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
            "Close without changing anything"
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        hint = QLabel(
            "Click a glyph to select it, Shift+click a range, Ctrl+click to add or remove one, drag a "
            "box around several; Ctrl+A selects all, Escape clears the selection."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.preview, 1)
        layout.addWidget(strip_area)
        layout.addLayout(controls)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self.changed.connect(self._refresh)
        if self.problem is not None:
            for widget in (self.preview, self.strip, *self._controls()):
                widget.setEnabled(False)
            self.ok_button.setEnabled(False)
        self._refresh()
        self.resize(720, 460)

    # -- building ---------------------------------------------------------------------------------

    def _button(self, text: str, slot: Callable[[], None], tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setAutoDefault(False)
        button.clicked.connect(slot)
        return button

    def _controls(self) -> list[QPushButton]:
        return [
            self.colour_button,
            self.clear_button,
            self.gradient_button,
            self.rainbow_button,
            self.alternate_button,
            self.reset_button,
        ]

    # -- what is shown ----------------------------------------------------------------------------

    def shown_colour(self, index: int) -> str:
        """The colour a glyph draws with: its part's, else its own glyph colour, else the object's."""
        return self.parts.get(index) or self.colours[index] or self.normal[index]

    def opacity(self, index: int) -> float:
        return self.opacities[index]

    def describe(self, index: int) -> str:
        label = self.labels[index] if index < len(self.labels) else str(index + 1)
        own = self.colours[index] or "the object's colour"
        text = f"Glyph {index + 1}: {label} - {own}"
        if index in self.parts:
            text += f" (its part's colour {self.parts[index]} wins)"
        return text

    def _refresh(self) -> None:
        self.preview.update()
        self.strip.update()
        if self.problem is not None:
            self.status.setText(
                f"Cannot colour the characters here: {self.problem}. The object is drawn as a placeholder."
            )
            self.status.setStyleSheet(f"color: {theme.css(theme.THEME.error_text)};")
            return
        n, chosen = len(self.paths), len(self.selected)
        text = f"{n} glyph{'s' * (n != 1)}, {chosen} selected."
        if self.parts:
            text += " Glyphs of a coloured part keep their part's colour."
        self.status.setText(text)
        has_selection = bool(self.selected)
        self.colour_button.setEnabled(has_selection)
        self.clear_button.setEnabled(has_selection)
        for button in (self.gradient_button, self.rainbow_button, self.alternate_button, self.reset_button):
            button.setEnabled(n > 0)

    # -- selection --------------------------------------------------------------------------------

    def click(self, index: int | None, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
        """A click on glyph ``index`` (None: on nothing), as a list selects: Shift for a range from
        the last clicked glyph, Ctrl to add or remove one."""
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if index is None:
            if not ctrl:
                self.selected = set()
            self.changed.emit()
            return
        if shift and self.anchor is not None:
            low, high = sorted((self.anchor, index))
            span = set(range(low, high + 1))
            self.selected = (self.selected | span) if ctrl else span
        elif ctrl:
            self.selected ^= {index}
            self.anchor = index
        else:
            self.selected = {index}
            self.anchor = index
        self.current = index
        self.changed.emit()

    def select_band(self, indices: Sequence[int], adding: bool = False) -> None:
        self.selected = (self.selected | set(indices)) if adding else set(indices)
        if indices:
            self.anchor = self.current = min(indices)
        self.changed.emit()

    def select_all(self) -> None:
        self.selected = set(range(len(self.paths)))
        self.changed.emit()

    def clear_choice(self) -> None:
        self.selected = set()
        self.changed.emit()

    def keyPressEvent(self, event) -> None:
        if self.problem is None and event.matches(QKeySequence.StandardKey.SelectAll):
            self.select_all()
            return
        if event.key() == Qt.Key.Key_Escape and self.selected:
            self.clear_choice()  # a second Escape closes the dialog
            return
        super().keyPressEvent(event)

    def _targets(self) -> list[int]:
        """The selected glyphs in order, else every glyph."""
        return sorted(self.selected) if self.selected else list(range(len(self.paths)))

    # -- colouring --------------------------------------------------------------------------------

    def _set(self, indices: Sequence[int], values: Sequence[str | None]) -> None:
        self.colours = gc.resolved(gc.assign(self.colours, indices, values), len(self.paths))
        self.changed.emit()

    def colour_selection(self) -> None:
        if not self.selected:
            return
        first = sorted(self.selected)[0]
        colour = self.ask_colour(self.colours[first] or self.normal[first])
        if colour is not None:
            indices = sorted(self.selected)
            self._set(indices, [colour] * len(indices))

    def clear_selection(self) -> None:
        indices = sorted(self.selected)
        self._set(indices, [None] * len(indices))

    def gradient(self) -> None:
        answer = self.ask_two_colours("Gradient", ("Start", "End"), (gc.GRADIENT_START, gc.GRADIENT_END))
        if answer is not None:
            indices = self._targets()
            self._set(indices, gc.gradient(list(answer), len(indices)))

    def rainbow(self) -> None:
        indices = self._targets()
        self._set(indices, gc.rainbow(len(indices)))

    def alternate(self) -> None:
        answer = self.ask_two_colours(
            "Alternate", ("First", "Second"), (gc.ALTERNATE_FIRST, gc.ALTERNATE_SECOND)
        )
        if answer is not None:
            indices = self._targets()
            self._set(indices, gc.alternate(len(indices), list(answer)))

    def reset_all(self) -> None:
        self.colours = [None] * len(self.paths)
        self.changed.emit()

    # -- the answer -------------------------------------------------------------------------------

    def result_colours(self) -> gc.Colours:
        return list(self.colours)


def _path(subpaths) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for points in subpaths:
        p = [QPointF(float(x), float(y)) for x, y in points]
        path.moveTo(p[0])
        for k in range(0, len(p) - 3, 4):  # anchor, handle, handle, anchor
            path.cubicTo(p[k + 1], p[k + 2], p[k + 3])
        path.closeSubpath()
    return path


def ask_glyph_colours(parent: QWidget, project: Project, layer_id: str) -> gc.Colours | None:
    """Show the dialog; the new colours on OK, None on Cancel."""
    dialog = GlyphColoursDialog(project, layer_id, parent)
    return dialog.result_colours() if dialog.exec() == QDialog.DialogCode.Accepted else None
