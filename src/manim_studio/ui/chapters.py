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

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

from ..core import edits, scene_analysis, scene_split
from ..core.code_cache import CodeClip
from ..core.scene_analysis import Analysis
from ..core.schema import CODE_TYPES

if TYPE_CHECKING:
    from .pages.code import CodePage


class ReportDialog(QDialog):
    """The analysis as text, with the button that acts on it."""

    def __init__(self, title: str, text: str, can_split: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 460)
        self.report = QPlainTextEdit(text)
        self.report.setReadOnly(True)
        self.report.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.split_button = buttons.addButton("Split into chapters", QDialogButtonBox.ButtonRole.AcceptRole)
        self.split_button.setEnabled(can_split)
        self.split_button.setToolTip(
            "Replace the layer by one layer per chapter, render them and check every frame against the "
            "full render; if one differs, the split is undone"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.report)
        layout.addWidget(buttons)


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
