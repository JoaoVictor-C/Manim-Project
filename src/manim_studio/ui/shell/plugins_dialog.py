"""Help > Plugins... (P4b.2, ADR 0032, 0078): which plugins loaded, what they add and declare, which wait for
approval and which did not load.

Plugins load when the editor starts; installing or changing one needs a restart. A plugin with a manifest
loads only after its permissions are approved here (ADR 0078); approving stores the approval and the
plugin loads at the next start. Permissions are a plugin's own declaration, shown so the user can decide,
not a sandbox: the dialog says so.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import plugin_manifest, plugins
from ...core.engine import adapter
from ...plugin_manifest import Manifest
from ..style import icons, theme
from ..style.card import Chip
from ..style.dialog_chrome import DialogFrame

NOT_A_SANDBOX = (
    "Plugins are Python code that runs inside Manim Studio with all of your user account's rights. "
    "Permissions are what a plugin says it does, so you can decide whether to allow it; "
    "they are not enforced. Only allow plugins you trust."
)
NO_MANIFEST = "no manifest: unknown permissions"


def _about(manifest: Manifest) -> str:
    return f"{manifest.name} {manifest.version}" + (f" by {manifest.author}" if manifest.author else "")


def _permissions(permissions: tuple[str, ...]) -> str:
    return ", ".join(permissions) or "none"


def report() -> str:
    """The dialog's text: plugins with their types and manifests, those waiting for approval, then those
    skipped with why."""
    lines = []
    for plugin, types in sorted(plugins.loaded.items()):
        voices = [t.removeprefix("voice:") for t in types if t.startswith("voice:")]
        objects = [t for t in types if not t.startswith("voice:")]
        added = ", ".join(f"{adapter.LIBRARY_LABELS.get(t, t)} ({plugins.TYPES[t].section})" for t in objects)
        if voices:
            added = ", ".join(filter(None, [added, "voices: " + ", ".join(voices)]))
        entry = f"{plugin}\n    adds: {added or 'no object types'}"
        manifest = plugins.manifests.get(plugin)
        if manifest is None:
            entry += f"\n    {NO_MANIFEST}"
        else:
            entry += f"\n    {_about(manifest)}\n    permissions: {_permissions(manifest.permissions)}"
        lines.append(entry)
    for plugin, manifest in sorted(plugins.pending.items()):
        new = plugin_manifest.new_permissions(plugins.approvals.get(plugin), manifest)
        asks = _permissions(manifest.permissions)
        if plugin in plugins.approvals and new:
            asks += f" (new: {', '.join(new)})"
        lines.append(f"{plugin}\n    WAITS FOR APPROVAL: {_about(manifest)}\n    permissions: {asks}")
    for plugin, manifest in sorted(plugins.approved.items()):
        lines.append(f"{plugin}\n    APPROVED: {_about(manifest)} loads at the next start")
    for plugin, problem in sorted(plugins.problems.items()):
        lines.append(f"{plugin}\n    NOT LOADED: {problem}")
    if not lines:
        lines.append("No plugins are installed.")
    folders = "\n".join(f"    {folder}" for folder in plugins.folders())
    lines.append(f"Plugin folders (restart the editor after a change):\n{folders}")
    return "\n\n".join(lines)


def startup_message() -> str | None:
    """A status-bar line when a plugin failed to load or waits for approval, else None."""
    parts = []
    if plugins.problems:
        count = len(plugins.problems)
        parts.append(f"{count} plugin{'s' if count > 1 else ''} could not load")
    if plugins.pending:
        count = len(plugins.pending)
        parts.append(f"{count} plugin{'s wait' if count > 1 else ' waits'} for your approval")
    return f"{', '.join(parts)}: see Help > Plugins" if parts else None


def summary() -> str:
    """The dialog's one-line description: how many loaded, wait and did not load."""
    loaded, problems, waiting = len(plugins.loaded), len(plugins.problems), len(plugins.pending)
    if not loaded and not problems and not waiting:
        return "No plugins are installed. They load when the editor starts."
    parts = [f"{loaded} loaded"]
    if waiting:
        parts.append(f"{waiting} wait{'s' if waiting == 1 else ''} for approval")
    if problems:
        parts.append(f"{problems} could not load")
    return ", ".join(parts).capitalize() + ". Changes need a restart."


