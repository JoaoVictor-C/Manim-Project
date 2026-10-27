"""File > New: starting a project the way a game engine's hub does (ADR 0056, amended; Lumen, ADR 0063).

Left, the starting points as cards - a blank scene and the example scenes that ship with the editor. Right,
what the project will be: a live preview of the frame, its name and the folder it is saved in, and for a blank
scene its canvas (size, frame rate, length, background). A template brings its own canvas, shown but not
editable. Last, the one question the dialog always asked: how should the Transform clips you add match their
pieces? **Smart** (the default) gives cleaner in-between frames; **Classic** is Manim's own Transform, so the
project's Python export stays readable code. It can be changed later in Properties (Scene > New morphs).

The dialog only collects ``NewProjectSettings`` (``core.model.new_project``); the window makes the project
and the file. The project is written to ``<folder>/<name>.json`` when it is created, so it is in the recent
list at once.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.model import new_project as rules
from ...core.model.new_project import NewProjectSettings
from ..session import places
from ..style import theme
from ..style.dialog_chrome import DialogFrame, OptionCard
from ..style.elided_label import ElidedLabel
from .welcome import EXAMPLE, paint_thumbnail

SMART = "smart"
CLASSIC = "classic"
BLACK = rules.BACKGROUNDS[0][1]  # the document's own default background, not an interface colour
EXAMPLES = EXAMPLE.parent  # examples/ beside src/ in a checkout; an installed copy has none


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    description: str
    source: Path | None = None  # the project file it starts from (None: a blank scene)


TEMPLATES: tuple[Template, ...] = (
    Template("blank", "Blank scene", "An empty canvas. You choose its size, speed and length."),
    Template(
        "showcase",
        "Showcase",
        "One 10 s scene using most features: parts, morphs, keys on a curve and a code layer.",
        EXAMPLES / "showcase.json",
    ),
    Template(
        "euler",
        "Euler's identity",
        "A title, the formula written, indicated and transformed: a small scene to read.",
        EXAMPLES / "euler.json",
    ),
    Template(
        "graphs",
        "Function graphs",
        "Axes and function graphs: Create, a graph morph, poles of tan(x), a dot along a path.",
        EXAMPLES / "graphs.json",
    ),
)


def available_templates() -> list[Template]:
    """The blank scene, then the example scenes whose files are present."""
    return [t for t in TEMPLATES if t.source is None or t.source.is_file()]


def template_by_key(key: str) -> Template:
    for template in available_templates():
        if template.key == key:
            return template
    return TEMPLATES[0]


def template_canvas(template: Template) -> dict:
    """A template's canvas as the fields the dialog shows (the defaults when its file is unreadable)."""
    fallback = {"width_px": 1280, "height_px": 720, "fps": 30, "duration": 5.0, "background": BLACK}
    if template.source is None:
        return fallback
    try:
        data = json.loads(template.source.read_text(encoding="utf-8"))["canvas"]
    except (OSError, ValueError, KeyError, TypeError):
        return fallback
    return {key: data.get(key, value) for key, value in fallback.items()}


CARD_SIZE = QSize(176, 108)  # a template card; also the stylesheet's minimum for it


def _rules(c: theme.Colours) -> str:
    return f"""
QLineEdit#projectField, QComboBox#projectField, QDoubleSpinBox#projectField {{ min-height: 30px; }}
QLabel[role="formLabel"] {{ color: {c.muted}; font-size: 11px; font-weight: 600; }}
QToolButton#swatch {{ padding: 0px; border: 0; background: transparent; min-width: 26px; min-height: 26px; }}
QToolButton#swatchMore {{ padding: 0px; min-width: 26px; min-height: 26px; }}
QPushButton#templateCard {{
    padding: 0px; border: 0; background: transparent;
    min-width: {CARD_SIZE.width()}px; min-height: {CARD_SIZE.height()}px;
}}
"""


theme.register_rules(_rules)


# -- widgets --------------------------------------------------------------------------------------


