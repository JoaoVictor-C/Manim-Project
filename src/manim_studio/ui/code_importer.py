"""Bringing code into the project (P12): files, pasted text, downloaded presets and drags.

The window shows ``ImportCodeDialog`` for what is about to be added; this carries out the answer:
layers (Python objects and code layers, one undo step per choice) and library presets. Dragging a
preset or a code layer onto the timeline or the canvas skips the window and adds it where it was
dropped. Nothing here runs the code: it stays untrusted unless the user allows it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ..core import code_export, code_files, code_import
from ..core.code_export import ExportEntry, ExportOptions
from ..core.code_import import ImportChoice, ImportItem
from . import online_presets_dialog
from .conflict_dialog import ConflictAsker
from .export_code_dialog import ExportCodeDialog
from .import_code_dialog import ImportCodeDialog
from .online_presets_dialog import OnlinePresetsDialog

if TYPE_CHECKING:
    from .main_window import MainWindow


class CodeImporter:
    def __init__(self, window: MainWindow) -> None:
        self.window = window
        # Hook for tests and other front-ends: the choices for these items, or None when cancelled.
        self.ask: Callable[..., list[ImportChoice] | None] = self._dialog
        # Hook for the export window: (entries, checked keys, folder, options) -> (chosen, folder,
        # options) or None when cancelled.
        self.ask_export: Callable[..., tuple[list[ExportEntry], str, ExportOptions] | None] = (
            self._export_dialog
        )
        # Hook for the online window: the downloaded items, or None when cancelled.
        self.ask_online: Callable[[], list[ImportItem] | None] = self._online_dialog
        # Hook for the question about a file that exists: a ConflictAsker (called with the file name).
        self.conflicts: Callable[[str | Path], Callable[[str], str | None]] = self._asker

    # -- asking -----------------------------------------------------------------------------

    def _dialog(
        self,
        items: list[ImportItem],
        at: float | None,
        position: tuple[float, float] | None,
        prefer_preset: bool = False,
    ) -> list[ImportChoice] | None:
        window = self.window
        dialog = ImportCodeDialog(
            items,
            playhead=window.t,
            at=at,
            position=position,
            has_project=window.project is not None,
            prefer_preset=prefer_preset,
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
        self,
        items: list[ImportItem],
        at: float | None = None,
        position: tuple[float, float] | None = None,
        *,
        prefer_preset: bool = False,
    ) -> str:
        choices = self.ask(items, at, position, prefer_preset=prefer_preset)
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

    # -- exporting --------------------------------------------------------------------------

    def entries(self) -> list[ExportEntry]:
        """Everything that can be exported: the project's code layers and Python objects, then the
        presets (with unapplied edits of the layer being edited left out - the page asks for them)."""
        window = self.window
        out = []
        project = window.project
        if project is not None:
            for layer in project.layers:
                if layer.spec is not None and layer.spec.type in ("Code", "Python"):
                    kind = "object" if layer.spec.type == "Python" else "scene"
                    out.append(
                        ExportEntry(layer.id, layer.label, kind, str(layer.spec.params.get("code", "")))
                    )
        for preset in window.code_presets.presets():
            out.append(
                ExportEntry(preset.id, preset.name, preset.kind, preset.code, "preset", preset.description)
            )
        return out

    def _asker(self, folder: str | Path) -> Callable[[str], str | None]:
        return ConflictAsker(self.window, folder)

    def _export_dialog(
        self, entries: list[ExportEntry], checked: set[str] | None, folder: str, options: ExportOptions
    ) -> tuple[list[ExportEntry], str, ExportOptions] | None:
        dialog = ExportCodeDialog(
            entries, checked=checked, folder=folder, options=options, parent=self.window
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return None
        return dialog.chosen(), dialog.folder(), dialog.options()

    def export_code(self, entries: list[ExportEntry] | None = None, checked: set[str] | None = None) -> str:
        """Ask what to export and where, then write it; a file that is already there is asked about
        (replace, skip or keep both). Returns the status line."""
        window = self.window
        prefs = window.prefs
        entries = self.entries() if entries is None else entries
        if not entries:
            return self._say("There is no code to export")
        folder = str(prefs.option("code_export_folder", str(window.default_folder())))
        saved = ExportOptions(
            "\r\n" if prefs.option("code_export_crlf", False) else "\n",
            prefs.option("code_export_header", False),
            prefs.option("code_export_manifest", False),
        )
        answer = self.ask_export(entries, checked, folder, saved)
        if answer is None:
            return ""
        chosen, folder, options = answer
        if not chosen:
            return ""
        prefs.set_option("code_export_folder", folder)
        prefs.set_option("code_export_crlf", options.newline == "\r\n")
        prefs.set_option("code_export_header", options.header)
        prefs.set_option("code_export_manifest", options.manifest)
        decide = self.conflicts(folder)
        result = code_files.export_files(code_export.prepare(chosen, options), folder, decide)
        extra = None
        if options.manifest and not result.cancelled:
            index = code_export.manifest(chosen, Path(folder).name)
            extra = code_files.export_files(
                [(code_export.MANIFEST_NAME, index)], folder, decide, extension=".json"
            )
        return self._say(self._summary(result, extra, folder))

    @staticmethod
    def _summary(result: code_files.ExportResult, index: code_files.ExportResult | None, folder: str) -> str:
        saved = result.saved
        details = []
        if result.replaced:
            details.append(f"{len(result.replaced)} replaced")
        if result.copied:
            details.append(f"{len(result.copied)} kept as copies")
        if result.skipped:
            details.append(f"{len(result.skipped)} skipped")
        if result.failed:
            first = result.failed[0]
            details.append(f"{len(result.failed)} failed ({first[0]}: {first[1]})")
        if index is not None and index.saved:
            details.append("index.json written")
        text = f"Exported {saved} file{'s' if saved != 1 else ''} to {folder}"
        if result.cancelled:
            text = f"Export cancelled after {saved} file{'s' if saved != 1 else ''} to {folder}"
        return text + (f" ({', '.join(details)})" if details else "")

    # -- folders and the internet -------------------------------------------------------------

    def import_folder(self, folder: str | Path) -> str:
        """Every ``.py`` file in a folder, offered in the import window as presets to keep."""
        try:
            paths = sorted(
                (p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() == ".py"),
                key=lambda p: p.name.casefold(),
            )
        except OSError as error:
            return self._say(f"Could not read that folder: {error.strerror or error}")
        if not paths:
            return self._say("No .py files found in that folder")
        items, problems = self.read_paths(paths)
        if not items:
            return self._say("; ".join(problems[:2]))
        message = self.import_items(items, prefer_preset=True)
        return message

    def _online_dialog(self) -> list[ImportItem] | None:
        sources = online_presets_dialog.load_sources(
            str(self.window.prefs.option(online_presets_dialog.SOURCES_OPTION, "[]"))
        )
        dialog = OnlinePresetsDialog(sources, self.window)
        accepted = dialog.exec() == dialog.DialogCode.Accepted
        self.window.prefs.set_option(online_presets_dialog.SOURCES_OPTION, json.dumps(dialog.sources))
        return dialog.items() if accepted else None

    def get_online(self) -> str:
        """Presets from a link: the online window, then the import window for what was downloaded."""
        items = self.ask_online()
        if not items:
            return ""
        return self.import_items(items, prefer_preset=True)
