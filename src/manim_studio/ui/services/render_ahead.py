"""Frames rendered ahead of the playhead, kept for the canvas (P3f, ADR 0028).

``RenderAhead`` owns the ``FrameStore`` and talks to the preview process:

* a document change drops the frames it can change at once (``changed_spans``)
  and sends the snapshot ``SEND_DELAY_MS`` after the last change, so a drag does
  not flood the process;
* a new framing (zoom, pan, resize, half resolution) clears the store;
* it asks for the next ``BATCH`` missing frames from the playhead, and asks
  again as frames arrive, after an invalidation, or when the playhead moves;
* ``image(t)`` is the kept frame at ``t`` as a QImage, or None (render live).

Without a process (``client`` None) it keeps nothing and the canvas renders live.
"""

from __future__ import annotations

import zlib

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from ...core.engine.frame_cache import (
    FrameStore,
    changed_spans,
    frame_count,
    frame_index,
    layer_spans,
    on_grid,
    span_indices,
)
from ...core.model.schema import Project
from ...logging_config import get_logger
from ...render.preview import PreviewView
from .preview_client import PreviewProcess

log = get_logger(__name__)

SEND_DELAY_MS = 150
BATCH = 60  # frames asked for at a time
REFILL_BELOW = 20  # ask again when fewer than this are on the way


class RenderAhead(QObject):
    progress = Signal()  # frames were kept or dropped

    def __init__(self, client: PreviewProcess | None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = FrameStore()
        self.client = client
        self._project: Project | None = None
        self._view: PreviewView | None = None
        self._playhead = 0
        self._asked: set[int] = set()  # requested, not arrived
        self._failed: set[int] = set()  # the process could not render them: live until they change
        # (view, index, the kept bytes, image): repaints without a seek; the bytes themselves are
        # compared, so a frame rendered again after an edit is decoded again (P7.1: a key "stopped working")
        self._decoded: tuple[int, int, bytes, QImage] | None = None
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.setInterval(SEND_DELAY_MS)
        self._send_timer.timeout.connect(self._send_project)
        if client is not None:
            client.frame.connect(self._on_frame)
            client.failed.connect(self._on_failed)
            client.availableChanged.connect(lambda available: available or self.stop())

    @property
    def active(self) -> bool:
        return self.client is not None and self.client.available

    def stop(self) -> None:
        """No more frames ahead (the window closes, or Render Ahead is turned off)."""
        if self.client is not None:
            self.client.stop()
            self.client = None
        self.store.invalidate_all()
        self._decoded = None
        self.progress.emit()

    # -- what changed -------------------------------------------------------------

    def reset(self, project: Project) -> None:
        """A project was opened."""
        self._project = project
        self.store.total = max(1, frame_count(project))
        self.store.invalidate_all()
        self._forget()
        self._send_project()
        self._request()

    def changed(self, project: Project) -> None:
        """An edit, undo or redo: drop what it changes now, tell the process soon."""
        if self._project is None:
            return self.reset(project)
        spans = changed_spans(self._project, project)
        self._project = project
        self.store.total = max(1, frame_count(project))
        if spans is None:
            self.store.invalidate_all()
            self._forget()
        elif spans:
            self._drop(span_indices(spans, project.canvas.fps, self.store.total))
        else:
            return
        self._send_timer.start()
        self._request()

    def layers_changed(self, layer_ids: set[str], media: bool = False) -> None:
        """Frames of these layers changed without a project edit (code rendered, media read)."""
        if self._project is None or not layer_ids:
            return
        spans = layer_spans(self._project, layer_ids)
        self._drop(span_indices(spans, self._project.canvas.fps, self.store.total))
        if media and self.active:
            self.client.media()
        self._send_project()  # its frames now need this generation: the same project, newer
        self._request()

    def set_view(self, view: PreviewView) -> None:
        if view == self._view:
            return
        self._view = view
        self.store.set_view(self.store.view + 1)
        self._forget()
        if self.active:
            self.client.send_view(self.store.view, view)
        self._request()

    def set_playhead(self, t: float) -> None:
        if self._project is None:
            return
        index = frame_index(t, self._project.canvas.fps)
        if index != self._playhead:
            self._playhead = index
            if index not in self._asked:
                self._request()

    # -- frames --------------------------------------------------------------------

    def image(self, t: float) -> QImage | None:
        """The kept frame at ``t`` for the current view, or None."""
        if self._project is None or self._view is None or not on_grid(t, self._project.canvas.fps):
            return None
        index = frame_index(t, self._project.canvas.fps)
        data = self.store.get(index)
        if data is None:
            return None
        decoded = self._decoded
        if decoded is not None and decoded[:2] == (self.store.view, index) and decoded[2] is data:
            return decoded[3]  # the same bytes (compared by identity: no copy of megabytes)
        width, height = self._view.pixel_width, self._view.pixel_height
        image = QImage(zlib.decompress(data), width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        self._decoded = (self.store.view, index, data, image)
        return image

    def _on_frame(self, view_id: int, generation: int, index: int, data: bytes, w: int, h: int) -> None:
        self._asked.discard(index)
        sized = self._view is not None and (w, h) == (self._view.pixel_width, self._view.pixel_height)
        if sized and self.store.accept(view_id, generation, index, data, self._playhead):
            self.progress.emit()
        if len(self._asked) < REFILL_BELOW:
            self._request()

    def _on_failed(self, index: int) -> None:
        self._asked.discard(index)
        self._failed.add(index)

    # -- helpers ---------------------------------------------------------------------

    def _drop(self, indices: set[int]) -> None:
        self.store.invalidate(indices)
        self._failed -= indices
        self._asked -= indices
        self.progress.emit()

    def _forget(self) -> None:
        self._asked.clear()
        self._failed.clear()
        self._decoded = None

    def _send_project(self) -> None:
        if self.active and self._project is not None:
            self.client.send_project(self._project, self.store.generation)

    def _request(self) -> None:
        if not self.active or self._project is None or self._view is None:
            return
        candidates = self.store.missing(self._playhead, BATCH + len(self._failed))
        wanted = [i for i in candidates if i not in self._failed][:BATCH]
        self._asked = set(wanted)
        self.client.want(wanted)
