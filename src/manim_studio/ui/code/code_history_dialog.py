"""History and revert on the Code page (P13.4): the versions of a layer's code, and going back to one.

The page owns one ``CodeHistory`` for the session (``page.history``); ``HistoryKeeper`` is the small
bit of glue that tells it what happened - a layer opened, a Run, a render or build that worked or
failed, another project - so the page itself only calls one method at each of those places.

Going back never applies anything: the chosen text is put in the editor as one step of the editor's
own undo, and Run is still the decision (as for Revert).

``CodeHistoryDialog`` lists the versions of the layer in the editor, newest first, with when, how
(Run, Live, opened), whether it worked, and how many lines differ from the editor; choosing one shows
the changes from it to the editor's text.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.code.code_history import CodeHistory, Version, diff_stats, unified_diff
from ...core.model.schema import PYTHON_TYPES
from ..style import theme

SOURCES = {"run": "Run", "live": "Live", "open": "Opened"}
NO_WORKING = "No earlier version of this code worked yet: run it first"
NO_LAYER = "Open a code layer, a Python object or a helper first"


def describe(version: Version, editor_text: str, now: float | None = None) -> str:
    """One line of the list: when, how, whether it worked, and the lines it differs from the editor by."""
    when = time.strftime("%H:%M:%S", time.localtime(version.time))
    if now is not None and time.localtime(now)[:3] != time.localtime(version.time)[:3]:
        when = time.strftime("%d %b %H:%M:%S", time.localtime(version.time))
    how = SOURCES.get(version.source, version.source)
    worked = {True: "worked", False: "failed", None: ""}[version.working]
    added, removed = diff_stats(version.text, editor_text)
    change = "same as the editor" if not (added or removed) else f"+{added} −{removed}"
    return "  ·  ".join(part for part in (when, how, worked, change) if part)


class HistoryKeeper:
    """Feeds ``page.history`` from the Code page's events; the page calls one method per event."""

    def __init__(self, page) -> None:
        self.page = page
        self._begun: set[str] = set()  # layers opened since they (re)appeared in the project
        self.dialog: CodeHistoryDialog | None = None

    @property
    def history(self) -> CodeHistory:
        return self.page.history

    # -- events ---------------------------------------------------------------------------------

    def opened(self, layer_id: str, code: str) -> None:
        """A layer is shown in the editor with its applied ``code``: the first time since it appeared,
        its chain begins (a reused id with unrelated text starts a new one)."""
        if layer_id not in self._begun:
            self._begun.add(layer_id)
            self.history.begin(layer_id, code)
        self.check(layer_id, code_status=True)

    def ran(self, layer_id: str, text: str, source: str = "run") -> None:
        """Run (or Live) applied ``text``: a new version. Whether it works is learned when the render
        settles, or now for a Python object that was already rebuilt (the apply may be synchronous)."""
        self.history.record(layer_id, text, source=source)
        self.check(layer_id)

    def status_changed(self, layer_id: str) -> None:
        """The renderer settled a code layer: ready marks its code as working, an error as failed."""
        if layer_id in self.history.layer_ids():
            self.check(layer_id, code_status=True)

    def project_changed(self) -> None:
        """The document changed: layers that left must begin again when they come back, and a Python
        object's build (computed from the document itself) says whether its code works."""
        present = {x.id: x for x in self.page._layers()}
        self._begun &= set(self.page._keys())  # layers and helpers (ADR 0058)
        for layer_id in self.history.layer_ids():
            layer = present.get(layer_id)
            if layer is not None and layer.spec.type in PYTHON_TYPES:
                self.check(layer_id)

    def project_reset(self) -> None:
        """Another project was opened: the chains of layers it does not have are dropped, and every
        layer begins again when it is opened (so a reused id with other text gets a new chain)."""
        self._begun.clear()
        self.history.drop_unused(set(self.page._keys()))

    def check(self, layer_id: str, *, code_status: bool = False) -> None:
        """Learn from the layer's status whether its applied code works. A code layer's render status
        is trusted only when asked (``code_status``): right after a change it may still be the old one."""
        page = self.page
        code = page._code_of(layer_id)
        if code is None or not self.history.contains(layer_id, code):
            return
        if not code_status and not page._is_python(layer_id):
            return
        status = page.status(layer_id)
        state = "" if status is None else status.state
        if state in ("ready", "built"):
            self.history.mark_working(layer_id, code)
        elif state == "error":
            versions = self.history.versions(layer_id)
            if versions and versions[0].text == code and versions[0].working is None:
                self.history.record(layer_id, code, False)  # the newest learns that it failed

    # -- actions --------------------------------------------------------------------------------

    def revert_to_working(self) -> bool:
        """Put the last version that worked (other than the editor's text) in the editor, as one
        editor-undo step; nothing is applied. Returns whether the text changed."""
        page = self.page
        layer_id = page.layer_id
        if layer_id is None or page.preset_id is not None:
            self._say(NO_LAYER)
            return False
        version = self.history.last_working(layer_id, before=page.editor.text())
        if version is None:
            self._say(NO_WORKING)
            return False
        self.put(version.text)
        when = time.strftime("%H:%M:%S", time.localtime(version.time))
        self._say(f"The version that worked at {when} is in the editor: Run applies it (Ctrl+Z undoes)")
        return True

    def put(self, text: str) -> None:
        """Replace the editor's text with ``text`` as one step of the editor's own undo."""
        editor = self.page.editor
        if editor.text() != text:
            editor.replace_text(text)

    def show_dialog(self) -> CodeHistoryDialog | None:
        """Open the History window for the layer in the editor (not modal, so it can be compared)."""
        page = self.page
        layer_id = page.layer_id
        if layer_id is None or page.preset_id is not None:
            self._say(NO_LAYER)
            return None
        if self.dialog is not None:
            self.dialog.close()
        self.dialog = CodeHistoryDialog(
            lambda: self.history.versions(layer_id),
            page.editor.text,
            self.put,
            title=page._label_of(layer_id),
            parent=page.widget,
        )
        page.editor.textChanged.connect(self.dialog.refresh_diff)
        self.dialog.finished.connect(lambda _code, d=self.dialog: self._closed(d))
        self.dialog.open()
        return self.dialog

    def _closed(self, dialog: CodeHistoryDialog) -> None:
        with contextlib.suppress(RuntimeError, TypeError):
            self.page.editor.textChanged.disconnect(dialog.refresh_diff)
        if self.dialog is dialog:
            self.dialog = None

    def _say(self, text: str) -> None:
        self.page.window.statusBar().showMessage(text, 8000)


