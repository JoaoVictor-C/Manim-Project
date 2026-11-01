"""Help > Plugins... (P4b.2, ADR 0032, 0078): which plugins loaded, what they add and declare, which wait for
approval and which did not load.

Plugins load when the editor starts; installing or changing one needs a restart. A plugin with a manifest
loads only after its permissions are approved here (ADR 0078); approving stores the approval and the
plugin loads at the next start. Permissions are a plugin's own declaration, shown so the user can decide,
not a sandbox: the dialog says so.

Each plugin is a row of the shared list (ADR 0084): name and version, a compatibility chip (*compatible* or
*needs newer app*), the permissions it asks for as chips (the riskier ones warn, those asked for since the
last approval say *new*), what it adds, and its state - an unapproved plugin says it is waiting for approval
and has an *Approve* button on its row. The text report stays under *Details*.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QWidget

from ... import plugin_manifest, plugins
from ...core.engine import adapter
from ...plugin_manifest import Manifest
from ..style import icons, theme
from ..style.card import Chip
from ..style.dialog_chrome import DialogFrame
from ..style.list_row import ListRow, RowList

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


COMPATIBLE, NEEDS_NEWER, NOT_COMPATIBLE = "compatible", "needs newer app", "not compatible"
WAITING = "waiting for approval"


def compatibility(manifest: Manifest | None) -> tuple[str, str]:
    """The compatibility chip's text and tone for a plugin: *compatible* (ok), *needs newer app* or *not
    compatible* (bad) when its ``requires`` range excludes this app, *no manifest* (warn) when it has none."""
    if manifest is None:
        return "no manifest", "warn"
    if plugin_manifest.incompatibility(manifest, plugins.app_version()) is None:
        return COMPATIBLE, "ok"
    for part in manifest.requires.split(","):
        part = part.strip()
        if part and not plugin_manifest.satisfies(plugins.app_version(), part):
            return (NEEDS_NEWER if part.startswith((">", "~=", "==")) else NOT_COMPATIBLE), "bad"
    return NOT_COMPATIBLE, "bad"


def _adds(types: list[str]) -> str:
    voices = [t.removeprefix("voice:") for t in types if t.startswith("voice:")]
    objects = [t for t in types if not t.startswith("voice:")]
    added = ", ".join(f"{adapter.LIBRARY_LABELS.get(t, t)} ({plugins.TYPES[t].section})" for t in objects)
    if voices:
        added = ", ".join(filter(None, [added, "voices: " + ", ".join(voices)]))
    return added or "no object types"


def _tone(permission: str) -> str:
    return "warn" if permission in plugin_manifest.SENSITIVE else "neutral"


class PluginRow(ListRow):
    """One plugin. ``state`` is ``loaded``, ``waiting``, ``approved`` (loads at next start) or ``problem``;
    a waiting plugin has the *Approve* button (``allow``)."""

    def __init__(self, plugin: str, state: str, dialog: PluginsDialog) -> None:
        manifest = {"waiting": plugins.pending, "approved": plugins.approved}.get(
            state, plugins.manifests
        ).get(plugin)
        super().__init__(_about(manifest) if manifest else Path(plugin).stem or plugin)
        self.plugin, self.state = plugin, state
        self.permission_chips: list[Chip] = []
        self.allow: QPushButton | None = None
        text, tone = compatibility(manifest)
        problem = plugins.problems.get(plugin, "")
        self.compat = self.add_head_chip(text, tone, problem if state == "problem" else "")
        if manifest is not None and manifest.description:
            self.add_line(manifest.description)
        self.add_line(plugin).setToolTip(plugin)
        known = plugin in plugins.approvals
        new: set[str] = set()
        if manifest is None:
            self.permission_chips = self.add_chips([("unknown permissions", "warn")], [NO_MANIFEST])
        else:
            new = set(plugin_manifest.new_permissions(plugins.approvals.get(plugin), manifest))
            chips = [
                (p + (" (new)" if state == "waiting" and known and p in new else ""), _tone(p))
                for p in manifest.permissions
            ] or [("no permissions", "ok")]
            tips = [plugin_manifest.PERMISSIONS.get(p, "") for p in manifest.permissions]
            self.permission_chips = self.add_chips(chips, tips)
        if state == "loaded":
            self.add_line("Adds: " + _adds(plugins.loaded.get(plugin, [])), "success")
        elif state == "waiting":
            self.add_line("Waiting for approval: it stays off until you approve it.", "warning")
            if known and new:
                self.add_line("It now asks for more than you approved before.")
            self.allow = QPushButton("Approve")
            self.allow.setProperty("role", "primary")
            self.allow.setIcon(icons.icon("check"))
            self.allow.setToolTip(
                "Approve these permissions; the plugin loads the next time the editor starts"
            )
            self.allow.clicked.connect(lambda: dialog.approve(plugin))
            self.add_action(self.allow)
        elif state == "approved":
            self.add_line("Approved: it loads at the next start.", "accent")
        else:
            self.add_line("Not loaded: " + problem, "danger")


class PluginsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plugins")
        self.resize(560, 520)
        tone = "warn" if plugins.problems or plugins.pending else "accent"
        self.frame = DialogFrame(self, "plugin", "Plugins", summary(), tone=tone)
        self.warning = QLabel(NOT_A_SANDBOX)
        self.warning.setWordWrap(True)
        self.warning.setProperty("role", "muted")
        self.frame.body.addWidget(self.warning)
        self.list = RowList()
        self.frame.body.addWidget(self.list, 1)
        self.rows: dict[str, PluginRow] = {}
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(theme.mono_font())
        self.text.setMaximumHeight(160)
        self.text.hide()
        self.frame.body.addWidget(self.text)
        self.open_folder = self.frame.add_left(QPushButton("Open Plugin Folder"))
        self.open_folder.setIcon(icons.icon("folder"))
        self.open_folder.clicked.connect(self._open_folder)
        self.details_button = self.frame.add_left(QPushButton("Details"))
        self.details_button.setCheckable(True)
        self.details_button.setToolTip("The plain-text report of every plugin and the folders they load from")
        self.details_button.toggled.connect(self.text.setVisible)
        close = self.frame.add_button("Close")
        close.clicked.connect(self.accept)
        self.refresh()

    def refresh(self) -> None:
        """Show the plugins as they are now (after an approval): those waiting first, then those loaded,
        approved this session and not loaded."""
        self.list.clear()
        self.rows = {}
        order = (
            [(p, "waiting") for p in sorted(plugins.pending)]
            + [(p, "loaded") for p in sorted(plugins.loaded)]
            + [(p, "approved") for p in sorted(plugins.approved)]
            + [(p, "problem") for p in sorted(plugins.problems)]
        )
        for plugin, state in order:
            row = PluginRow(plugin, state, self)
            self.rows[plugin] = row
            self.list.add_row(row, f"{plugin} - {state}")
        if not order:
            self.list.add_note("No plugins are installed. Put one in the plugin folder and restart.")
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
