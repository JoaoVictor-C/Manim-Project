"""The open project: current snapshot, undo history, change notification (ADR 0014).

Edits are made with ``core.edits`` and handed to the ``Document``:

* ``apply(edit, text)`` — commit one undoable step;
* ``begin_preview()`` / ``preview(edit)`` / ``commit_preview(text)`` /
  ``cancel_preview()`` — a drag: any number of previews, then one undo step
  (or none, if cancelled).

Every change of the current snapshot emits ``changed(project, layer_ids, kind)``
so the evaluator, canvas and timeline can update. Undo and redo emit the kind of
the reverse change, computed by diffing, so undoing a drag is as cheap as one
drag step (ADR 0013).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from ..core import edits
from ..core.schema import Project
from ..logging_config import get_logger

log = get_logger(__name__)


class _SnapshotCommand(QUndoCommand):
    def __init__(self, document: Document, before: Project, after: Project, text: str, applied: bool) -> None:
        super().__init__(text)
        self._document, self._before, self._after = document, before, after
        self._skip_first_redo = applied  # a committed preview is already current

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._document._set(self._after)

    def undo(self) -> None:
        self._document._set(self._before)


class Document(QObject):
    changed = Signal(object, object, str)  # project, frozenset of layer ids, edit kind
    reset = Signal(object)  # a new project replaced the old one (open)
    dragFinished = Signal()  # a drag was committed or cancelled

    def __init__(self, project: Project, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._drag_start: Project | None = None
        self.undo_stack = QUndoStack(self)

    @property
    def project(self) -> Project:
        return self._project

    @property
    def dragging(self) -> bool:
        return self._drag_start is not None

    # -- whole-document changes -----------------------------------------------

    def replace(self, project: Project) -> None:
        """Open another project: history is cleared, observers rebuild."""
        self.cancel_preview()
        self.undo_stack.clear()
        self._project = project
        self.undo_stack.setClean()
        self.reset.emit(project)

    # -- committed edits ------------------------------------------------------

    def apply(self, edit: edits.Edit, text: str) -> None:
        """Commit ``edit`` as one undo step (none if it changes nothing)."""
        if self.dragging:
            raise RuntimeError("finish or cancel the drag before applying another edit")
        if edit.project == self._project:
            return
        self.undo_stack.push(_SnapshotCommand(self, self._project, edit.project, text, applied=False))

    # -- drags ---------------------------------------------------------------

    def begin_preview(self) -> None:
        if self.dragging:
            raise RuntimeError("a drag is already in progress")
        self._drag_start = self._project

    def preview(self, edit: edits.Edit) -> None:
        """Show ``edit`` without recording it (call between begin and commit/cancel)."""
        if not self.dragging:
            raise RuntimeError("preview() outside a drag; call begin_preview() first")
        self._set(edit.project)

    def commit_preview(self, text: str) -> None:
        """End the drag: one undo step from the drag start to the current snapshot."""
        before = self._drag_start
        self._drag_start = None
        if before is None:
            return
        if before is not self._project:
            self.undo_stack.push(_SnapshotCommand(self, before, self._project, text, applied=True))
        self.dragFinished.emit()

    def cancel_preview(self) -> None:
        """End the drag and restore the snapshot it started from."""
        before = self._drag_start
        self._drag_start = None
        if before is not None:
            self._set(before)
            self.dragFinished.emit()

    # -- internal -------------------------------------------------------------

    def _set(self, project: Project) -> None:
        if project is self._project:
            return
        kind, layer_ids = edits.classify(self._project, project)
        self._project = project
        log.debug("document changed: %s %s", kind, sorted(layer_ids))
        self.changed.emit(project, layer_ids, kind)
