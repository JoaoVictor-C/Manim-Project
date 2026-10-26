"""The Code page's chapter commands (ADR 0061): Analyse scene, Split into chapters, Move selection.

*Analyse* reads the scene's code and what its last render recorded and says where it can be cut. *Split*
replaces the layer by one layer per chapter (one undo step), waits for them to render, then compares every
frame with the full render in a background thread; if one differs the split is undone and the message says
which. *Move selection* gives the selected statements a layer of their own: the user declared them
independent, so nothing is compared. Nothing here renders or imports Manim.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ...core.code import scene_analysis, scene_split
from ...core.code.code_cache import CodeClip
from ...core.code.scene_analysis import Analysis
from ...core.editing import edits
from ...core.model.schema import CODE_TYPES
from ..style import theme
from ..style.card import Chip
from .code_chrome import chip_font, paint_chip
from .dialog_frame import DialogFrame

if TYPE_CHECKING:
    from ..pages.code import CodePage


EMPTY = "Run the scene: its chapters - the parts that can render separately - are listed here."


class ReportDialog(QDialog):
    """The analysis as text, with the button that acts on it."""

    def __init__(self, title: str, text: str, can_split: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 460)
        frame = DialogFrame(self, "chapters", title, "Where this scene can be cut into chapters")
        self.report = QPlainTextEdit(text)
        self.report.setReadOnly(True)
        self.report.setFont(theme.mono_font())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.split_button = buttons.addButton("Split into chapters", QDialogButtonBox.ButtonRole.AcceptRole)
        self.split_button.setEnabled(can_split)
        self.split_button.setToolTip(
            "Replace the layer by one layer per chapter, render them and check every frame against the "
            "full render; if one differs, the split is undone"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        frame.body.addWidget(self.report)
        frame.add_buttons(buttons)


NUMBER_ROLE = Qt.ItemDataRole.UserRole
DETAIL_ROLE = Qt.ItemDataRole.UserRole + 1
CHIP_ROLE = Qt.ItemDataRole.UserRole + 2


def _clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def chapter_rows(analysis: Analysis | None) -> list[tuple[int, str, str, str]]:
    """(number, title, detail, chip) for each chapter of ``analysis``: the first statement names it, the
    detail says its lines and times, the chip its frames."""
    if analysis is None or not analysis.ok or not analysis.chapters:
        return []
    rows = []
    fps = analysis.fps or 1
    for number, chapter in enumerate(analysis.chapters, 1):
        statements = analysis.statements[chapter.first : chapter.end]
        if not statements:
            continue
        first, last = statements[0].first_line, statements[-1].last_line
        end_frame = chapter.end_frame if chapter.end_frame is not None else analysis.total_frames
        start = chapter.start_time if chapter.start_time else chapter.start_frame / fps
        end = start + (end_frame - chapter.start_frame) / fps
        detail = f"lines {first} – {last} · {_clock(start)} – {_clock(end)}"
        frames = end_frame - chapter.start_frame
        rows.append((number, statements[0].text, detail, f"{frames} frames"))
    return rows


class _ChapterDelegate(QStyledItemDelegate):
    """A chapter as a raised row: its number in the accent, the first statement, lines and times, frames."""

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), 52)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        colours = theme.THEME
        rect = QRectF(option.rect).adjusted(0, 0, 0, -6)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QPen(theme.qcolor(colours.accent_line if selected else colours.line), 1))
        painter.setBrush(theme.qcolor(colours.accent_soft if selected else colours.raised))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS_ROW, theme.RADIUS_ROW)
        number = theme.font("label", kind="mono")
        number.setBold(True)
        painter.setFont(number)
        painter.setPen(theme.qcolor(colours.accent_text))
        painter.drawText(
            QRectF(rect.left() + 12, rect.top(), 20, rect.height()),
            Qt.AlignmentFlag.AlignVCenter,
            str(index.data(NUMBER_ROLE)),
        )
        right = rect.right() - 10
        chip = str(index.data(CHIP_ROLE) or "")
        if chip:
            width = QFontMetricsF(chip_font()).horizontalAdvance(chip) + 14
            box = QRectF(right - width, rect.center().y() - 9, width, 18)
            paint_chip(painter, box, chip)
            right = box.left() - 8
        left = rect.left() + 36
        title = theme.font("label")
        title.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title)
        painter.setPen(theme.qcolor(colours.text))
        text = painter.fontMetrics().elidedText(
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""), Qt.TextElideMode.ElideRight, int(right - left)
        )
        painter.drawText(QRectF(left, rect.top() + 6, right - left, 18), Qt.AlignmentFlag.AlignVCenter, text)
        painter.setFont(theme.font("caption"))
        painter.setPen(theme.qcolor(colours.faint))
        detail = painter.fontMetrics().elidedText(
            str(index.data(DETAIL_ROLE) or ""), Qt.TextElideMode.ElideRight, int(right - left)
        )
        painter.drawText(
            QRectF(left, rect.top() + 24, right - left, 16), Qt.AlignmentFlag.AlignVCenter, detail
        )
        painter.restore()


class ChaptersPanel(QWidget):
    """The Chapters card's body (ADR 0061): the chapters the last render of the scene allows, or why none."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chaptersPanel")
        self.count_chip = Chip("", "neutral")
        self.count_chip.hide()
        self.list = QListWidget()
        self.list.setObjectName("codeChapters")
        self.list.setItemDelegate(_ChapterDelegate(self.list))
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.empty = QLabel(EMPTY)
        self.empty.setObjectName("chaptersEmpty")
        self.empty.setWordWrap(True)
        self.empty.setProperty("role", "hint")
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 8)
        column.setSpacing(4)
        column.addWidget(self.empty)
        column.addWidget(self.list, 1)
        self.rows: list[tuple[int, str, str, str]] = []
        self.show_analysis(None)

    def show_analysis(self, analysis: Analysis | None) -> None:
        rows = chapter_rows(analysis)
        if analysis is not None and analysis.ok and not rows:
            note = "No cut point: the scene is one chapter." if analysis.total_frames else EMPTY
        elif analysis is not None and not analysis.ok:
            note = f"Not analysed: {analysis.problem}"
        else:
            note = EMPTY
        self.empty.setText(note)
        self.empty.setVisible(not rows)
        self.list.setVisible(bool(rows))
        self.count_chip.setText(str(len(rows)))
        self.count_chip.setVisible(bool(rows))
        if rows == self.rows:
            return
        self.rows = rows
        self.list.clear()
        for number, title, detail, chip in rows:
            item = QListWidgetItem(title)
            item.setData(NUMBER_ROLE, number)
            item.setData(DETAIL_ROLE, detail)
            item.setData(CHIP_ROLE, chip)
            item.setToolTip(f"Chapter {number}: {title} ({detail})")
            self.list.addItem(item)


