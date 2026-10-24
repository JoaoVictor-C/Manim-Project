"""Bringing code into the project (P12): files, pasted text, downloaded presets and drags.

The window shows ``ImportCodeDialog`` for what is about to be added; this carries out the answer:
layers (Python objects and code layers, one undo step per choice) and library presets. Dragging a
preset or a code layer onto the timeline or the canvas skips the window and adds it where it was
dropped. Nothing here runs the code: it stays untrusted unless the user allows it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ..core import code_files, code_import
from ..core.code_import import ImportChoice, ImportItem
from .import_code_dialog import ImportCodeDialog

if TYPE_CHECKING:
    from .main_window import MainWindow


class CodeImporter:
    def __init__(self, window: MainWindow) -> None:
        self.window = window
        # Hook for tests and other front-ends: the choices for these items, or None when cancelled.
        self.ask: Callable[..., list[ImportChoice] | None] = self._dialog

    # -- asking -----------------------------------------------------------------------------

    def _dialog(
        self, items: list[ImportItem], at: float | None, position: tuple[float, float] | None
    ) -> list[ImportChoice] | None:
        window = self.window
        dialog = ImportCodeDialog(
            items,
            playhead=window.t,
            at=at,
            position=position,
            has_project=window.project is not None,
            parent=window,
        )
        return dialog.choices() if dialog.exec() == dialog.DialogCode.Accepted else None

    def read_paths(self, paths: list) -> tuple[list[ImportItem], list[str]]:
        """The readable files as items, and a line for each one that could not be read."""
        items, problems = [], []
        for raw in paths:
            path = Path(raw)
            try:
                items.append(ImportItem(code_files.read_source(path), path.name, path.name))
            except code_files.SourceError as error:
                problems.append(f"{path.name}: {error.reason}")
        return items, problems

    # -- importing --------------------------------------------------------------------------

    def import_paths(
        self, paths: list, at: float | None = None, position: tuple[float, float] | None = None
    ) -> str:
        """Read ``paths`` and open the import window for them. Returns what happened (also shown in
        the status bar)."""
        items, problems = self.read_paths(paths)
        if not items:
            return self._say("; ".join(problems) or "Nothing to import")
        message = self.import_items(items, at, position)
        if problems:
            message = f"{message} ({len(problems)} file(s) could not be read: {'; '.join(problems[:2])})"
            self.window.statusBar().showMessage(message, 12000)
        return message

    def import_items(
        self, items: list[ImportItem], at: float | None = None, position: tuple[float, float] | None = None
    ) -> str:
        choices = self.ask(items, at, position)
        if not choices:
            return ""
        return self.apply(choices)

    def apply(self, choices: list[ImportChoice]) -> str:
        """Add what was chosen; returns the status line."""
        window = self.window
        layers = presets = 0
        problems = []
        for choice in choices:
            why = code_import.validate(choice)
            if why is not None:
                problems.append(f"{choice.name}: {why}")
                continue
            for name, kind, code in code_import.presets_of(choice):
                window.code_presets.add(
                    name,
                    kind,
                    code,
                    origin="online" if choice.item.origin.startswith("http") else "user",
                    source_url=choice.item.origin if choice.item.origin.startswith("http") else "",
                )
                presets += 1
            if choice.as_ != code_import.PRESET:
                made = code_import.layers_of(choice)
                window.layers.add_code_layers(
                    made, appear=choice.appear, position=choice.position, trust=choice.trust
                )
                layers += len(made)
        parts = []
        if layers:
            parts.append(f"{layers} layer{'s' if layers != 1 else ''}")
        if presets:
            parts.append(f"{presets} preset{'s' if presets != 1 else ''}")
        message = ("Added " + " and ".join(parts)) if parts else "Nothing was added"
        if problems:
            message += f" ({'; '.join(problems[:2])})"
        return self._say(message)

    # -- dragging ---------------------------------------------------------------------------

    def place(
        self, payload: dict, t: float | None = None, position: tuple[float, float] | None = None
    ) -> str:
        """Something dragged from the Code workspace was dropped: add it as it is, at ``t`` seconds
        and ``position`` (None: the playhead / where it fits)."""
        window = self.window
        if window.project is None:
            return self._say("Create or open a project first")
        name = str(payload.get("name", "code"))
        if payload.get("from") == "layer":
            layer_id = str(payload.get("id"))
            if layer_id not in {layer.id for layer in window.project.layers}:
                return self._say(f"{name} is not in the project any more")
            window.layers.duplicate_code_layer(layer_id, appear=t, position=position)
            return self._say(f"Added another {name}")
        preset = window.code_presets.get(str(payload.get("id")))
        if preset is None:
            return self._say(f"The preset {name} is not in the library any more")
        type_name = "Python" if preset.kind == "object" else "Code"
        # The editor's own presets are trusted like its starter code; yours and downloaded ones are not.
        window.layers.add_code_layers(
            [(preset.name, type_name, preset.code)], appear=t, position=position, trust=preset.builtin
        )
        return self._say(f"Added {preset.name}")

    def _say(self, message: str) -> str:
        if message:
            self.window.statusBar().showMessage(message, 10000)
        return message