class _DiffColours(QSyntaxHighlighter):
    """Added lines in the success colour, removed ones in the error colour, hunk headers muted."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)

    def highlightBlock(self, text: str) -> None:
        colours = theme.THEME
        if text.startswith(("+++", "---")):
            token = colours.muted
        elif text.startswith("+"):
            token = colours.success
        elif text.startswith("-"):
            token = colours.error_text
        elif text.startswith("@@"):
            token = colours.muted
        else:
            return
        fmt = QTextCharFormat()
        fmt.setForeground(theme.qcolor(token))
        self.setFormat(0, len(text), fmt)


class CodeHistoryDialog(QDialog):
    """The versions of one layer, newest first; choosing one shows what changed from it to the editor."""

    def __init__(
        self,
        versions: Callable[[], list[Version]],
        editor_text: Callable[[], str],
        put: Callable[[str], None],
        *,
        title: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._versions_of = versions
        self._editor_text = editor_text
        self._put = put
        self.versions: list[Version] = []
        self.setWindowTitle(f"History — {title}" if title else "History")
        self.setObjectName("codeHistory")
        self.resize(820, 520)

        intro = QLabel(
            "The versions of this code in this session, newest first. Choose one to see what changed "
            "from it to the text in the editor; Put in editor replaces the editor's text with it "
            "(Ctrl+Z in the editor undoes, and nothing is applied until you Run)."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "hint")
        self.list = QListWidget()
        self.list.setObjectName("codeHistoryList")
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemDoubleClicked.connect(lambda _item: self.put_in_editor())
        self.diff_label = QLabel("")
        self.diff_label.setProperty("role", "hint")
        self.diff = QPlainTextEdit()
        self.diff.setObjectName("codeHistoryDiff")
        self.diff.setReadOnly(True)
        self.diff.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.diff.setFont(theme.mono_font())
        self._colours = _DiffColours(self.diff.document())
        right = QWidget()
        right_column = QVBoxLayout(right)
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.addWidget(self.diff_label)
        right_column.addWidget(self.diff, 1)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.list)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 520])

        self.put_button = QPushButton("Put in editor")
        self.put_button.setToolTip("Replace the editor's text with this version (not applied until Run)")
        self.put_button.clicked.connect(self.put_in_editor)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.put_button)
        buttons.addWidget(self.close_button)

        column = QVBoxLayout(self)
        column.addWidget(intro)
        column.addWidget(split, 1)
        column.addLayout(buttons)
        self.refresh()

    # -- reading --------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Read the versions again and redo the list (keeping the chosen row)."""
        row = max(self.list.currentRow(), 0)
        self.versions = self._versions_of()
        editor = self._editor_text()
        now = time.time()
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for version in self.versions:
                item = QListWidgetItem(describe(version, editor, now))
                item.setToolTip("This version worked" if version.working else "")
                self.list.addItem(item)
        finally:
            self.list.blockSignals(False)
        if self.versions:
            self.list.setCurrentRow(min(row, len(self.versions) - 1))
        self._on_row(self.list.currentRow())

    def chosen(self) -> Version | None:
        row = self.list.currentRow()
        return self.versions[row] if 0 <= row < len(self.versions) else None

    def refresh_diff(self) -> None:
        """The editor's text changed: redo the +/- counts and the diff."""
        editor = self._editor_text()
        now = time.time()
        for row, version in enumerate(self.versions):
            item = self.list.item(row)
            if item is not None:
                item.setText(describe(version, editor, now))
        self._on_row(self.list.currentRow())

    def _on_row(self, _row: int) -> None:
        version = self.chosen()
        self.put_button.setEnabled(version is not None)
        if version is None:
            self.diff_label.setText("No versions yet: Run records one each time it applies the code.")
            self.diff.setPlainText("")
            return
        text = unified_diff(version.text, self._editor_text(), "this version", "the editor")
        self.diff_label.setText(
            "Changes from this version to the editor's text:" if text else "Same as the editor's text."
        )
        self.diff.setPlainText(text)

    # -- acting ---------------------------------------------------------------------------------

    def put_in_editor(self) -> None:
        version = self.chosen()
        if version is not None:
            self._put(version.text)
            self.refresh_diff()