class _Check(QRunnable):
    """Compares a full render with its chapters off the UI thread."""

    def __init__(self, whole: CodeClip, chapters: list[tuple[CodeClip, int]], done) -> None:
        super().__init__()
        self.whole, self.chapters, self.done = whole, chapters, done
        self.stop = False

    def run(self) -> None:
        # fresh readers: the editor paints from the shared ones on its own thread
        whole = CodeClip(self.whole.folder)
        chapters = [(CodeClip(clip.folder), start) for clip, start in self.chapters]
        try:
            verdict = scene_split.verify(whole, chapters, should_stop=lambda: self.stop)
        except Exception as error:  # a vanished cache folder, a bad read: not a pass
            verdict = scene_split.Verdict(False, message=f"could not compare the renders: {error}")
        self.done(verdict)


class ChapterVerifier(QObject):
    """Waits for the chapter layers to render, compares them with the full render, undoes a bad split."""

    finished = Signal(object)  # scene_split.Verdict
    _result = Signal(object)  # from the comparing thread to this one

    def __init__(self, window, whole: CodeClip, layers: list[tuple[str, int]], applied, label: str) -> None:
        super().__init__(window)
        self.window, self.whole, self.layers, self.applied, self.label = window, whole, layers, applied, label
        self.verdict: scene_split.Verdict | None = None
        self._started = False
        self._check: _Check | None = None
        self._result.connect(self._finish)
        window.code.statusChanged.connect(self.poll)
        self.poll()

    def poll(self, _layer_id: str = "") -> None:
        if self._started or self.verdict is not None:
            return
        project = self.window.project
        if project is None or any(i not in {x.id for x in project.layers} for i, _ in self.layers):
            self._finish(
                scene_split.Verdict(False, message="the chapters were changed or removed"), undo=False
            )
            return
        clips = []
        for number, (layer_id, start) in enumerate(self.layers, 1):
            status = self.window.code.status(layer_id)
            if status is None or status.state in ("queued", "rendering", "untrusted", "checking"):
                return
            if status.state != "ready":
                reason = status.error or status.state
                self._finish(
                    scene_split.Verdict(False, message=f"chapter {number} did not render ({reason})")
                )
                return
            clip = self.window.code.cache.open(self.window.evaluator.code_key(project.layer(layer_id)))
            if clip is None:
                return
            clips.append((clip, start))
        self._started = True
        self.window.statusBar().showMessage(f"{self.label}: comparing every frame with the full render...")
        self._check = _Check(self.whole, clips, self._thread_done)
        QThreadPool.globalInstance().start(self._check)

    def _thread_done(self, verdict) -> None:
        self._result.emit(verdict)  # queued: handled on the UI thread

    def _finish(self, verdict, undo: bool = True) -> None:
        if self.verdict is not None:
            return
        self.verdict = verdict
        with contextlib.suppress(RuntimeError, TypeError):
            self.window.code.statusChanged.disconnect(self.poll)
        if verdict.ok:
            self.window.statusBar().showMessage(f"{self.label}: verified, {verdict.message}", 12000)
        elif undo and self.window.document.project is self.applied:
            self.window.document.undo_stack.undo()
            self.window.statusBar().showMessage(
                f"{self.label} undone: {verdict.message}. Cutting this scene changes what it draws", 20000
            )
        else:
            self.window.statusBar().showMessage(
                f"{self.label}: {verdict.message}. Undo if the picture is not what you expect", 20000
            )
        self.finished.emit(verdict)

    def cancel(self) -> None:
        if self._check is not None:
            self._check.stop = True


