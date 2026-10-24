"""The Audio page (P6b.4, ADR 0041): sounds and subtitles as tables, a level meter, the shared viewer.

A *sounds* table (name, file, start, trim, duration, gain, fades) and a *subtitles* table (start, end,
text) read the document snapshot and edit it in place: a cell's text becomes an ``Edit`` through
``core/tables.py`` (so ``update_audio`` / ``update_cue`` validate it), applied as one undo step; a
refused edit shows its reason in the status bar and the cell keeps its value. Selection follows the
shared ``Selection`` both ways - a click on a row selects the sound or subtitle (a subtitle row also
moves the playhead to it), a selection made on the timeline selects the row without moving anything.

The level meter shows the peak and RMS of the mix around the playhead (``core/levels.py``); it follows
every seek and playback tick and every edit while the page is shown. The subtitle style is in the shared
Properties panel (select a subtitle), and the timeline sits below, as on every page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core import audio, edits, levels, tables
from ...core.schema import AudioClip, Cue
from .. import icons, theme
from . import Page, Shared

ZONES = ((levels.FLOOR_DB, -18.0, "success"), (-18.0, -6.0, "warning"), (-6.0, 0.0, "danger"))
SCALE_DB = (-60, -40, -20, -10, -6, 0)
MISSING_FILE = "file not found"
UNREADABLE_FILE = "cannot read the file"


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
        if role == Qt.ItemDataRole.ForegroundRole and problem:
            return theme.qcolor(theme.THEME.warning)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            numeric = column.key not in ("name", "path", "text")
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
        self.setMinimumSize(160, 62)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:
        return QSize(320, 70)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        colours = theme.THEME
        scale_h = 14
        bar_h = max(8.0, (self.height() - scale_h - 6) / 2)
        x0, width = 18.0, max(1.0, self.width() - 26.0)
        for row, side in enumerate("LR"):
            top = 2 + row * (bar_h + 2)
            painter.fillRect(QRectF(x0, top, width, bar_h), theme.qcolor(colours.track))
            for low, high, token in ZONES:  # the RMS, zone by zone
                reach = min(self.level.rms_db[row], high)
                if reach > low:
                    left = x0 + width * levels.fraction(low)
                    painter.fillRect(
                        QRectF(left, top, width * (levels.fraction(reach) - levels.fraction(low)), bar_h),
                        theme.qcolor(getattr(colours, token)),
                    )
            peak = self.level.peak_db[row]
            if peak > levels.FLOOR_DB:
                painter.setPen(QPen(theme.qcolor(colours.text), 2))
                px = x0 + width * levels.fraction(peak)
                painter.drawLine(int(px), int(top), int(px), int(top + bar_h))
            painter.setPen(theme.qcolor(colours.muted))
            painter.drawText(QRectF(0, top, x0 - 4, bar_h), Qt.AlignmentFlag.AlignCenter, side)
        painter.setPen(theme.qcolor(colours.muted))
        base = 2 + 2 * (bar_h + 2)
        for db in SCALE_DB:
            px = x0 + width * levels.fraction(db)
            painter.drawText(QRectF(px - 16, base, 32, scale_h), Qt.AlignmentFlag.AlignCenter, str(db))
        painter.end()


class LevelMeter(QWidget):
    """The mix's level at the playhead: bars and a readout (``readout()``)."""

    def __init__(self) -> None:
        super().__init__()
        self.level = levels.SILENCE
        title = QLabel("Level at the playhead")
        title.setProperty("role", "section")
        self.bars = LevelBars()
        self.label = QLabel()
        self.label.setObjectName("levelReadout")
        self.label.setFont(theme.mono_font())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE * 2, theme.SPACE, theme.SPACE * 2, theme.SPACE)
        layout.addWidget(title)
        layout.addWidget(self.bars)
        layout.addWidget(self.label)
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
        self.cues_model = RowsModel(self, tables.CUE_COLUMNS, self._cues, tables.cue_cell, tables.cue_edit)
        self.sounds = self._table(self.sounds_model)
        self.cues = self._table(self.cues_model)
        header = self.sounds.horizontalHeader()  # names and files share the room, numbers fit their text
        for column in range(self.sounds_model.columnCount()):
            fits = column > 1
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents if fits else QHeaderView.ResizeMode.Stretch
            )
        self.cues.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.sounds.selectionModel().currentRowChanged.connect(self._sound_row_chosen)
        self.cues.selectionModel().currentRowChanged.connect(self._cue_row_chosen)
        self.cues.clicked.connect(self._cue_clicked)
        self.import_sound_button = self._button("Import", "open", "Import a sound at the playhead")
        self.delete_sound_button = self._button("Delete", "delete", "Delete the selected sound")
        self.play_button = self._button("Play from here", "play", "Play the video from the playhead")
        self.add_cue_button = self._button("Add at playhead", "add", "A subtitle at the playhead (Ctrl+T)")
        self.delete_cue_button = self._button("Delete", "delete", "Delete the selected subtitle")
        self.import_srt_button = self._button(
            "Import .srt", "open", "Replace the subtitles with an .srt file"
        )
        self.export_srt_button = self._button("Export .srt", "export", "Write the subtitles to an .srt file")
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

        self.tables = QSplitter(Qt.Orientation.Vertical)
        self.tables.addWidget(
            self._box(
                "Sounds",
                self.sounds,
                (self.import_sound_button, self.delete_sound_button, self.play_button),
            )
        )
        self.tables.addWidget(
            self._box(
                "Subtitles",
                self.cues,
                (
                    self.add_cue_button,
                    self.delete_cue_button,
                    self.import_srt_button,
                    self.export_srt_button,
                ),
            )
        )
        self.centre = QSplitter(Qt.Orientation.Vertical)  # the viewer (placed), the meter
        self.centre.addWidget(self.meter)
        self.top = QSplitter(Qt.Orientation.Horizontal)  # tables | viewer and meter | Properties (placed)
        self.top.addWidget(self.tables)
        self.top.addWidget(self.centre)
        self.top.setChildrenCollapsible(False)
        self.outer = QSplitter(Qt.Orientation.Vertical)
        self.outer.addWidget(self.top)
        self.outer.setChildrenCollapsible(False)
        return self.outer

    # -- building --------------------------------------------------------------------------

    def _table(self, model: RowsModel) -> QTableView:
        view = QTableView()
        view.setModel(model)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        view.setAlternatingRowColors(True)
        view.setWordWrap(False)
        view.verticalHeader().hide()
        view.verticalHeader().setDefaultSectionSize(26)
        view.horizontalHeader().setHighlightSections(False)
        view.horizontalHeader().setMinimumSectionSize(56)
        view.setMinimumHeight(90)
        return view

    def _button(self, text: str, icon: str, tip: str) -> QPushButton:
        button = QPushButton(icons.icon(icon), text)
        button.setToolTip(tip)
        button.setAccessibleName(text)
        return button

    def _box(self, title: str, view: QTableView, buttons: tuple[QPushButton, ...]) -> QGroupBox:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(theme.SPACE * 2, theme.SPACE * 4, theme.SPACE * 2, theme.SPACE * 2)
        row = QHBoxLayout()
        for button in buttons:
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(view, 1)
        return box

    def place(self, shared: Shared) -> None:
        self.centre.insertWidget(0, shared.viewer)
        self.top.insertWidget(2, shared.properties)
        self.outer.insertWidget(1, shared.timeline)
        self.centre.setStretchFactor(0, 1)
        self.centre.setStretchFactor(1, 0)
        for i, stretch in enumerate((0, 1, 0)):
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
            tables_w, properties_w = int(width * 0.46), 300  # first show: the tables get the room
            self.top.setSizes([tables_w, max(width - tables_w - properties_w, 300), properties_w])
            self.outer.setSizes([int(height * 0.6), int(height * 0.4)])
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

    def _on_changed(self, *_args) -> None:
        self.refresh()

    def _on_playhead(self, _t: float) -> None:
        if self._active:
            self.refresh_meter()

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
