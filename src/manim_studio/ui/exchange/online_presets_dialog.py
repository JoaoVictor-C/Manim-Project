"""Get presets from the internet (P12.6).

Paste a link - a ``.py`` file, a folder or repository on GitHub, a gist, or an ``index.json`` made by
Export - and the window lists the code it finds; pick what you want, look at it, and it goes to the
import window like any other file. Links used before are kept. Downloads run in the background and are
only text: nothing is imported or run, and nothing downloaded runs until you allow it.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import shiboken6
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.exchange import preset_online
from ...core.exchange.code_import import ImportItem
from ...core.exchange.preset_online import OnlineEntry, OnlineError
from ..code.code_editor import CodeEditor
from ..code.dialog_frame import DialogFrame, ghost

SOURCES_OPTION = "code_online_sources"
MAX_SOURCES = 20
HINT = (
    "Paste a link to a .py file, a GitHub folder or repository, a gist, or an index.json "
    "(File > Export writes one)."
)


def load_sources(raw: str) -> list[str]:
    """The saved links from their stored JSON (tolerant: anything else is an empty list)."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item][:MAX_SOURCES]


def remember(sources: list[str], url: str) -> list[str]:
    """``url`` first, the others after it without repeats, at most ``MAX_SOURCES``."""
    return [url, *(s for s in sources if s != url)][:MAX_SOURCES]


class _Signals(QObject):
    done = Signal(object)  # the result
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self.work = work
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.work()
        except OnlineError as error:
            self.signals.failed.emit(str(error))
        except Exception as error:  # a download must never take the editor down
            self.signals.failed.emit(f"{type(error).__name__}: {error}")
        else:
            self.signals.done.emit(result)


