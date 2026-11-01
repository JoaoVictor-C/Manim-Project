"""The Audio page (P6b.4, ADR 0041; Lumen, ADR 0063): the mix as lanes and the narration, two cards.

**Mix** (a wide card): a ruler and four lanes with waveforms - Narration, Music, Effects, Subtitles
(``MixLanes``) - the playhead, and under them the transport strip (play, the time, the master level, a
"Master -3.1 dB" chip). Its header has the sound's length, **Add sound**, **Markers**, **Table**, a menu of
the rest (subtitles, delete) and the zoom. **Table** swaps the lanes for the sounds table (name, file, start,
trim, duration, gain, fades) and the subtitles table (start, end, text, voice, speech, pause before): the
same rows, edited in place. **Narration** (the shared ``NarrationPanel``, 400 px at the right): the voice
engine, voice, speed, Generate speech, the cues with their state and the pronunciations.

The page has no stage, Properties panel or global timeline: they wait parked while it is shown, and a sound
or subtitle selected here is the one Compose and Animate show (the subtitle style is in Properties there).

A table cell's text becomes an ``Edit`` through ``core/editing/tables.py`` (so ``update_audio`` /
``update_cue`` validate it), applied as one undo step; a refused edit shows its reason in the status bar and
the cell keeps its value. Selection follows the shared ``Selection`` both ways - a click on a lane clip, a
table row or a cue row selects the sound or subtitle (a subtitle also moves the playhead to it).

The level meter shows the peak and RMS of the mix around the playhead (``core/sound/levels.py``); it follows
every seek and playback tick and every edit while the page is shown.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QKeySequence, QLinearGradient, QPainter, QPainterPath, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.editing import edits, tables
from ...core.model.schema import AudioClip, Cue
from ...core.sound import audio, levels
from ...core.voice import narration as speech
from ..panels.narration_panel import NARRATION_COLUMNS, NarrationPanel, cue_cell
from ..style import icons, theme
from ..style.card import Card, Chip, gutter_splitter, page_margins
from . import Page
from .mix_lanes import MAX_ZOOM, MixLanes, stamp

LEVEL_ZONES = ((-18.0, "success"), (-6.0, "warning"), (0.0, "danger"))  # up to this dB, in this colour
NARRATION_WIDTH = 400  # px: the Narration card
MIX_MIN = 340  # px: the least the Mix card is given


def _rules(c: theme.Colours) -> str:
    return f"""
