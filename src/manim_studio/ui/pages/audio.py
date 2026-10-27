"""The Audio page (P6b.4, ADR 0041; Lumen, ADR 0063): the mix as lanes, sounds and subtitles as tables, the
narration, a master level strip, the shared viewer and Properties.

Cards: **Mix** (``MixLanes`` - narration, sounds and subtitles on a ruler with waveforms - over the master
level strip), **Sounds** and **Subtitles** (the tables) in the left column; **Narration** (the shared
``NarrationPanel``, as it is) in the middle; the viewer over Properties at the right; the timeline below.

A *sounds* table (name, file, start, trim, duration, gain, fades) and a *subtitles* table (start, end,
text) read the document snapshot and edit it in place: a cell's text becomes an ``Edit`` through
``core/editing/tables.py`` (so ``update_audio`` / ``update_cue`` validate it), applied as one undo step; a
refused edit shows its reason in the status bar and the cell keeps its value. Selection follows the
shared ``Selection`` both ways - a click on a row selects the sound or subtitle (a subtitle row also
moves the playhead to it), a selection made on the timeline selects the row without moving anything.

The level meter shows the peak and RMS of the mix around the playhead (``core/sound/levels.py``); it follows
every seek and playback tick and every edit while the page is shown. The subtitle style is in the shared
Properties panel (select a subtitle), and the timeline sits below, as on every page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
from . import Page, Shared
from .mix_lanes import MixLanes, stamp

ZONES = ((levels.FLOOR_DB, -18.0, "success"), (-18.0, -6.0, "warning"), (-6.0, 0.0, "danger"))
SCALE_DB = (-60, -40, -20, -10, -6, 0)
LEFT_MIN, NARRATION_MIN = 340, 300  # px: the least the left column and the Narration card are given


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


class LevelBars(QWidget):
    """Two bars (left, right) in dB from -60 to 0: the RMS filled in zones, the peak as a tick."""

    def __init__(self) -> None:
        super().__init__()
        self.level = levels.SILENCE
        self.setMinimumSize(96, 46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:
        return QSize(320, 70)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colours = theme.THEME
        scale_h = 14
        bar_h = max(8.0, (self.height() - scale_h - 6) / 2)
        x0, width = 18.0, max(1.0, self.width() - 26.0)
        painter.setFont(theme.mono_font(7))
        for row, side in enumerate("LR"):
            top = 2 + row * (bar_h + 3)
            track = QPainterPath()
            track.addRoundedRect(QRectF(x0, top, width, bar_h), 4, 4)
            painter.fillPath(track, theme.qcolor(colours.surface_3))
            painter.save()
            painter.setClipPath(track)
            for low, high, token in ZONES:  # the RMS, zone by zone
                reach = min(self.level.rms_db[row], high)
                if reach > low:
                    left = x0 + width * levels.fraction(low)
                    painter.fillRect(
                        QRectF(left, top, width * (levels.fraction(reach) - levels.fraction(low)), bar_h),
                        theme.qcolor(getattr(colours, token)),
                    )
            painter.restore()
            peak = self.level.peak_db[row]
            if peak > levels.FLOOR_DB:
                painter.setPen(QPen(theme.qcolor(colours.text), 2))
                px = x0 + width * levels.fraction(peak)
                painter.drawLine(int(px), int(top), int(px), int(top + bar_h))
            painter.setPen(theme.qcolor(colours.faint))
            painter.drawText(QRectF(0, top, x0 - 4, bar_h), Qt.AlignmentFlag.AlignCenter, side)
        painter.setPen(theme.qcolor(colours.faint))
        base = 2 + 2 * (bar_h + 3)
        for db in SCALE_DB:
            px = x0 + width * levels.fraction(db)
            painter.drawText(QRectF(px - 16, base, 32, scale_h), Qt.AlignmentFlag.AlignCenter, str(db))
        painter.end()


class LevelMeter(QFrame):
    """The master strip: the mix's level at the playhead, bars and a readout (``readout()``)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("masterStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.level = levels.SILENCE
        title = QLabel("Master level")
        title.setProperty("role", "section")
        self.bars = LevelBars()
        self.label = QLabel()
        self.label.setObjectName("levelReadout")
        self.label.setFont(theme.mono_font())
        self.label.setProperty("role", "muted")
        words = QVBoxLayout()
        words.setSpacing(theme.SPACE)
        words.addWidget(title)
        words.addWidget(self.label)
        words.addStretch(1)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)
        layout.addLayout(words)
        layout.addWidget(self.bars, 1)
        self.set_level(levels.SILENCE)

    def set_level(self, level: levels.Level) -> None:
        self.level = self.bars.level = level
        self.label.setText(self.readout())
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
    tooltip = "Sounds and subtitles as tables, and the level at the playhead (Ctrl+4)"

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
        self.import_sound_button = self._button("Import", "open", "Import a sound at the playhead")
        self.delete_sound_button = self._button(
            "Delete", "delete", "Delete the selected sound", icon_only=True
        )
        self.play_button = self._button("Play", "play", "Play the video from the playhead")
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
        self.play_button.clicked.connect(lambda: self.window.play())
        self.add_cue_button.clicked.connect(lambda: self.window.add_subtitle())
        self.delete_cue_button.clicked.connect(self.delete_cue)
        self.import_srt_button.clicked.connect(lambda: self.window.import_subtitles())
        self.export_srt_button.clicked.connect(lambda: self.window.export_subtitles())
        for view, slot in ((self.sounds, self.delete_sound), (self.cues, self.delete_cue)):
            delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), view)
            delete.setContext(Qt.ShortcutContext.WidgetShortcut)  # not while a cell is being edited
            delete.activated.connect(slot)
        self.meter = LevelMeter()

        self.narration = NarrationPanel(self.window)
        self.lanes = MixLanes(lambda: self.window.project, lambda: self.window.t)
        self.lanes.seekRequested.connect(self._seek_from_lanes)
        self.lanes.soundClicked.connect(self._pick_sound)
        self.lanes.cueClicked.connect(self._pick_cue)

        self.mix_card = self._mix_card()
        self.sounds_card = self._table_card(
            "Sounds", self.sounds, (self.import_sound_button, self.delete_sound_button, self.play_button)
        )
        self.cues_card = self._table_card(
            "Subtitles",
            self.cues,
            (self.add_cue_button, self.delete_cue_button, self.import_srt_button, self.export_srt_button),
        )
        self.tables = gutter_splitter(Qt.Orientation.Vertical)  # Mix over Sounds over Subtitles
        for card in (self.mix_card, self.sounds_card, self.cues_card):
            self.tables.addWidget(card)
        self.tables.setStretchFactor(0, 3)
        self.tables.setStretchFactor(1, 2)
        self.tables.setStretchFactor(2, 2)
        self.tables.setMinimumWidth(LEFT_MIN)

        self.narration_card = self._narration_card()
        self.centre = gutter_splitter(Qt.Orientation.Vertical)  # the viewer over Properties (both placed)
        self.right = self.centre
        self.top = gutter_splitter(
            Qt.Orientation.Horizontal
        )  # Mix and tables | viewer, Properties | Narration
        self.top.addWidget(self.tables)
        self.top.addWidget(self.centre)
        self.top.addWidget(self.narration_card)  # at the right, as in the mock-up (Lumen, ADR 0063)
        self.outer = gutter_splitter(Qt.Orientation.Vertical)  # all of that over the timeline (placed)
        self.outer.addWidget(self.top)
        root = QWidget()
        layout = QHBoxLayout(root)
        page_margins(layout)
        layout.addWidget(self.outer)
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

    def _button(self, text: str, icon: str, tip: str, *, icon_only: bool = False) -> QPushButton:
        button = QPushButton(icons.icon(icon), "" if icon_only else text)
        button.setToolTip(tip)
        button.setAccessibleName(text)
        button.setProperty("role", "ghost")
        return button

    def _mix_card(self) -> Card:
        card = Card("Mix")
        self.time_chip = Chip(stamp(0.0))
        self.time_chip.setFixedHeight(22)
        self.time_chip.setFont(theme.mono_font())
        card.add_title_widget(self.time_chip)
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(10, 8, 10, 10)
        column.setSpacing(8)
        column.addWidget(self.lanes, 1)
        column.addWidget(self.meter)
        card.set_body(body)
        return card

    def _table_card(self, title: str, view: QTableView, buttons: tuple[QPushButton, ...]) -> Card:
        card = Card(title)
        for button in buttons:
            card.add_action(button)
        card.set_body(view)
        return card

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
        self.narration.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        card.set_body(scroll)
        card.setMinimumWidth(NARRATION_MIN)
        return card

    def place(self, shared: Shared) -> None:
        self.centre.insertWidget(0, shared.viewer)
        self.centre.insertWidget(1, shared.properties)
        self.outer.insertWidget(1, shared.timeline)
        self.centre.setStretchFactor(0, 1)
        self.centre.setStretchFactor(1, 1)
        for i, stretch in enumerate((1, 0, 0)):
            self.top.setStretchFactor(i, stretch)
        self.outer.setStretchFactor(0, 1)
        self.outer.setStretchFactor(1, 0)  # the timeline keeps its height

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

    def on_show(self) -> None:
        if not self._wired:
            self._connect()
            width, height = max(self.top.width(), 1200), max(self.outer.height(), 700)
            narration_w, properties_w = 610, 320  # first show: the mix and the tables get the rest
            self.top.setSizes([width - narration_w - properties_w, properties_w, narration_w])
            self.outer.setSizes([int(height * 0.74), int(height * 0.26)])
            room = int(height * 0.74)  # the left column: the mix, then the two tables
            self.tables.setSizes([int(room * 0.5), int(room * 0.24), int(room * 0.26)])
            self.centre.setSizes([int(room * 0.45), int(room * 0.55)])
        self._active = True
        self.refresh()

    def on_hide(self) -> None:
        self._active = False

    def refresh(self) -> None:
        """Read everything again: both tables, the selection in them, the buttons, the meter."""
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
        self._refresh_stale()

    def _on_changed(self, *_args) -> None:
        self.refresh()

    def _on_playhead(self, t: float) -> None:
        if self._active:
            self.refresh_meter()
            self.time_chip.setText(stamp(t))
            self.lanes.update()

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
        self.delete_sound_button.setEnabled(self.sounds_model.row_of(selection.audio_id) >= 0)
        self.delete_cue_button.setEnabled(self.cues_model.row_of(selection.subtitle_id) >= 0)

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
