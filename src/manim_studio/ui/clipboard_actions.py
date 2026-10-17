"""Edit > Cut / Copy / Paste / Duplicate (P5d, ADR 0038).

A thin Qt layer over ``core.clipboard``: it reads the shared selection, puts the copied
document on the system clipboard (under ``clipboard.MIME_TYPE`` and as plain text, so
another instance can paste it), places pasted clips the way the timeline's Add clip
does (``place_new_clip`` and the obstacles of ADR 0012) and selects what it pasted.
Every action is one undo step; pasted layers go through the build service so new text
is warmed first (ADR 0015). A text field with the focus keeps its own shortcuts: Qt
gives them to the field before the window's actions.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from pydantic import ValidationError
from PySide6.QtCore import QMimeData, QObject, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QMenu

from ..core import adapter, clipboard, edits
from ..core.clipboard import ClipboardData, ClipboardError, Pasted
from ..core.schema import Project
from ..logging_config import get_logger
from .build_service import BuildService
from .selection import Selection
from .timeline.model import obstacles, place_new_clip

log = get_logger(__name__)


class ClipboardActions(QObject):
    message = Signal(str)  # what happened or why not, for the status bar

    def __init__(
        self,
        builds: BuildService,
        selection: Selection,
        playhead: Callable[[], float],
        has_project: Callable[[], bool],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.builds, self.document, self.selection = builds, builds.document, selection
        self.playhead, self.has_project = playhead, has_project
        self.actions: dict[str, QAction] = {}
        for name, text, keys, slot in (
            ("cut", "Cu&t", QKeySequence.StandardKey.Cut, self.cut),
            ("copy", "&Copy", QKeySequence.StandardKey.Copy, self.copy),
            ("paste", "&Paste", QKeySequence.StandardKey.Paste, self.paste),
            ("duplicate", "&Duplicate", QKeySequence("Ctrl+D"), self.duplicate),
        ):
            action = QAction(text, self)
            action.setShortcut(keys)
            action.triggered.connect(slot)
            self.actions[name] = action
        self.actions["duplicate"].setToolTip("A copy of the selection next to it (the clipboard is kept)")
        self.actions["cut"].setToolTip("Copy the selection and delete it")
        self.actions["copy"].setToolTip("Copy the selected layers, clip, sound or subtitle")
        self.actions["paste"].setToolTip("Paste layers above the selection, a clip at the playhead")

    def add_to(self, menu: QMenu) -> None:
        menu.addActions(list(self.actions.values()))
        menu.addSeparator()

    @property
    def project(self) -> Project:
        return self.document.project

    # -- the system clipboard -------------------------------------------------------

    def put(self, data: ClipboardData) -> None:
        text = clipboard.to_json(data)
        mime = QMimeData()
        mime.setData(clipboard.MIME_TYPE, text.encode("utf-8"))
        mime.setText(text)
        QGuiApplication.clipboard().setMimeData(mime)

    def take(self) -> ClipboardData:
        """What the system clipboard holds (``ClipboardError`` if nothing we can paste)."""
        mime = QGuiApplication.clipboard().mimeData()
        if mime is not None and mime.hasFormat(clipboard.MIME_TYPE):
            text = bytes(mime.data(clipboard.MIME_TYPE).data()).decode("utf-8", errors="replace")
        elif mime is not None and mime.hasText():
            text = mime.text()  # copied by another instance, through a plain-text hop
        else:
            raise ClipboardError(clipboard.NOTHING)
        return clipboard.from_json(text)

    # -- actions ------------------------------------------------------------------

    def copy(self) -> bool:
        """Put the selection on the clipboard; True if something was copied."""
        if not self._ready():
            return False
        try:
            data, what = self._selected_data()
        except ClipboardError as error:
            self.message.emit(str(error))
            return False
        self.put(data)
        self.message.emit(f"Copied {what}")
        return True

    def cut(self) -> None:
        """Copy, then delete the selection (one undo step)."""
        if not self._ready():
            return
        sel = self.selection
        try:
            data, what = self._selected_data()
        except ClipboardError as error:
            self.message.emit(str(error))
            return
        if sel.audio_id is not None:
            edit = edits.remove_audio(self.project, sel.audio_id)
        elif sel.subtitle_id is not None:
            edit = edits.remove_cue(self.project, sel.subtitle_id)
        elif sel.clip_id is not None:
            edit = edits.remove_clip(self.project, sel.layer_id, sel.clip_id)
        elif sel.many:
            edit = edits.remove_layers(self.project, self._chosen())
        else:
            edit = edits.remove_layer(self.project, sel.layer_id)
        self.put(data)
        self.document.apply(edit, f"Cut {what}")
        self.message.emit(f"Cut {what}")

    def paste(self) -> None:
        if not self._ready():
            return
        try:
            data = self.take()
            if data.kind == "layers":
                self._paste_layers(data)
                return
            pasted = self._paste_item(data)
        except ClipboardError as error:
            self.message.emit(str(error))
            return
        self._commit(pasted, "Paste", data.kind)

    def duplicate(self) -> None:
        if not self._ready():
            return
        sel, project = self.selection, self.project
        try:
            if sel.audio_id is not None:
                pasted, kind = clipboard.duplicate_audio(project, sel.audio_id), "audio"
            elif sel.subtitle_id is not None:
                pasted, kind = clipboard.duplicate_cue(project, sel.subtitle_id), "cue"
            elif sel.clip_id is not None:
                allowed = self._allowed(sel.layer_id)
                pasted = clipboard.duplicate_clip(project, sel.layer_id, sel.clip_id, allowed)
                kind = "clip"
            elif sel.layer_id is not None:
                chosen = self._chosen()
                self._submit_layers(lambda p: clipboard.duplicate_layers(p, chosen), "Duplicate")
                return
            else:
                raise ClipboardError("Select a layer, clip, sound or subtitle to duplicate")
        except ClipboardError as error:
            self.message.emit(str(error))
            return
        self._commit(pasted, "Duplicate", kind)

    # -- internals ----------------------------------------------------------------

    def _ready(self) -> bool:
        if not self.has_project():
            self.message.emit("Create or open a project first.")
            return False
        return not self.document.dragging

    def _selected_data(self) -> tuple[ClipboardData, str]:
        """The clipboard document for the selection, and words for it."""
        sel, project = self.selection, self.project
        if sel.audio_id is not None:
            data = clipboard.copy_audio(project, sel.audio_id)
            return data, f"sound {data.payload.sound.name or data.payload.sound.id}"
        if sel.subtitle_id is not None:
            return clipboard.copy_cue(project, sel.subtitle_id), "subtitle"
        if sel.clip_id is not None:
            data = clipboard.copy_clip(project, sel.layer_id, sel.clip_id)
            return data, f"{data.payload.clip.kind} clip"
        if sel.many:
            chosen = self._chosen()
            return clipboard.copy_layers(project, chosen), f"{len(chosen)} layers"
        if sel.layer_id is not None:
            layer = project.layer(sel.layer_id)
            return clipboard.copy_layers(project, [sel.layer_id]), layer.label
        raise ClipboardError("Select a layer, clip, sound or subtitle first")

    def _chosen(self) -> list[str]:
        """The selected layers in the project's order (several, ADR 0043)."""
        chosen = set(self.selection.layer_ids)
        return [layer.id for layer in self.project.layers if layer.id in chosen]

    def _allowed(self, layer_id: str) -> list[str]:
        layer = self.project.layer(layer_id)
        return adapter.allowed_clip_kinds((layer.spec or self.project.root_of(layer_id).spec).type)

    def _paste_item(self, data: ClipboardData) -> Pasted:
        """A clip on the selected layer, a sound or a subtitle at the playhead."""
        project, t = self.project, self.playhead()
        if data.kind == "audio":
            return clipboard.paste_audio(project, data.payload, t)
        if data.kind == "cue":
            return clipboard.paste_cue(project, data.payload, t)
        layer_id = self.selection.layer_id
        if layer_id is None:
            raise ClipboardError("Select the layer to paste the clip on")
        clip = data.payload.clip
        layer = project.layer(layer_id)
        placement = place_new_clip(
            layer,
            t,
            duration=project.canvas.duration,
            fps=project.canvas.fps,
            length=clip.duration,
            obstacles=obstacles(project, layer_id),
        )
        if placement is None or placement[1] < clip.duration - 1e-9:
            raise ClipboardError(f"No room for the {clip.kind} clip ({clip.duration:g} s) at the playhead")
        return clipboard.paste_clip(project, data.payload, layer_id, placement[0], self._allowed(layer_id))

    def _paste_layers(self, data: ClipboardData) -> None:
        above = self.selection.layer_id
        self._submit_layers(partial(clipboard.paste_layers, payload=data.payload, above=above), "Paste")

    def _submit_layers(self, paste: Callable[[Project], Pasted], verb: str) -> None:
        """Layers go through the build service: a pasted equation may need its text warmed."""
        before = {layer.id for layer in self.project.layers}
        pasted = paste(self.project)  # raises ClipboardError before anything changes
        try:
            self.builds.submit(lambda p: paste(p).edit, f"{verb} layer")
        except (edits.EditError, ValidationError, ClipboardError) as error:  # pragma: no cover - re-run
            self.message.emit(f"{verb}: {error}")
            return
        present = {layer.id for layer in self.project.layers}
        new_roots = [x.id for x in self.project.roots() if x.id not in before]
        if len(new_roots) > 1:  # several pasted objects stay selected together (ADR 0043)
            self.selection.set_layers(new_roots, pasted.selected if pasted.selected in new_roots else None)
        elif pasted.selected in present:
            self.selection.set(pasted.selected)
        layer = next((x for x in pasted.edit.project.layers if x.id == pasted.selected), None)
        self._report(verb, layer.label if layer is not None else "layers", pasted.notes)

    def _commit(self, pasted: Pasted, verb: str, kind: str) -> None:
        names = {"clip": "clip", "audio": "sound", "cue": "subtitle"}
        self.document.apply(pasted.edit, f"{verb} {names[kind]}")
        if kind == "audio":
            self.selection.set_audio(pasted.selected)
        elif kind == "cue":
            self.selection.set_subtitle(pasted.selected)
        else:
            self.selection.set(self.selection.layer_id, pasted.selected)
        self._report(verb, names[kind], pasted.notes)

    def _report(self, verb: str, what: str, notes: tuple[str, ...]) -> None:
        past = {"Paste": "Pasted", "Duplicate": "Duplicated"}[verb]
        text = f"{past} {what}"
        if notes:
            text += " - " + "; ".join(notes)
            log.info("%s: %s", text, notes)
        self.message.emit(text)
