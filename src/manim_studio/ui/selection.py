"""What is selected: one layer, optionally one of its clips (S3, ADR 0016).

The single source of truth for the canvas, the Layers panel, the timeline and
the Properties panel. Views report user choices to it and follow ``changed``.
It drops what disappears from the document (a deleted clip leaves its layer
selected; a deleted layer clears the selection) and clears on New/Open.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .document import Document


class Selection(QObject):
    changed = Signal()

    def __init__(self, document: Document, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.layer_id: str | None = None
        self.clip_id: str | None = None
        document.changed.connect(lambda *_: self._drop_missing())
        document.reset.connect(lambda _project: self.clear())

    def set(self, layer_id: str | None, clip_id: str | None = None) -> None:
        if not layer_id:
            layer_id = clip_id = None
        if (layer_id, clip_id) == (self.layer_id, self.clip_id):
            return
        self.layer_id, self.clip_id = layer_id, clip_id
        self.changed.emit()

    def select_layer(self, layer_id: str | None) -> None:
        """Select a layer; a clip of that same layer stays selected."""
        if layer_id and layer_id == self.layer_id:
            return
        self.set(layer_id)

    def clear(self) -> None:
        self.set(None)

    def _drop_missing(self) -> None:
        if self.layer_id is None:
            return
        layer = next((lay for lay in self.document.project.layers if lay.id == self.layer_id), None)
        if layer is None:
            self.clear()
        elif self.clip_id is not None and all(c.id != self.clip_id for c in layer.clips):
            self.set(self.layer_id)
