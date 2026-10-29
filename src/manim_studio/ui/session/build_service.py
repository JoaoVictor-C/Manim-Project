"""Warm-then-commit: every UI edit goes through here (ADR 0015).

Panels submit *operations* — callables ``Project -> Edit`` over
``core.edits`` — not finished snapshots. An operation whose result builds no
cold text object is applied at once. Otherwise it waits while the build worker
warms Manim's disk cache, then it is **re-run on the current snapshot** and
committed as one undo step. Re-running is what keeps edits made meanwhile
(or undone meanwhile) intact; an operation that no longer applies — say its
layer was deleted — raises ``EditError`` and is dropped.

* Latest wins: a newer operation with the same ``supersede`` key, e.g.
  ``(layer_id, "params.text")``, replaces a waiting one.
* One worker request per cold key, however many operations wait for it.
* A failed build (bad LaTeX) commits nothing; ``failed`` reports it.
* Nothing is committed in the middle of a timeline drag; waiting operations
  run when the drag ends.
* ``pending_value`` lets a panel keep showing what the user typed.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QObject, Signal

from ...core.editing import edits
from ...core.engine.warm import needs_warm, warm_key
from ...core.model.schema import Project, Spec
from ...logging_config import get_logger
from ..services.worker_process import WorkerClient
from .document import Document

log = get_logger(__name__)

Operation = Callable[[Project], edits.Edit]


@dataclass
class _Pending:
    op: Operation
    text: str
    supersede: Hashable | None
    value: Any
    keys: set[str] = field(default_factory=set)
    merge_key: Hashable | None = None


class BuildService(QObject):
    pendingChanged = Signal()
    failed = Signal(str, str)  # undo text of the dropped edit, message
    checked = Signal(str, bool, str)  # warm key, built, error: a reply to ``check`` (P11)

    def __init__(self, document: Document, client: WorkerClient, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.client = client
        self._warmed: set[str] = set()
        self._failed: dict[str, str] = {}  # keys the worker could not build, and why
        self._inflight: dict[str, int] = {}  # key -> request id
        self._keys: dict[int, str] = {}  # request id -> key
        self._next_id = 1
        self._pending: list[_Pending] = []
        client.replied.connect(self._on_replied)
        client.availableChanged.connect(lambda _available: self._process())
        document.dragFinished.connect(self._process)
        document.reset.connect(lambda _project: self._clear())

    # -- submitting -------------------------------------------------------------

    def submit(
        self,
        op: Operation,
        text: str,
        *,
        supersede: Hashable | None = None,
        value: Any = None,
        merge_key: Hashable | None = None,
    ) -> bool:
        """Apply ``op`` now (True) or once its text objects are warm (False).

        Raises whatever ``op`` raises on the current snapshot (``EditError``,
        ``ValidationError``), so the caller can show the message. With ``merge_key`` the edit extends
        the previous undo step when that carries the same key (Live mode, P13.7).
        """
        edit = op(self.document.project)
        if supersede is not None:
            self._drop(lambda p: p.supersede == supersede)
        keys = self._cold(edit)
        if not keys and not self.document.dragging:
            self.document.apply(edit, text, merge_key, merge_key is not None)
            return True
        self._pending.append(_Pending(op, text, supersede, value, keys, merge_key))
        self._request(keys)
        self.pendingChanged.emit()
        return False

    def preview(self, op: Operation) -> bool:
        """Preview a warm field edit during its drag; cold text edits wait until release."""
        if not self.document.field_edit_preview:
            return False
        edit = op(self.document.project)
        if self._cold(edit):
            return False
        self.document.preview(edit)
        return True

    def prewarm(self, specs: list[Spec]) -> None:
        """Warm objects the user is likely to create (the library defaults)."""
        if self.client.available:
            self._request({k for k in map(warm_key, specs) if k is not None and k not in self._warmed})

    # -- queries ----------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return bool(self._pending)

    def pending_value(self, supersede: Hashable) -> tuple[bool, Any]:
        """``(True, value)`` if an edit for ``supersede`` is waiting, else ``(False, None)``."""
        for pending in reversed(self._pending):
            if pending.supersede == supersede:
                return True, pending.value
        return False, None

    def is_warm(self, spec: Spec) -> bool:
        key = warm_key(spec)
        return key is None or key in self._warmed

    def check(self, spec: Spec, ask: bool = True) -> tuple[bool, str] | None:
        """Whether ``spec`` builds: ``(True, "")`` or ``(False, why)`` when known, else None.

        With ``ask``, an unknown text object is sent to the worker, which warms it for the edit
        that follows; ``checked`` reports the answer. Without a worker nothing is checked ahead."""
        key = warm_key(spec)
        if key is None or key in self._warmed:
            return True, ""
        if key in self._failed:
            return False, self._failed[key]
        if ask and self.client.available:
            self._request({key})
        return None

    # -- internals --------------------------------------------------------------

    def _cold(self, edit: edits.Edit) -> set[str]:
        if not self.client.available:
            return set()
        return needs_warm(self.document.project, edit.project, self._warmed)

    def _request(self, keys: set[str]) -> None:
        for key in sorted(keys - self._inflight.keys()):
            request_id, self._next_id = self._next_id, self._next_id + 1
            self._inflight[key] = request_id
            self._keys[request_id] = key
            self.client.request(request_id, key)

    def _on_replied(self, request_id: int, ok: bool, error: str) -> None:
        key = self._keys.pop(request_id, None)
        if key is None:
            return
        self._inflight.pop(key, None)
        if ok:
            self._warmed.add(key)
        else:
            self._failed[key] = error
            for pending in self._drop(lambda p: key in p.keys):
                log.info("edit %r not applied: %s", pending.text, error)
                self.failed.emit(pending.text, error)
        self.checked.emit(key, ok, error)
        self._process()

    def _process(self) -> None:
        """Re-run waiting operations on the current snapshot; commit those now warm."""
        if self.document.dragging or not self._pending:
            return
        waiting, self._pending = self._pending, []
        for pending in waiting:
            try:
                edit = pending.op(self.document.project)
            except (edits.EditError, ValidationError) as exc:
                log.info("edit %r dropped, no longer applies: %s", pending.text, exc)
                continue
            keys = self._cold(edit)
            if keys:
                pending.keys = keys
                self._request(keys)
                self._pending.append(pending)
            else:
                self.document.apply(edit, pending.text, pending.merge_key, pending.merge_key is not None)
        self.pendingChanged.emit()

    def _drop(self, predicate: Callable[[_Pending], bool]) -> list[_Pending]:
        dropped = [p for p in self._pending if predicate(p)]
        if dropped:
            self._pending = [p for p in self._pending if not predicate(p)]
            self.pendingChanged.emit()
        return dropped

    def _clear(self) -> None:
        if self._pending:
            self._pending = []
            self.pendingChanged.emit()
