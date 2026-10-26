"""Help > Plugins... (P4b.2, ADR 0032): which plugins loaded, which types they add, which failed.

Plugins load when the editor starts; installing or changing one needs a
restart, so the dialog only reports and opens the plugin folder.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ... import plugins
from ...core.engine import adapter


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


class PluginsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plugins")
        self.resize(640, 360)
        self.text = QPlainTextEdit(report())
        self.text.setReadOnly(True)
        self.open_folder = QPushButton("Open Plugin Folder")
        self.open_folder.clicked.connect(self._open_folder)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_folder)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addLayout(buttons)

    def _open_folder(self) -> None:
        folder = plugins.folders()[0] if plugins.folders() else plugins.DEFAULT_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