class ChapterActions:
    """The page's chapter commands; ``page`` is the Code page."""

    def __init__(self, page: CodePage) -> None:
        self.page = page
        self.verifier: ChapterVerifier | None = None
        self._quiet: tuple[tuple, Analysis | None] | None = None  # (what it was read from, the analysis)

    def quiet_analysis(self) -> Analysis | None:
        """The analysis of the scene in the editor for the Chapters card, or None - saying nothing when there
        is none (the commands below explain why). Read again only when the code or its render changed."""
        page, window = self.page, self.window
        project = window.project
        layer_id = page.layer_id
        layer = None if project is None else next((x for x in project.layers if x.id == layer_id), None)
        if layer is None or layer.spec is None or layer.spec.type not in CODE_TYPES:
            return None
        status = page.status(layer_id)
        if status is None or status.state != "ready":
            return None
        code = str(layer.spec.params.get("code", ""))
        key = (layer.id, code, status.frames)
        if self._quiet is not None and self._quiet[0] == key:
            return self._quiet[1]
        try:
            clip = window.code.cache.open(window.evaluator.code_key(layer))
        except (OSError, ValueError, KeyError):
            clip = None
        result = None
        if clip is not None:
            try:
                result = scene_analysis.analyse(code, clip.probes, clip.fps, clip.frame_count)
            except (SyntaxError, ValueError):
                result = None
        self._quiet = (key, result)
        return result

    @property
    def window(self):
        return self.page.window

    def _say(self, text: str, ms: int = 9000) -> None:
        self.window.statusBar().showMessage(text, ms)

    def _scene(self):
        """(layer, key, clip) of the layer in the editor if it is a rendered scene; else None, saying why."""
        page, window = self.page, self.window
        layer_id = page.layer_id
        project = window.project
        if layer_id is None or project is None or page.preset_id is not None:
            self._say("Choose a code layer first")
            return None
        layer = next((x for x in project.layers if x.id == layer_id), None)
        if layer is None or layer.spec is None or layer.spec.type not in CODE_TYPES:
            self._say("Chapters work on a scene (a code layer)")
            return None
        if page.is_dirty():
            self._say("Run the scene first: the analysis reads what was rendered")
            return None
        key = window.evaluator.code_key(layer)
        clip = window.code.cache.open(key)
        if clip is None:
            self._say("Render the scene first (Run), then analyse it")
            return None
        return layer, key, clip

    def analysis(self) -> tuple[Analysis, object, CodeClip] | None:
        found = self._scene()
        if found is None:
            return None
        layer, _key, clip = found
        code = str(layer.spec.params.get("code", ""))
        return scene_analysis.analyse(code, clip.probes, clip.fps, clip.frame_count), layer, clip

    def analyse(self) -> ReportDialog | None:
        """Editor > Analyse scene...: where the scene can be cut, and why not elsewhere."""
        found = self.analysis()
        if found is None:
            return None
        result, layer, _clip = found
        dialog = ReportDialog(f"Analyse {layer.label}", result.report(), result.splittable, self.page.widget)
        dialog.accepted.connect(self.split)
        dialog.show()
        self.dialog = dialog
        return dialog

    def split(self) -> bool:
        """Editor > Split into chapters...: replace the layer by its chapters, then prove it."""
        found = self.analysis()
        if found is None:
            return False
        result, layer, clip = found
        if not result.splittable:
            self._say(
                "This scene has no valid cut point: " + (result.notes[0] if result.notes else "see Analyse")
            )
            return False
        window = self.window
        code = str(layer.spec.params.get("code", ""))
        chapters = scene_split.chapter_codes(code, result)
        window.trust.trust([c.code for c in chapters])  # cut from code the user ran
        edit = edits.split_code_layer(
            window.project, layer.id, [(c.code, c.start_frame, c.start_time, c.name) for c in chapters]
        )
        before = {x.id for x in window.project.layers}
        window.document.apply(edit, f"Split {layer.label} into {len(chapters)} chapters")
        applied = window.document.project
        new_ids = [x.id for x in applied.layers if x.id not in before]
        if self.verifier is not None:
            self.verifier.cancel()
        self.verifier = ChapterVerifier(
            window,
            clip,
            list(zip(new_ids, [c.start_frame for c in chapters], strict=True)),
            applied,
            f"Split {layer.label} into {len(chapters)} chapters",
        )
        self._say(f"Split into {len(chapters)} chapters: rendering them to check...", 15000)
        return True

    def move_selection(self) -> bool:
        """Editor > Move selection to a new layer: the selected statements get a layer of their own."""
        page, window = self.page, self.window
        layer_id = page.layer_id
        project = window.project
        layer = next((x for x in project.layers if x.id == layer_id), None) if project and layer_id else None
        if layer is None or layer.spec is None or layer.spec.type not in CODE_TYPES or page.preset_id:
            self._say("Select statements in a scene (a code layer) first")
            return False
        if page.is_dirty():
            self._say("Run the scene first: the move works on the applied code")
            return False
        cursor = page.editor.textCursor()
        if not cursor.hasSelection():
            self._say("Select the statements of construct to move, then use this command")
            return False
        document = page.editor.document()
        first = document.findBlock(cursor.selectionStart()).blockNumber() + 1
        last = document.findBlock(cursor.selectionEnd()).blockNumber() + 1
        moved = scene_split.move_selection(page.editor.text(), first, last)
        if moved.problem:
            self._say(f"Cannot move: {moved.problem}")
            return False
        window.trust.trust([moved.kept, moved.moved])
        edit = edits.move_code_to_new_layer(window.project, layer.id, moved.kept, moved.moved)
        window.document.apply(edit, f"Move selection of {layer.label} to a new layer")
        note = " Warning: " + "; ".join(moved.warnings) if moved.warnings else ""
        self._say("Moved the selection to a new layer: the two render separately." + note, 15000)
        return True