class PendingPlugin(QFrame):
    """One plugin waiting for approval: who made it, what it says it does, its permissions as chips (the
    ones not approved before marked new) and an Allow button."""

    def __init__(self, plugin: str, manifest: Manifest, dialog: PluginsDialog) -> None:
        super().__init__()
        self.plugin = plugin
        self.setProperty("option", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel(_about(manifest))
        title.setProperty("role", "dialogTitle")
        head.addWidget(title, 1)
        self.allow = QPushButton("Allow")
        self.allow.setIcon(icons.icon("check"))
        self.allow.setToolTip("Allow these permissions; the plugin loads the next time the editor starts")
        self.allow.clicked.connect(lambda: dialog.approve(plugin))
        head.addWidget(self.allow)
        layout.addLayout(head)
        where = QLabel(plugin + (f"\n{manifest.description}" if manifest.description else ""))
        where.setProperty("role", "muted")
        where.setWordWrap(True)
        layout.addWidget(where)
        known = plugin in plugins.approvals
        new = set(plugin_manifest.new_permissions(plugins.approvals.get(plugin), manifest))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chips: list[Chip] = []
        for permission in manifest.permissions:
            text = permission + (" (new)" if known and permission in new else "")
            chip = Chip(text, "warn" if permission in plugin_manifest.SENSITIVE else "neutral")
            chip.setToolTip(plugin_manifest.PERMISSIONS[permission])
            chips.addWidget(chip)
            self.chips.append(chip)
        if not manifest.permissions:
            chips.addWidget(Chip("no permissions", "ok"))
        chips.addStretch(1)
        layout.addLayout(chips)
        if known and new:
            more = QLabel("It now asks for more than you allowed before.")
            more.setProperty("role", "muted")
            layout.addWidget(more)


class PluginsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plugins")
        self.resize(680, 480)
        tone = "warn" if plugins.problems or plugins.pending else "accent"
        self.frame = DialogFrame(self, "plugin", "Plugins", summary(), tone=tone)
        self.warning = QLabel(NOT_A_SANDBOX)
        self.warning.setWordWrap(True)
        self.warning.setProperty("role", "muted")
        self.frame.body.addWidget(self.warning)
        self.pending_box = QVBoxLayout()
        self.pending_box.setSpacing(8)
        self.frame.body.addLayout(self.pending_box)
        self.rows: dict[str, PendingPlugin] = {}
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(theme.mono_font())
        self.frame.body.addWidget(self.text, 1)
        self.open_folder = self.frame.add_left(QPushButton("Open Plugin Folder"))
        self.open_folder.setIcon(icons.icon("folder"))
        self.open_folder.clicked.connect(self._open_folder)
        close = self.frame.add_button("Close", "primary")
        close.clicked.connect(self.accept)
        self.refresh()

    def refresh(self) -> None:
        """Show the plugins as they are now (after an approval)."""
        for row in self.rows.values():
            self.pending_box.removeWidget(row)
            row.deleteLater()
        self.rows = {}
        for plugin, manifest in sorted(plugins.pending.items()):
            self.rows[plugin] = PendingPlugin(plugin, manifest, self)
            self.pending_box.addWidget(self.rows[plugin])
        self.text.setPlainText(report())
        self.frame.set_description(summary())

    def approve(self, plugin: str) -> None:
        """The user allowed ``plugin``'s permissions: store the approval (it loads at the next start)."""
        plugins.approve(plugin)
        self.refresh()

    def _open_folder(self) -> None:
        folder = plugins.folders()[0] if plugins.folders() else plugins.DEFAULT_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
