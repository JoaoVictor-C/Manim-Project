"""What is selected: one layer, optionally one of its clips or key times (S3, P2b).

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
        self.key_time: float | None = None  # all keys of the layer at this time (P2b)
        self.audio_id: str | None = None  # a sound instead of a layer (ADR 0034)
        self.subtitle_id: str | None = None  # a subtitle instead of a layer (ADR 0035)
        document.changed.connect(lambda *_: self._drop_missing())
        document.reset.connect(lambda _project: self.clear())

    def set(self, layer_id: str | None, clip_id: str | None = None, key_time: float | None = None) -> None:
        if not layer_id:
            layer_id = clip_id = key_time = None
        if clip_id is not None:
            key_time = None  # a clip or a key time, not both
        now = (self.layer_id, self.clip_id, self.key_time, self.audio_id, self.subtitle_id)
        if (layer_id, clip_id, key_time, None, None) == now:
            return
        self.layer_id, self.clip_id, self.key_time = layer_id, clip_id, key_time
        self.audio_id = self.subtitle_id = None
        self.changed.emit()

    def set_audio(self, audio_id: str | None) -> None:
        """Select a sound (or nothing): no layer is selected then."""
        if not audio_id:
            self.clear()
            return
        if (self.layer_id, self.audio_id, self.subtitle_id) == (None, audio_id, None):
            return
        self.layer_id = self.clip_id = self.key_time = self.subtitle_id = None
        self.audio_id = audio_id
        self.changed.emit()

    def set_subtitle(self, cue_id: str | None) -> None:
        """Select a subtitle (or nothing): no layer is selected then."""
        if not cue_id:
            self.clear()
            return
        if (self.layer_id, self.audio_id, self.subtitle_id) == (None, None, cue_id):
            return
        self.layer_id = self.clip_id = self.key_time = self.audio_id = None
        self.subtitle_id = cue_id
        self.changed.emit()

    def set_key(self, layer_id: str, key_time: float) -> None:
        self.set(layer_id, None, key_time)

    def select_layer(self, layer_id: str | None) -> None:
        """Select a layer; a clip or key time of that same layer stays selected."""
        if layer_id and layer_id == self.layer_id:
            return
        self.set(layer_id)

    def clear(self) -> None:
        self.set(None)

    def _drop_missing(self) -> None:
        if self.audio_id is not None and all(c.id != self.audio_id for c in self.document.project.audio):
            self.clear()
        if self.subtitle_id is not None and all(
            c.id != self.subtitle_id for c in self.document.project.subtitles
        ):
            self.clear()
        if self.layer_id is None:
            return
        layer = next((lay for lay in self.document.project.layers if lay.id == self.layer_id), None)
        if layer is None:
            self.clear()
        elif self.clip_id is not None and all(c.id != self.clip_id for c in layer.clips):
            self.set(self.layer_id)
        elif self.key_time is not None:
            half_frame = 0.5 / self.document.project.canvas.fps
            keyed = any(
                abs(k.t - self.key_time) < half_frame for track in layer.tracks.values() for k in track
            )
            if not keyed:
                self.set(self.layer_id)
