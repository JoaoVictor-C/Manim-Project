"""Help > Plugins... (P4b.2, ADR 0032): which plugins loaded, which types they add, which failed.

Plugins load when the editor starts; installing or changing one needs a
restart, so the dialog only reports and opens the plugin folder.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QPushButton, QWidget

from ... import plugins
from ...core.engine import adapter
from ..style import icons, theme
from ..style.dialog_chrome import DialogFrame


def report() -> str:
    """The dialog's text: plugins with their types, then those skipped with why."""
    lines = []
    for plugin, types in sorted(plugins.loaded.items()):
        voices = [t.removeprefix("voice:") for t in types if t.startswith("voice:")]
        objects = [t for t in types if not t.startswith("voice:")]
        added = ", ".join(f"{adapter.LIBRARY_LABELS.get(t, t)} ({plugins.TYPES[t].section})" for t in objects)
        if voices:
            added = ", ".join(filter(None, [added, "voices: " + ", ".join(voices)]))
        lines.append(f"{plugin}\n    adds: {added or 'no object types'}")
    for plugin, problem in sorted(plugins.problems.items()):
        lines.append(f"{plugin}\n    NOT LOADED: {problem}")
    if not lines:
        lines.append("No plugins are installed.")
    folders = "\n".join(f"    {folder}" for folder in plugins.folders())
    lines.append(f"Plugin folders (restart the editor after a change):\n{folders}")
    return "\n\n".join(lines)


def startup_message() -> str | None:
    """A status-bar line when a plugin failed to load, else None."""
    if not plugins.problems:
        return None
    count = len(plugins.problems)
    return f"{count} plugin{'s' if count > 1 else ''} could not load: see Help > Plugins"


def summary() -> str:
    """The dialog's one-line description: how many loaded and how many did not."""
    loaded, problems = len(plugins.loaded), len(plugins.problems)
    if not loaded and not problems:
        return "No plugins are installed. They load when the editor starts."
    parts = [f"{loaded} loaded"]
    if problems:
        parts.append(f"{problems} could not load")
    return ", ".join(parts).capitalize() + ". Changes need a restart."


class PluginsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plugins")
        self.resize(640, 400)
        self.frame = DialogFrame(
            self, "plugin", "Plugins", summary(), tone="warn" if plugins.problems else "accent"
        )
        self.text = QPlainTextEdit(report())
        self.text.setReadOnly(True)
        self.text.setFont(theme.mono_font())
        self.frame.body.addWidget(self.text, 1)
        self.open_folder = self.frame.add_left(QPushButton("Open Plugin Folder"))
        self.open_folder.setIcon(icons.icon("folder"))
        self.open_folder.clicked.connect(self._open_folder)
        close = self.frame.add_button("Close", "primary")
        close.clicked.connect(self.accept)

    def _open_folder(self) -> None:
        folder = plugins.folders()[0] if plugins.folders() else plugins.DEFAULT_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
