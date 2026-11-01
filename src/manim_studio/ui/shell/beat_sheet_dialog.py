"""Edit > Beat Sheet...: the video as beats, each with a picture, what appears, is said and heard (ADR 0073).

Beats are spans between markers. Double-clicking a beat moves the playhead there; the sheet can be copied as
Markdown. It only reads the project: pictures are drawn small, one per tick, so the window opens at once.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QListWidgetItem, QPushButton, QWidget

from ...core.editing import beat_sheet
from ...core.engine.evaluator import Evaluator
from ...core.model.schema import Project
from ...render.cairo_export import make_camera, render_frame
from ..style.dialog_chrome import DialogFrame

PICTURE_WIDTH = 192


def picture(project: Project, t: float) -> QPixmap:
    """The frame at ``t``, small."""
    canvas = project.canvas
    height = max(1, round(PICTURE_WIDTH * canvas.height_px / canvas.width_px))
    small = project.model_copy(
        update={"canvas": canvas.model_copy(update={"width_px": PICTURE_WIDTH, "height_px": height})}
    )
    frame = np.ascontiguousarray(
        render_frame(
            make_camera(small.canvas, small.camera, small.view_background), Evaluator(small).frame(t)
        )
    )
    rows, columns, _ = frame.shape
    return QPixmap.fromImage(
        QImage(frame.data, columns, rows, columns * 4, QImage.Format.Format_RGBA8888).copy()
    )


def describe(row: beat_sheet.Row) -> str:
    beat = row.beat
    lines = [
        f"{beat.name}   {beat_sheet.clock(beat.start)} - {beat_sheet.clock(beat.end)}  ({beat.length:g} s)"
    ]
    if row.appears:
        lines.append("Appears: " + ", ".join(row.appears))
    lines += [f'Says: "{text}"' for text in row.said]
    if row.sounds:
        lines.append("Sound: " + ", ".join(row.sounds))
    return "\n".join(lines)


class BeatSheetDialog(QDialog):
    def __init__(
        self,
        current: Callable[[], Project],
        seek: Callable[[float], None],
        title: str = "Beat sheet",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Beat sheet")
        self.current, self._seek, self.title = current, seek, title
        self.frame = DialogFrame(
            self,
            "chapters",
            "Beat sheet",
            "The video beat by beat, between your markers. Double-click a beat to go there.",
        )
        self.list = QListWidget()
        self.list.setIconSize(QSize(PICTURE_WIDTH, round(PICTURE_WIDTH * 9 / 16)))
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self.go)
        self.frame.body.addWidget(self.list)
        self.rows = beat_sheet.sheet(current())
        for row in self.rows:
            item = QListWidgetItem(describe(row))
            item.setData(Qt.ItemDataRole.UserRole, row.beat.start)
            self.list.addItem(item)
        if not self.rows:
            self.list.addItem("Nothing to show yet.")
        copy = self.frame.add_left(QPushButton("Copy as Markdown"))
        copy.clicked.connect(self.copy_markdown)
        close = self.frame.add_button("Close")
        close.clicked.connect(self.close)
        self.resize(560, 520)
        self._next = 0

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._draw_next)

    def _draw_next(self) -> None:
        if self._next >= len(self.rows) or not self.isVisible():
            return
        row = self.rows[self._next]
        self.list.item(self._next).setIcon(QIcon(picture(self.current(), row.thumbnail_time)))
        self._next += 1
        QTimer.singleShot(0, self._draw_next)

    def go(self, item: QListWidgetItem | None = None) -> None:
        item = item or self.list.currentItem()
        start = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if start is not None:
            self._seek(float(start))

    def markdown(self) -> str:
        return beat_sheet.to_markdown(self.current(), self.title)

    def copy_markdown(self) -> None:
        QApplication.clipboard().setText(self.markdown())