class TemplateCard(QPushButton):
    """A starting point: its picture over a name, with the accent edge when chosen."""

    SIZE = CARD_SIZE

    def __init__(self, template: Template) -> None:
        super().__init__(template.name)
        self.template = template
        self.setObjectName("templateCard")  # the stylesheet keeps its minimum size at the fixed one
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(template.description)
        self.setFixedSize(self.SIZE)
        self.setAccessibleName(template.name)

    def sizeHint(self) -> QSize:
        return self.SIZE

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        chosen, hovered = self.isChecked(), self.underMouse() or self.hasFocus()
        painter.setBrush(theme.qcolor(c.accent_soft if chosen else c.field))
        edge = c.accent_line if chosen else (c.line_strong if hovered else c.line)
        painter.setPen(QPen(theme.qcolor(edge), 1.5 if chosen else 1))
        painter.drawRoundedRect(rect, 12, 12)
        thumb = QRectF(rect.left() + 8, rect.top() + 8, rect.width() - 16, 54)
        paint_thumbnail(painter, thumb, self.template.name if self.template.source else 4, 8.0)
        font = theme.font("label")
        font.setPixelSize(13)
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(theme.qcolor(c.text))
        text = painter.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, int(rect.width() - 20)
        )
        painter.drawText(
            QRectF(rect.left() + 10, thumb.bottom() + 4, rect.width() - 20, 34),
            Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        painter.end()


class FramePreview(QWidget):
    """The project's frame to scale (its aspect ratio, its background) with a curve in it, and its numbers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.size_px, self.fps, self.seconds, self.background = (1280, 720), 30, 5.0, BLACK

    def show_canvas(self, size: tuple[int, int], fps: int, seconds: float, background: str) -> None:
        self.size_px, self.fps, self.seconds, self.background = size, fps, seconds, background
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(c.window))
        painter.drawRoundedRect(area, 12, 12)
        room = area.adjusted(14, 12, -14, -30)
        width, height = self.size_px
        scale = min(room.width() / width, room.height() / height)
        frame = QRectF(0, 0, width * scale, height * scale)
        frame.moveCenter(room.center())
        colour = QColor(self.background)
        light = colour.lightnessF() > 0.55
        painter.setPen(QPen(theme.qcolor(c.line_strong), 1))
        painter.setBrush(colour)
        painter.drawRoundedRect(frame, 5, 5)
        clip = QPainterPath()
        clip.addRoundedRect(frame, 5, 5)
        painter.setClipPath(clip)
        # content: the lines drawn over the document's own background colour, not an interface colour
        ink = QColor(40, 44, 60, 110) if light else QColor(255, 255, 255, 40)  # content
        painter.setPen(QPen(ink, 1))
        painter.drawLine(frame.left(), frame.center().y(), frame.right(), frame.center().y())
        painter.drawLine(frame.center().x(), frame.top(), frame.center().x(), frame.bottom())
        curve = QPainterPath()
        w, h, x0, y0 = frame.width(), frame.height(), frame.left(), frame.top()
        curve.moveTo(x0 + w * 0.08, y0 + h * 0.5)
        curve.cubicTo(x0 + w * 0.2, y0 + h * 0.5, x0 + w * 0.26, y0 + h * 0.2, x0 + w * 0.4, y0 + h * 0.2)
        curve.cubicTo(x0 + w * 0.54, y0 + h * 0.2, x0 + w * 0.58, y0 + h * 0.8, x0 + w * 0.72, y0 + h * 0.8)
        curve.cubicTo(x0 + w * 0.84, y0 + h * 0.8, x0 + w * 0.86, y0 + h * 0.5, x0 + w * 0.92, y0 + h * 0.5)
        painter.setPen(
            QPen(theme.qcolor(c.accent), max(1.5, h / 40), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(curve)
        painter.setClipping(False)
        painter.setFont(theme.font("caption", kind="mono"))
        painter.setPen(theme.qcolor(c.muted))
        label = f"{width} x {height}  -  {self.fps} fps  -  {self.seconds:g} s"
        painter.drawText(
            QRectF(area.left(), area.bottom() - 22, area.width(), 18), Qt.AlignmentFlag.AlignCenter, label
        )
        painter.end()


class _SmallButton(QToolButton):
    """A 26 px square button: the stylesheet's padding must not make its hint larger than that."""

    def sizeHint(self) -> QSize:
        return QSize(26, 26)

    def minimumSizeHint(self) -> QSize:
        return QSize(26, 26)


class Swatch(_SmallButton):
    """A background colour to pick: a round chip with the accent ring when chosen."""

    def __init__(self, name: str, colour: str) -> None:
        super().__init__()
        self.colour = colour
        self.setObjectName("swatch")
        self.setCheckable(True)
        self.setToolTip(f"{name}  {colour}")
        self.setAccessibleName(name)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        painter.setPen(QPen(theme.qcolor(c.line_strong), 1))
        painter.setBrush(QColor(self.colour))
        painter.drawEllipse(box)
        if self.isChecked() or self.underMouse():
            painter.setPen(QPen(theme.qcolor(c.accent if self.isChecked() else c.line_strong), 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8))
        painter.end()


# -- the dialog -----------------------------------------------------------------------------------


class NewProjectDialog(QDialog):
    def __init__(
        self,
        remembered: str = SMART,
        parent: QWidget | None = None,
        *,
        folder: Path | None = None,
        template: str = "blank",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.setMinimumWidth(820)
        self.frame = DialogFrame(
            self, "add", "New project", "Choose a starting point, then name it and say where it is saved."
        )
        self._background = BLACK
        self._locked = False

        self.frame.body.setContentsMargins(22, 12, 22, 12)
        body = QHBoxLayout()
        body.setSpacing(22)
        self.frame.body.addLayout(body)

        # -- the starting points
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self._label("START FROM", eyebrow=True))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.template_group = QButtonGroup(self)
        self.template_cards: dict[str, TemplateCard] = {}
        for index, entry in enumerate(available_templates()):
            card = TemplateCard(entry)
            self.template_group.addButton(card)
            self.template_cards[entry.key] = card
            grid.addWidget(card, index // 2, index % 2)
            card.clicked.connect(lambda _=False, key=entry.key: self.choose_template(key))
        left.addLayout(grid)
        left.addSpacing(6)
        self.preview = FramePreview()
        left.addWidget(self.preview)
        self.template_title = QLabel()
        self.template_title.setProperty("role", "dialogTitle")
        self.template_note = QLabel()
        self.template_note.setProperty("role", "muted")
        self.template_note.setWordWrap(True)
        self.template_note.setFixedHeight(36)  # two lines: a wrapping label would size the dialog too small
        self.template_note.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        left.addWidget(self.template_title)
        left.addWidget(self.template_note)
        left.addStretch(1)
        body.addLayout(left)

        # -- what the project is
        right = QVBoxLayout()
        right.setSpacing(10)
        self.name_edit = self._line("Project name")
        right.addLayout(self._labelled("NAME", self.name_edit))
        self.folder_edit = self._line("Folder")
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse)
        where = QHBoxLayout()
        where.setSpacing(8)
        where.addWidget(self.folder_edit, 1)
        where.addWidget(self.browse_button)
        right.addLayout(self._labelled("LOCATION", where))
        self.path_hint = ElidedLabel(minimum=120)
        self.path_hint.setProperty("role", "hint")
        right.addWidget(self.path_hint)

        self.size_box = self._combo([label for label, _, _ in rules.SIZES])
        self.fps_box = self._combo([f"{fps} fps" for fps in rules.FRAME_RATES])
        self.fps_box.setCurrentIndex(rules.FRAME_RATES.index(30))
        self.length_box = QDoubleSpinBox()
        self.length_box.setObjectName("projectField")
        self.length_box.setRange(rules.MIN_SECONDS, rules.MAX_SECONDS)
        self.length_box.setDecimals(1)
        self.length_box.setSuffix(" s")
        self.length_box.setValue(5.0)
        self.swatches: list[Swatch] = []
        colours = QHBoxLayout()
        colours.setSpacing(2)
        for name, colour in rules.BACKGROUNDS:
            swatch = Swatch(name, colour)
            swatch.clicked.connect(lambda _=False, value=colour: self.set_background(value))
            self.swatches.append(swatch)
            colours.addWidget(swatch)
        self.custom_colour = _SmallButton()
        self.custom_colour.setText("...")
        self.custom_colour.setObjectName("swatchMore")
        self.custom_colour.setToolTip("Another background colour")
        self.custom_colour.setFixedSize(26, 26)
        self.custom_colour.clicked.connect(self.pick_colour)
        colours.addWidget(self.custom_colour)
        colours.addStretch(1)
        canvas = QGridLayout()
        canvas.setHorizontalSpacing(12)
        canvas.setVerticalSpacing(8)
        canvas.addLayout(self._labelled("SIZE", self.size_box), 0, 0)
        canvas.addLayout(self._labelled("SPEED", self.fps_box), 0, 1)
        canvas.addLayout(self._labelled("LENGTH", self.length_box), 1, 0)
        canvas.addLayout(self._labelled("BACKGROUND", colours), 1, 1)
        right.addLayout(canvas)

        self.smart_button = QRadioButton("Smart (recommended)")
        self.smart_button.setToolTip(
            "Pieces are paired by place and shape, holes with holes, and outlines start where they "
            "travel least: fewer twisted or tangled frames.\n"
            "The project's Python export is then an exact replay of the editor, not readable code."
        )
        self.classic_button = QRadioButton("Classic")
        self.classic_button.setToolTip(
            "Manim's own Transform: pieces and points paired in order.\n"
            "The project's Python export stays plain, readable Manim code."
        )
        self.group = QButtonGroup(self)  # the radios sit in different cards, so they need a group
        self.group.addButton(self.smart_button)
        self.group.addButton(self.classic_button)
        self.smart_card = OptionCard(self.smart_button, "Cleaner frames.")
        self.classic_card = OptionCard(self.classic_button, "Readable export.")
        morphs = QHBoxLayout()
        morphs.setSpacing(10)
        morphs.addWidget(self.smart_card)
        morphs.addWidget(self.classic_card)
        right.addLayout(self._labelled("NEW MORPHS", morphs))
        right.addStretch(1)
        body.addLayout(right, 1)

        (self.classic_button if remembered == CLASSIC else self.smart_button).setChecked(True)
        self.cancel_button = self.frame.add_button("Cancel")
        self.ok_button = self.frame.add_button("Create project", "primary")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self.accept)

        start = folder if folder is not None else places.default_folder([])
        self.folder_edit.setText(str(start))
        self.name_edit.setText(rules.free_name(start))
        self.name_edit.textChanged.connect(self._validate)
        self.folder_edit.textChanged.connect(self._validate)
        self.size_box.currentIndexChanged.connect(self._canvas_changed)
        self.fps_box.currentIndexChanged.connect(self._canvas_changed)
        self.length_box.valueChanged.connect(self._canvas_changed)
        self.choose_template(template)
        self._validate()
        self.name_edit.selectAll()
        self.name_edit.setFocus()

    # -- building -----------------------------------------------------------------------------------

    @staticmethod
    def _label(text: str, *, eyebrow: bool = False) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "eyebrow" if eyebrow else "formLabel")
        return label

    def _labelled(self, text: str, content: QWidget | QHBoxLayout) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(4)
        column.addWidget(self._label(text))
        if isinstance(content, QWidget):
            column.addWidget(content)
        else:
            column.addLayout(content)
        return column

    @staticmethod
    def _line(placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("projectField")
        edit.setPlaceholderText(placeholder)
        return edit

    @staticmethod
    def _combo(items: list[str]) -> QComboBox:
        box = QComboBox()
        box.setObjectName("projectField")
        box.addItems(items)
        return box

    # -- choosing -----------------------------------------------------------------------------------

    def choose_template(self, key: str) -> None:
        """Select a starting point: a template brings its own canvas (shown, locked); the blank scene lets
        the canvas be chosen."""
        entry = template_by_key(key)
        self.template = entry
        self.template_cards[entry.key].setChecked(True)
        self.template_title.setText(entry.name)
        self.template_note.setText(entry.description)
        canvas = template_canvas(entry)
        locked = entry.source is not None
        self._locked = locked
        if locked:
            self._show_canvas(canvas)
        else:
            self._show_canvas(
                {
                    "width_px": self.current_size()[0] if self._has_size() else 1280,
                    "height_px": self.current_size()[1] if self._has_size() else 720,
                    "fps": self.current_fps(),
                    "duration": self.length_box.value(),
                    "background": self._background,
                }
            )
        for widget in (self.size_box, self.fps_box, self.length_box, self.custom_colour, *self.swatches):
            widget.setEnabled(not locked)
        self._canvas_changed()

    def _has_size(self) -> bool:
        return self.size_box.currentIndex() >= 0

    def _show_canvas(self, canvas: dict) -> None:
        size = (int(canvas["width_px"]), int(canvas["height_px"]))
        for widget in (self.size_box, self.fps_box, self.length_box):
            widget.blockSignals(True)
        sizes = [(w, h) for _, w, h in rules.SIZES]
        # a template's own size may not be one of the presets: show it as an extra entry
        while self.size_box.count() > len(sizes):
            self.size_box.removeItem(self.size_box.count() - 1)
        if size not in sizes:
            self.size_box.addItem(f"{size[0]} x {size[1]}")
        self.size_box.setCurrentIndex(sizes.index(size) if size in sizes else self.size_box.count() - 1)
        fps = int(canvas["fps"])
        if self.fps_box.count() > len(rules.FRAME_RATES):
            self.fps_box.removeItem(self.fps_box.count() - 1)
        if fps not in rules.FRAME_RATES:
            self.fps_box.addItem(f"{fps} fps")
        self.fps_box.setCurrentIndex(
            rules.FRAME_RATES.index(fps) if fps in rules.FRAME_RATES else self.fps_box.count() - 1
        )
        self.length_box.setValue(float(canvas["duration"]))
        for widget in (self.size_box, self.fps_box, self.length_box):
            widget.blockSignals(False)
        self.set_background(str(canvas["background"]))

    def current_size(self) -> tuple[int, int]:
        index = self.size_box.currentIndex()
        if index < len(rules.SIZES):
            return rules.SIZES[index][1], rules.SIZES[index][2]
        w, _, h = self.size_box.currentText().partition(" x ")
        return int(w), int(h)

    def current_fps(self) -> int:
        index = self.fps_box.currentIndex()
        if 0 <= index < len(rules.FRAME_RATES):
            return rules.FRAME_RATES[index]
        return int(self.fps_box.currentText().split()[0]) if self.fps_box.currentText() else 30

    def set_background(self, colour: str) -> None:
        self._background = colour
        for swatch in self.swatches:
            swatch.setChecked(swatch.colour.lower() == colour.lower())
        self._canvas_changed()

    def pick_colour(self) -> None:
        picked = QColorDialog.getColor(QColor(self._background), self, "Background colour")
        if picked.isValid():
            self.set_background(picked.name())

    def browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Where should the project be saved?", self.folder_edit.text()
        )
        if chosen:
            self.folder_edit.setText(chosen)

    def _canvas_changed(self, *_args) -> None:
        if not self._has_size():
            return
        self.preview.show_canvas(
            self.current_size(), self.current_fps(), self.length_box.value(), self._background
        )

    def _validate(self, *_args) -> None:
        folder, name = self.folder_edit.text().strip(), self.name_edit.text()
        problem = rules.location_problem(folder, name)
        if problem:
            self.path_hint.setText(problem)
            self.path_hint.setStyleSheet(f"color: {theme.css(theme.THEME.danger)};")
        else:
            self.path_hint.setText(f"Saved as {Path(folder) / (name.strip() + rules.EXTENSION)}")
            self.path_hint.setStyleSheet("")
        self.ok_button.setEnabled(not problem)

    # -- the answer ---------------------------------------------------------------------------------

    def choice(self) -> str:
        return CLASSIC if self.classic_button.isChecked() else SMART

    def settings(self) -> NewProjectSettings:
        width, height = self.current_size()
        return NewProjectSettings(
            name=self.name_edit.text().strip(),
            folder=Path(self.folder_edit.text().strip()),
            template=self.template.key,
            morph_matching=self.choice(),
            width_px=width,
            height_px=height,
            fps=self.current_fps(),
            duration=self.length_box.value(),
            background=self._background,
        )