QTableView {{
    background: transparent; border: 0; outline: 0; gridline-color: transparent;
    alternate-background-color: {theme.mix(c.panel, c.raised, 0.55)};
}}
QTableView::item {{ padding: 2px 8px; border: 0; }}
QTableView::item:selected {{ background: {theme.css(c.accent_soft)}; color: {c.text}; }}
QTableCornerButton::section {{ background: {c.raised}; border: 0; }}
QTableView QScrollBar::handle:vertical {{ min-height: 14px; }}
QFrame#masterStrip {{ background: {c.raised}; border: 1px solid {theme.css(c.line)}; border-radius: 14px; }}
QFrame#masterStrip QLabel {{ background: transparent; }}
QFrame#masterStrip QLabel[chip="true"] {{
    background: {c.surface_3}; border: 1px solid {theme.css(c.line)}; border-radius: 11px;
}}
QLabel#mixTime {{ font-weight: 600; color: {c.text}; }}
"""


theme.register_rules(_rules)
MISSING_FILE = "file not found"
UNREADABLE_FILE = "cannot read the file"


class CompactTable(QTableView):
    """A table that may shrink to little more than its header (a small window gives the Mix card the room)."""

    def minimumSizeHint(self) -> QSize:
        return QSize(80, 34)


class RowsModel(QAbstractTableModel):
    """One kind of row (sounds or subtitles) read from the document and edited through ``core.tables``.

    Rows are the objects of the last ``refresh()`` (a document change); ``setData`` applies the cell's
    edit to the live document once, or refuses with the reason (the status bar) and returns False.
    """

    def __init__(
        self,
        page: AudioPage,
        columns: tuple[tables.Column, ...],
        items: Callable[[], list[Any]],
        cell: Callable[[Any, str], str],
        edit: Callable[[Any, str, str, str], edits.Edit],
    ) -> None:
        super().__init__()
        self.page, self.columns, self._items, self._cell, self._edit = page, columns, items, cell, edit
        self.rows: list[Any] = []
        self.problems: dict[str, str] = {}

    @property
    def ids(self) -> list[str]:
        return [row.id for row in self.rows]

    def refresh(self) -> None:
        """Read the document again: new rows reset the view, the same rows only update their cells."""
        rows = list(self._items())
        same = [r.id for r in rows] == self.ids
        if not same:
            self.beginResetModel()
        self.rows = rows
        self.problems = {r.id: why for r in rows if isinstance(r, AudioClip) and (why := file_problem(r))}
        if not same:
            self.endResetModel()
        elif rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, len(self.columns) - 1))

    def row_of(self, item_id: str | None) -> int:
        return next((i for i, row in enumerate(self.rows) if row.id == item_id), -1)

    # -- the model -------------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(self.columns):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section].title
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.columns[section].tip
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row, column = self.rows[index.row()], self.columns[index.column()]
        text = self._cell(row, column.key)
        problem = self.problems.get(row.id) if column.key == "path" else None
        if role == Qt.ItemDataRole.EditRole:
            return text
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{text} - {problem}" if problem else text
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{row.path}\n{problem}" if column.key == "path" else column.tip
        if role == Qt.ItemDataRole.ForegroundRole and (
            problem or (column.key == "speech" and text == "stale")
        ):
            return theme.qcolor(theme.THEME.warning)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            numeric = column.key not in ("name", "path", "text", "voice", "speech")
            side = Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft
            return int(side | Qt.AlignmentFlag.AlignVCenter)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and self.columns[index.column()].editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or not 0 <= index.row() < len(self.rows):
            return False
        column = self.columns[index.column()]
        project = self.page.window.project
        if project is None or not column.editable:
            return False
        try:
            edit = self._edit(project, self.rows[index.row()].id, column.key, str(value))
        except ValueError as exc:  # EditError, or a validation error of the edit
            self.page.message(tables.reason(exc))
            return False
        if edit.project == project:  # typed what was already there
            return False
        self.page.window.document.apply(edit, column.undo)
        return True


def file_problem(clip: AudioClip) -> str | None:
    """Why a sound is silent, cheaply (a file check and the cached probe; ``audio.problem`` decodes)."""
    if audio.signature(clip.path) == audio.MISSING:
        return MISSING_FILE
    return UNREADABLE_FILE if audio.probe(clip.path) is None else None


class PlayButton(QAbstractButton):
    """The round play button of the transport strip: the accent gradient, a filled play or pause glyph."""

    SIZE = 34

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("playMix")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.playing = False

    def sizeHint(self) -> QSize:
        return QSize(self.SIZE, self.SIZE)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.SIZE, self.SIZE)

    def set_playing(self, playing: bool) -> None:
        self.playing = playing
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colours = theme.THEME
        disc = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isEnabled():
            fill = QLinearGradient(disc.topLeft(), disc.bottomRight())
            fill.setColorAt(0.0, theme.qcolor(colours.accent_2))
            fill.setColorAt(1.0, theme.qcolor(colours.accent))
            painter.setBrush(fill)
        else:
            painter.setBrush(theme.qcolor(colours.surface_3))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(disc)
        if self.underMouse() and self.isEnabled():
            shine = QColor(theme.qcolor(colours.on_accent))
            shine.setAlpha(36)
            painter.setBrush(shine)
            painter.drawEllipse(disc)
        painter.setBrush(theme.qcolor(colours.on_accent if self.isEnabled() else colours.disabled))
        c = disc.center()
        if self.playing:
            painter.drawRoundedRect(QRectF(c.x() - 5.5, c.y() - 6, 4, 12), 1, 1)
            painter.drawRoundedRect(QRectF(c.x() + 1.5, c.y() - 6, 4, 12), 1, 1)
        else:
            glyph = QPainterPath()
            glyph.moveTo(c.x() - 4, c.y() - 7)
            glyph.lineTo(c.x() + 7, c.y())
            glyph.lineTo(c.x() - 4, c.y() + 7)
            glyph.closeSubpath()
            painter.drawPath(glyph)
        painter.end()


class LevelBars(QWidget):
    """Two rows of small bars (left, right) in dB from -60 to 0: the RMS lit in zones, the peak as one
    bright bar - the master level, as the transport strip shows it."""

    BAR, GAP = 4.0, 2.0

    def __init__(self) -> None:
        super().__init__()
        self.level = levels.SILENCE
        self.setMinimumSize(80, 26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:
        return QSize(260, 28)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colours = theme.THEME
        bar_h = max(6.0, (self.height() - 3) / 2)
        x0 = 14.0
        count = max(1, int((self.width() - x0) // (self.BAR + self.GAP)))
        painter.setFont(theme.mono_font(7))
        for row, side in enumerate("LR"):
            top = row * (bar_h + 3)
            painter.setPen(theme.qcolor(colours.faint))
            painter.drawText(QRectF(0, top, x0 - 3, bar_h), Qt.AlignmentFlag.AlignCenter, side)
            lit = levels.fraction(self.level.rms_db[row])
            peak = (
                levels.fraction(self.level.peak_db[row]) if self.level.peak_db[row] > levels.FLOOR_DB else -1
            )
            painter.setPen(Qt.PenStyle.NoPen)
            for i in range(count):
                where = (i + 0.5) / count
                left = x0 + i * (self.BAR + self.GAP)
                if where <= lit:
                    token = next(t for db, t in LEVEL_ZONES if where <= levels.fraction(db) or db == 0.0)
                    painter.setBrush(theme.qcolor(getattr(colours, token)))
                elif peak >= 0 and abs(where - peak) <= 0.5 / count:
                    painter.setBrush(theme.qcolor(colours.text))
                else:
                    painter.setBrush(theme.qcolor(colours.surface_3))
                path = QPainterPath()
                path.addRoundedRect(QRectF(left, top, self.BAR, bar_h), 1.5, 1.5)
                painter.drawPath(path)
        painter.end()


class LevelMeter(QFrame):
    """The transport strip: the play button, the time, the mix's level at the playhead (bars) and a
    "Master -3.1 dB" chip; ``readout()`` is the full peak and RMS (the chip's tooltip)."""

    def __init__(self, play_button: QPushButton, time_label: QLabel) -> None:
        super().__init__()
        self.setObjectName("masterStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.level = levels.SILENCE
        self.bars = LevelBars()
        self.chip = Chip("Master")
        self.chip.setFont(theme.mono_font())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)
        layout.addWidget(play_button)
        layout.addWidget(time_label)
        layout.addWidget(self.bars, 1)
        layout.addWidget(self.chip)
        self.set_level(levels.SILENCE)

    def set_level(self, level: levels.Level) -> None:
        self.level = self.bars.level = level
        loudest = max(level.peak_db)
        self.chip.setText(
            "Master silent" if loudest <= levels.FLOOR_DB else f"Master {levels.label(loudest)} dB"
        )
        tip = self.readout()
        self.chip.setToolTip(tip)
        self.bars.setToolTip(tip)
        self.bars.update()

    def readout(self) -> str:
        peak, rms = level_labels(self.level.peak_db), level_labels(self.level.rms_db)
        return f"peak  L {peak[0]:>5}  R {peak[1]:>5} dB\nRMS   L {rms[0]:>5}  R {rms[1]:>5} dB"


def level_labels(values: tuple[float, float]) -> tuple[str, str]:
    return levels.label(values[0]), levels.label(values[1])


class AudioPage(Page):
    name = "audio"
    title = "Audio"
    icon = "audio"
    tooltip = "The mix as lanes, the narration and the subtitles (Ctrl+4)"

    def build(self) -> QWidget:
        self._active = False  # shown: the tables and the meter follow the document
        self._wired = False
        self._syncing = False  # selecting a row because the selection changed, not because of a click
        self.sounds_model = RowsModel(
            self, tables.SOUND_COLUMNS, self._clips, tables.sound_cell, tables.sound_edit
        )
        self.cues_model = RowsModel(
            self, tables.CUE_COLUMNS + NARRATION_COLUMNS, self._cues, self._cue_cell, tables.cue_edit
        )
        self.sounds = self._table(self.sounds_model)
        self.cues = self._table(self.cues_model)
        header = self.sounds.horizontalHeader()  # names and files share the room, numbers fit their text
        for column in range(self.sounds_model.columnCount()):
            fits = column > 1
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents if fits else QHeaderView.ResizeMode.Stretch
            )
        self.cues.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (3, 4, 5):  # voice, speech, pause before
            self.cues.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.sounds.selectionModel().currentRowChanged.connect(self._sound_row_chosen)
        self.cues.selectionModel().currentRowChanged.connect(self._cue_row_chosen)
        self.cues.clicked.connect(self._cue_clicked)
        self.import_sound_button = self._button(
            "Add sound", "add", "Add a sound at the playhead", ghost=False
        )
        self.delete_sound_button = self._button(
            "Delete", "delete", "Delete the selected sound", icon_only=True
        )
        self.play_button = PlayButton()
        self.play_button.setToolTip("Play the video from the playhead (Space)")
        self.play_button.setAccessibleName("Play")
        self.add_cue_button = self._button("Add", "add", "Add a subtitle at the playhead (Ctrl+T)")
        self.delete_cue_button = self._button(
            "Delete", "delete", "Delete the selected subtitle", icon_only=True
        )
        self.import_srt_button = self._button(
            "Import .srt", "open", "Replace the subtitles with an .srt file", icon_only=True
        )
        self.export_srt_button = self._button(
            "Export .srt", "export", "Write the subtitles to an .srt file", icon_only=True
        )
        self.import_sound_button.clicked.connect(lambda: self.window.import_audio())
        self.delete_sound_button.clicked.connect(self.delete_sound)
        self.play_button.clicked.connect(lambda: self.window.toggle_play())
        self.add_cue_button.clicked.connect(lambda: self.window.add_subtitle())
        self.delete_cue_button.clicked.connect(self.delete_cue)
        self.import_srt_button.clicked.connect(lambda: self.window.import_subtitles())
        self.export_srt_button.clicked.connect(lambda: self.window.export_subtitles())
        for view, slot in ((self.sounds, self.delete_sound), (self.cues, self.delete_cue)):
            delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), view)
            delete.setContext(Qt.ShortcutContext.WidgetShortcut)  # not while a cell is being edited
            delete.activated.connect(slot)
        self.time_chip = QLabel(stamp(0.0))  # the playhead's time, in the transport strip
        self.time_chip.setObjectName("mixTime")
        self.time_chip.setFont(theme.mono_font(theme.UI_POINT_SIZE + 2))
        self.time_chip.setMinimumWidth(70)
        self.meter = LevelMeter(self.play_button, self.time_chip)

        self.narration = NarrationPanel(self.window)
        self.narration.cueChosen.connect(self._pick_cue)
        self.lanes = MixLanes(lambda: self.window.project, lambda: self.window.t)
        self.lanes.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.lanes.seekRequested.connect(self._seek_from_lanes)
        self.lanes.soundClicked.connect(self._pick_sound)
        self.lanes.cueClicked.connect(self._pick_cue)
        self.lanes.viewChanged.connect(self._sync_scroll)
        delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.lanes)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.delete_selected)
        self.scroll_bar = QScrollBar(Qt.Orientation.Horizontal)
        self.scroll_bar.setToolTip("Scroll the zoomed mix")
        self.scroll_bar.valueChanged.connect(lambda v: self.lanes.set_scroll(v / 1000))
        self.scroll_bar.hide()

        self.mix_card = self._mix_card()
        self.narration_card = self._narration_card()
        self.top = gutter_splitter(Qt.Orientation.Horizontal)  # Mix | Narration
        self.top.addWidget(self.mix_card)
        self.top.addWidget(self.narration_card)
        self.top.setStretchFactor(0, 1)
        self.top.setStretchFactor(1, 0)
        root = QWidget()
        layout = QHBoxLayout(root)
        page_margins(layout)
        layout.addWidget(self.top)
        return root

    # -- building --------------------------------------------------------------------------

    def _table(self, model: RowsModel) -> QTableView:
        view = CompactTable()
        view.setModel(model)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        view.setAlternatingRowColors(True)
        view.setShowGrid(False)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setWordWrap(False)
        view.verticalHeader().hide()
        view.verticalHeader().setDefaultSectionSize(30)
        view.horizontalHeader().setHighlightSections(False)
        view.horizontalHeader().setMinimumSectionSize(56)
        view.setMinimumHeight(34)
        return view

    def _button(
        self, text: str, icon: str, tip: str, *, icon_only: bool = False, ghost: bool = True
    ) -> QPushButton:
        button = QPushButton(icons.icon(icon), "" if icon_only else text)
        button.setToolTip(tip)
        button.setAccessibleName(text)
        if ghost:
            button.setProperty("role", "ghost")
        return button

    def _mix_card(self) -> Card:
        card = Card("Mix")
        self.length_chip = Chip(stamp(0.0))  # how long the scene is
        self.length_chip.setFixedHeight(22)
        self.length_chip.setFont(theme.mono_font())
        self.length_chip.setToolTip("The length of the scene")
        card.add_title_widget(self.length_chip)
        self.markers_button = self._button("Markers", "marker", "Markers: add one at the playhead, or jump")
        menu = QMenu(self.markers_button)
        self.add_marker_action = menu.addAction("Add marker at the playhead")
        self.previous_marker_action = menu.addAction("Previous marker")
        self.next_marker_action = menu.addAction("Next marker")
        self.add_marker_action.triggered.connect(lambda: self.window.add_marker())
        self.previous_marker_action.triggered.connect(lambda: self.window.jump_to_marker(-1))
        self.next_marker_action.triggered.connect(lambda: self.window.jump_to_marker(+1))
        self.markers_button.setMenu(menu)
        self.table_button = self._button("Table", "text", "Show the sounds and subtitles as editable tables")
        self.table_button.setCheckable(True)
        self.table_button.toggled.connect(self._show_tables)
        self.more_button = self._button("More", "more", "Subtitles and deleting", icon_only=True)
        more = QMenu(self.more_button)
        self.more_actions = {
            "add_cue": more.addAction(icons.icon("add"), "Add a subtitle at the playhead"),
            "import_srt": more.addAction(icons.icon("open"), "Import .srt..."),
            "export_srt": more.addAction(icons.icon("export"), "Export .srt..."),
            "delete": more.addAction(icons.icon("delete"), "Delete the selected sound or subtitle"),
        }
        self.more_actions["add_cue"].triggered.connect(lambda: self.add_cue_button.click())
        self.more_actions["import_srt"].triggered.connect(lambda: self.import_srt_button.click())
        self.more_actions["export_srt"].triggered.connect(lambda: self.export_srt_button.click())
        self.more_actions["delete"].triggered.connect(self.delete_selected)
        self.more_button.setMenu(more)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, 100)
        self.zoom_slider.setFixedWidth(100)
        self.zoom_slider.setToolTip("Zoom the mix (Ctrl+wheel on it)")
        self.zoom_slider.valueChanged.connect(self._zoom_chosen)
        for widget in (
            self.import_sound_button,
            self.markers_button,
            self.table_button,
            self.more_button,
            self.zoom_slider,
        ):
            card.add_action(widget)

        self.tables = gutter_splitter(Qt.Orientation.Vertical)  # Sounds over Subtitles
        self.tables.addWidget(self._table_section("Sounds", self.sounds, (self.delete_sound_button,)))
        self.tables.addWidget(
            self._table_section(
                "Subtitles",
                self.cues,
                (self.add_cue_button, self.delete_cue_button, self.import_srt_button, self.export_srt_button),
            )
        )
        lanes_page = QWidget()
        lanes_column = QVBoxLayout(lanes_page)
        lanes_column.setContentsMargins(0, 0, 0, 0)
        lanes_column.setSpacing(4)
        lanes_column.addWidget(self.lanes, 1)
        lanes_column.addWidget(self.scroll_bar)
        self.views = QStackedWidget()  # the lanes, or the tables
        self.views.addWidget(lanes_page)
        self.views.addWidget(self.tables)
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(10, 8, 10, 10)
        column.setSpacing(8)
        column.addWidget(self.views, 1)
        column.addWidget(self.meter)
        card.set_body(body)
        card.setMinimumWidth(MIX_MIN)
        return card

    def _table_section(self, title: str, view: QTableView, buttons: tuple[QPushButton, ...]) -> QWidget:
        section = QWidget()
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 0, 0)
        head.setSpacing(4)
        label = QLabel(title.upper())
        label.setProperty("role", "hint")
        head.addWidget(label)
        head.addStretch(1)
        for button in buttons:
            head.addWidget(button)
        column = QVBoxLayout(section)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addLayout(head)
        column.addWidget(view, 1)
        return section

    def _narration_card(self) -> Card:
        card = Card("Narration")
        self.stale_chip = Chip("", "warn")
        self.stale_chip.setFixedHeight(22)
        self.stale_chip.setVisible(False)
        card.add_title_widget(self.stale_chip)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.narration)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.narration.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        card.set_body(scroll)
        card.setMinimumWidth(NARRATION_WIDTH - 60)
        return card

    def _show_tables(self, shown: bool) -> None:
        self.views.setCurrentIndex(1 if shown else 0)
        self.table_button.setText("Lanes" if shown else "Table")
        self.table_button.setToolTip(
            "Back to the lanes" if shown else "Show the sounds and subtitles as editable tables"
        )

    def _zoom_chosen(self, value: int) -> None:
        zoom = MAX_ZOOM ** (value / 100)
        self.lanes.set_zoom(zoom, self.window.t)

    def _sync_scroll(self) -> None:
        """The scroll bar shows the part of the mix the lanes show (hidden while the whole mix is)."""
        lanes = self.lanes
        zoomed = lanes.zoom > 1.0 + 1e-9
        self.scroll_bar.setVisible(zoomed)
        if zoomed:
            self.scroll_bar.blockSignals(True)
            self.scroll_bar.setRange(0, round((lanes.duration() - lanes.span()) * 1000))
            self.scroll_bar.setPageStep(round(lanes.span() * 1000))
            self.scroll_bar.setValue(round(lanes.scroll * 1000))
            self.scroll_bar.blockSignals(False)

    # -- document and selection ---------------------------------------------------------------

    def _clips(self) -> list[AudioClip]:
        project = self.window.project
        return list(project.audio) if project is not None else []

    def _cues(self) -> list[Cue]:
        project = self.window.project
        return list(project.subtitles) if project is not None else []

    def _cue_cell(self, cue: Cue, key: str) -> str:
        project = self.window.project
        if key in ("voice", "speech") and project is not None:
            return cue_cell(project, cue, key)
        return tables.cue_cell(cue, key)

    def message(self, text: str) -> None:
        self.window.statusBar().showMessage(text, 10000)

    def _connect(self) -> None:
        """Follow the window (once): it builds the selection after the pages."""
        self._wired = True
        window = self.window
        window.document.changed.connect(self._on_changed)
        window.document.reset.connect(lambda _project: self.refresh())
        window.selection.changed.connect(self._sync_selection)
        window.playheadMoved.connect(self._on_playhead)
        window.playingChanged.connect(self._on_playing)

    def on_show(self) -> None:
        if not self._wired:
            self._connect()
            width = max(self.top.width(), 1000)
            self.top.setSizes([width - NARRATION_WIDTH, NARRATION_WIDTH])  # first show
            height = max(self.tables.height(), 400)
            self.tables.setSizes([int(height * 0.4), int(height * 0.6)])
        self._active = True
        self.refresh()
        self._on_playing(self.window.play_timer.isActive())

    def on_hide(self) -> None:
        self._active = False

    def refresh(self) -> None:
        """Read everything again: both tables, the selection in them, the buttons, the meter, the lanes."""
        if not self._active:
            return
        self._syncing = True
        try:
            self.sounds_model.refresh()
            self.cues_model.refresh()
        finally:
            self._syncing = False
        self._sync_selection()
        self.refresh_meter()
        self.narration.refresh()
        self.lanes.refresh()
        self._sync_scroll()
        self._refresh_header()
        self._refresh_stale()

    def _on_changed(self, *_args) -> None:
        self.refresh()

    def _on_playhead(self, t: float) -> None:
        if self._active:
            self.refresh_meter()
            self.time_chip.setText(stamp(t))
            lanes = self.lanes
            if lanes.zoom > 1.0 and not lanes.scroll <= t <= lanes.scroll + lanes.span():
                lanes.set_scroll(t - lanes.span() * 0.1)  # a zoomed mix follows the playhead
            lanes.update()

    def _on_playing(self, playing: bool) -> None:
        self.play_button.set_playing(playing)
        self.play_button.setToolTip(
            "Pause (Space)" if playing else "Play the video from the playhead (Space)"
        )

    def _refresh_header(self) -> None:
        self.length_chip.setText(stamp(self.lanes.duration()))
        self.time_chip.setText(stamp(self.window.t))
        project = self.window.project
        self.previous_marker_action.setEnabled(project is not None and bool(project.markers))
        self.next_marker_action.setEnabled(project is not None and bool(project.markers))

    def _refresh_stale(self) -> None:
        """The Narration card's chip: how many subtitles speak an old text or voice."""
        project = self.window.project
        stale = (
            sum(1 for cue in project.subtitles if speech.state(project, cue) == speech.STALE)
            if project
            else 0
        )
        self.stale_chip.setText(f"{stale} stale")
        self.stale_chip.setVisible(stale > 0)

    def _seek_from_lanes(self, t: float) -> None:
        self.window.pause()
        self.window.seek(t)

    def _pick_sound(self, sound_id: str) -> None:
        row = self.sounds_model.row_of(sound_id)
        if row >= 0:
            self.sounds.setCurrentIndex(
                self.sounds_model.index(row, max(self.sounds.currentIndex().column(), 0))
            )

    def _pick_cue(self, cue_id: str) -> None:
        row = self.cues_model.row_of(cue_id)
        if row >= 0:
            self.cues.setCurrentIndex(self.cues_model.index(row, max(self.cues.currentIndex().column(), 0)))
            self._seek_to_cue(row)  # clicking a bar again brings the playhead back, as a row does

    def refresh_meter(self) -> None:
        project = self.window.project
        self.meter.set_level(
            levels.level_at(project, self.window.t)
            if project is not None and project.audio
            else levels.SILENCE
        )

    def _sync_selection(self) -> None:
        """The shared selection chose a sound or a subtitle (or nothing): select its row, seek nothing."""
        if not self._active:
            return
        selection = self.window.selection
        self._syncing = True
        try:
            self._select_row(self.sounds, self.sounds_model, selection.audio_id)
            self._select_row(self.cues, self.cues_model, selection.subtitle_id)
        finally:
            self._syncing = False
        self._update_buttons()
        self.narration.refresh()
        self.lanes.set_selection(selection.audio_id, selection.subtitle_id)
        self._refresh_stale()

    def _select_row(self, view: QTableView, model: RowsModel, item_id: str | None) -> None:
        row = model.row_of(item_id)
        if row < 0:
            view.clearSelection()
            view.setCurrentIndex(QModelIndex())
            return
        column = max(view.currentIndex().column(), 0)
        view.setCurrentIndex(model.index(row, column))
        view.scrollTo(model.index(row, column))

    def _sound_row_chosen(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._syncing or not current.isValid():
            return
        self.window.selection.set_audio(self.sounds_model.rows[current.row()].id)
        self._update_buttons()

    def _cue_row_chosen(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._syncing or not current.isValid():
            return
        self.window.selection.set_subtitle(self.cues_model.rows[current.row()].id)
        self._seek_to_cue(current.row())
        self._update_buttons()

    def _cue_clicked(self, index: QModelIndex) -> None:
        if not self._syncing and index.isValid():
            self._seek_to_cue(index.row())  # clicking the row again after the playhead moved away

    def _seek_to_cue(self, row: int) -> None:
        if 0 <= row < len(self.cues_model.rows):
            self.window.pause()
            self.window.seek(self.cues_model.rows[row].start)

    def _update_buttons(self) -> None:
        has_project = self.window.project is not None
        selection = self.window.selection
        self.import_sound_button.setEnabled(has_project)
        self.play_button.setEnabled(has_project)
        self.add_cue_button.setEnabled(has_project)
        self.import_srt_button.setEnabled(has_project)
        self.export_srt_button.setEnabled(has_project and bool(self.cues_model.rows))
        sound = self.sounds_model.row_of(selection.audio_id) >= 0
        cue = self.cues_model.row_of(selection.subtitle_id) >= 0
        self.delete_sound_button.setEnabled(sound)
        self.delete_cue_button.setEnabled(cue)
        self.table_button.setEnabled(has_project)
        self.markers_button.setEnabled(has_project)
        self.more_actions["add_cue"].setEnabled(has_project)
        self.more_actions["import_srt"].setEnabled(has_project)
        self.more_actions["export_srt"].setEnabled(self.export_srt_button.isEnabled())
        self.more_actions["delete"].setEnabled(sound or cue)

    # -- deleting ---------------------------------------------------------------------------

    def delete_sound(self) -> None:
        """Delete the selected sound (one undo step)."""
        project, sound_id = self.window.project, self.window.selection.audio_id
        if project is not None and self.sounds_model.row_of(sound_id) >= 0:
            self.window.document.apply(edits.remove_audio(project, sound_id), "Delete sound")

    def delete_cue(self) -> None:
        """Delete the selected subtitle (one undo step)."""
        project, cue_id = self.window.project, self.window.selection.subtitle_id
        if project is not None and self.cues_model.row_of(cue_id) >= 0:
            self.window.document.apply(edits.remove_cue(project, cue_id), "Delete subtitle")

    def delete_selected(self) -> None:
        """Delete the selected sound or subtitle (the Delete key on the lanes, the More menu)."""
        if self.sounds_model.row_of(self.window.selection.audio_id) >= 0:
            self.delete_sound()
        else:
            self.delete_cue()