class OnlinePresetsDialog(QDialog):
    """Pick presets from a link. ``items()`` are the downloaded ones, once ``accept``ed."""

    def __init__(
        self,
        sources: list[str] | None = None,
        parent: QWidget | None = None,
        *,
        resolver: Callable[[str], list[OnlineEntry]] = preset_online.resolve,
        fetcher: Callable[[OnlineEntry], str] = preset_online.fetch_entry,
        threaded: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Get presets online")
        self.resize(820, 560)
        self.sources = list(sources or [])
        self.resolver, self.fetcher, self.threaded = resolver, fetcher, threaded
        self.entries: list[OnlineEntry] = []
        self._previews: dict[str, str] = {}
        self._downloaded: list[ImportItem] = []
        self._jobs: list[_Job] = []  # kept alive until they report
        self._busy = False

        frame = DialogFrame(self, "import", "Get presets online", HINT)
        layout = frame.body
        row = QHBoxLayout()
        row.setSpacing(8)
        self.link = QComboBox()
        self.link.setEditable(True)
        self.link.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.link.addItems(self.sources)
        self.link.setCurrentText("")
        self.link.lineEdit().setPlaceholderText("https://github.com/owner/repo/tree/main/presets")
        self.link.lineEdit().returnPressed.connect(self.fetch_list)
        self.fetch_button = QPushButton("Find presets")
        self.fetch_button.clicked.connect(self.fetch_list)
        self.forget_button = ghost(QPushButton("Forget link"))
        self.forget_button.setToolTip("Remove this link from the saved ones")
        self.forget_button.clicked.connect(self.forget)
        row.addWidget(self.link, 1)
        row.addWidget(self.fetch_button)
        row.addWidget(self.forget_button)
        layout.addLayout(row)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(16)
        self.list = QListWidget()
        self.list.setObjectName("onlineItems")
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemChanged.connect(self._refresh)
        split.addWidget(self.list)
        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.preview = CodeEditor()
        self.preview.setReadOnly(True)
        self.preview.setObjectName("onlinePreview")
        column.addWidget(self.detail)
        column.addWidget(self.preview, 1)
        split.addWidget(right)
        split.setSizes([280, 540])
        layout.addWidget(split, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_button.setText("Download and import…")
        self.buttons.accepted.connect(self.download_checked)
        self.buttons.rejected.connect(self.reject)
        frame.add_footer(self.status, 1)
        frame.add_buttons(self.buttons)
        self._refresh()

    # -- running work off the interface thread -----------------------------------------------

    def _run(
        self, work: Callable[[], object], done: Callable[[object], None], failed: Callable[[str], None]
    ) -> None:
        self._set_busy(True)

        def finish(callback, value) -> None:
            if not shiboken6.isValid(self):  # a download that ends after the window was deleted
                return
            self._set_busy(False)
            callback(value)

        if not self.threaded:
            try:
                value = work()
            except OnlineError as error:
                finish(failed, str(error))
            else:
                finish(done, value)
            return
        job = _Job(work)
        self._jobs.append(job)
        job.signals.done.connect(lambda value: finish(done, value))
        job.signals.failed.connect(lambda text: finish(failed, text))
        QThreadPool.globalInstance().start(job)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.fetch_button.setEnabled(not busy)
        self._refresh()

    # -- the list ----------------------------------------------------------------------------

    def url(self) -> str:
        return self.link.currentText().strip()

    def fetch_list(self) -> None:
        url = self.url()
        if not url:
            self.status.setText("Paste a link first")
            return
        self.status.setText("Looking…")
        self._run(lambda: self.resolver(url), lambda found: self._listed(url, found), self._failed)

    def _listed(self, url: str, found: object) -> None:
        self.entries = list(found)  # type: ignore[call-overload]
        self.sources = remember(self.sources, url)
        self.list.blockSignals(True)
        self.list.clear()
        for entry in self.entries:
            suffix = f"  —  {entry.kind_hint}" if entry.kind_hint else ""
            item = QListWidgetItem(entry.name + suffix)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setToolTip(entry.description or entry.url)
            self.list.addItem(item)
        self.list.blockSignals(False)
        count = len(self.entries)
        self.status.setText(f"Found {count} preset{'s' if count != 1 else ''}. Tick the ones you want.")
        if self.entries:
            self.list.setCurrentRow(0)
        self._refresh()

    def _failed(self, text: str) -> None:
        self.status.setText(text)

    def _on_row(self, row: int) -> None:
        if not 0 <= row < len(self.entries):
            self.detail.setText("")
            self.preview.set_text("", 0)
            return
        entry = self.entries[row]
        size = f" — {entry.size} bytes" if entry.size else ""
        self.detail.setText(f"{entry.description or entry.name}\n{entry.url}{size}")
        if entry.url in self._previews:
            self.preview.set_text(self._previews[entry.url], 0)
            return
        self.preview.set_text("Loading preview…", 0)
        self._run(
            lambda: self.fetcher(entry),
            lambda text: self._previewed(entry, str(text)),
            lambda why: self.preview.set_text(f"# Could not load a preview: {why}\n", 0),
        )

    def _previewed(self, entry: OnlineEntry, text: str) -> None:
        self._previews[entry.url] = text
        row = self.list.currentRow()
        if 0 <= row < len(self.entries) and self.entries[row].url == entry.url:
            self.preview.set_text(text, 0)

    def checked(self) -> list[OnlineEntry]:
        return [
            entry
            for row, entry in enumerate(self.entries)
            if self.list.item(row).checkState() == Qt.CheckState.Checked
        ]

    def forget(self) -> None:
        url = self.url()
        self.sources = [s for s in self.sources if s != url]
        index = self.link.findText(url)
        if index >= 0:
            self.link.removeItem(index)
        self.link.setCurrentText("")

    def _refresh(self, *_args) -> None:
        self.import_button.setEnabled(bool(self.checked()) and not self._busy)

    # -- the answer --------------------------------------------------------------------------

    def download_checked(self) -> None:
        """Download the ticked presets, then close; ``items()`` has them."""
        entries = self.checked()
        if not entries:
            return
        self.status.setText(f"Downloading {len(entries)}…")

        def work() -> list[ImportItem]:
            return [
                ImportItem(self._previews.get(e.url) or self.fetcher(e), e.url, e.name + ".py")
                for e in entries
            ]

        self._run(work, self._downloaded_all, self._failed)

    def _downloaded_all(self, items: object) -> None:
        self._downloaded = list(items)  # type: ignore[call-overload]
        self.accept()

    def items(self) -> list[ImportItem]:
        return self._downloaded
