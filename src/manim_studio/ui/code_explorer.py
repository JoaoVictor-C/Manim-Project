"""The Code workspace's explorer (P12.5): a tree of what can be edited or used.

Sections (this project's code layers and Python objects, then the preset library: built in, yours,
from the internet) hold rows. The tree knows nothing about the project or the library: the page gives
it ``Section`` lists and hears back which row was opened, which was asked for a menu, and which was
dragged. Rows drag out as ``code_drag`` payloads, so they can be dropped on the timeline, the canvas
and the layers list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem, QWidget

from . import code_drag, icons, theme

KEY_ROLE = Qt.ItemDataRole.UserRole
SOURCE_ROLE = Qt.ItemDataRole.UserRole + 1
KIND_ROLE = Qt.ItemDataRole.UserRole + 2
NAME_ROLE = Qt.ItemDataRole.UserRole + 3

KIND_BADGE = {"object": "obj", "scene": "scene"}


@dataclass(frozen=True)
class Row:
    key: str  # a layer id, or a preset id
    label: str
    kind: str  # "object" or "scene"
    source: str  # "layer" or "preset"
    tip: str = ""
    dirty: bool = False  # unapplied changes (layers)
    state: str = ""  # "", "error", "untrusted", "running" - shown as a marker after the name
    match: str = ""  # more words the filter looks in (a preset's description, tags and kind)


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    rows: tuple[Row, ...] = ()
    empty: str = ""  # shown (greyed) when there are no rows
    extra: dict = field(default_factory=dict)


class CodeExplorer(QTreeWidget):
    opened = Signal(str, str)  # source ("layer" | "preset"), key: double-click or Enter
    chosen = Signal(str, str)  # source, key: the current row changed
    menuRequested = Signal(str, str, QPoint)  # source, key ("" for a section header), global position
    filesDropped = Signal(list)  # .py files dragged in from the desktop

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setObjectName("codeExplorer")
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)
        self.setAcceptDrops(True)
        self.currentItemChanged.connect(self._on_current)
        self.itemActivated.connect(self._on_activated)
        self.itemDoubleClicked.connect(self._on_activated)
        self._filter = ""
        self._sections: list[Section] = []
        self._collapsed: set[str] = set()
        self.itemExpanded.connect(lambda item: self._remember(item, False))
        self.itemCollapsed.connect(lambda item: self._remember(item, True))

    # -- content ------------------------------------------------------------------------------

    def set_sections(self, sections: list[Section], current: tuple[str, str] | None = None) -> None:
        """Show ``sections``; keep the current row (or select ``current``) when it is still there."""
        if current is None:
            current = self.current()
        self._sections = list(sections)
        self._rebuild(current)

    def set_filter(self, text: str) -> None:
        self._filter = text.strip().casefold()
        self._rebuild(self.current())

    def current(self) -> tuple[str, str] | None:
        item = self.currentItem()
        if item is None or item.parent() is None:
            return None
        return item.data(0, SOURCE_ROLE), item.data(0, KEY_ROLE)

    def select(self, source: str, key: str) -> bool:
        item = self._find(source, key)
        if item is None:
            return False
        self.setCurrentItem(item)
        return True

    def rows(self) -> list[tuple[str, str, str]]:
        """(section, source, key) of the rows shown, top to bottom."""
        out = []
        for top in self._tops():
            for i in range(top.childCount()):
                child = top.child(i)
                if child.data(0, KEY_ROLE) is not None:
                    out.append((top.data(0, KEY_ROLE), child.data(0, SOURCE_ROLE), child.data(0, KEY_ROLE)))
        return out

    def texts(self, section: str) -> list[str]:
        """The text of each row of ``section`` as shown (marks included)."""
        for top in self._tops():
            if top.data(0, KEY_ROLE) == section:
                return [
                    top.child(i).text(0)
                    for i in range(top.childCount())
                    if top.child(i).data(0, KEY_ROLE) is not None
                ]
        return []

    def _tops(self) -> list[QTreeWidgetItem]:
        return [self.topLevelItem(i) for i in range(self.topLevelItemCount())]

    def _find(self, source: str, key: str) -> QTreeWidgetItem | None:
        for top in self._tops():
            for i in range(top.childCount()):
                child = top.child(i)
                if child.data(0, SOURCE_ROLE) == source and child.data(0, KEY_ROLE) == key:
                    return child
        return None

    def _rebuild(self, current: tuple[str, str] | None) -> None:
        colours = theme.THEME
        self.blockSignals(True)
        self.clear()
        for section in self._sections:
            top = QTreeWidgetItem([section.title])
            top.setData(0, KEY_ROLE, section.key)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            self.addTopLevelItem(top)
            shown = [row for row in section.rows if self._matches(row)]
            for row in shown:
                top.addChild(self._item(row))
            if not shown and (section.empty or self._filter):
                note = QTreeWidgetItem(["No match" if self._filter and section.rows else section.empty])
                note.setFlags(Qt.ItemFlag.NoItemFlags)
                note.setForeground(0, QBrush(QColor(colours.muted)))
                top.addChild(note)
            top.setExpanded(section.key not in self._collapsed or bool(self._filter))
        self.blockSignals(False)
        if current is not None:
            item = self._find(*current)
            if item is not None:
                self.blockSignals(True)
                self.setCurrentItem(item)
                self.blockSignals(False)

    def _matches(self, row: Row) -> bool:
        if not self._filter:
            return True
        words = f"{row.label} {row.match}".casefold()
        return all(word in words for word in self._filter.split())

    def _item(self, row: Row) -> QTreeWidgetItem:
        colours = theme.THEME
        marks = []
        if row.dirty:
            marks.append("●")  # a dot: unapplied changes
        if row.state == "error":
            marks.append("!")
        elif row.state == "untrusted":
            marks.append("?")
        label = f"{row.label}  {' '.join(marks)}" if marks else row.label
        item = QTreeWidgetItem([label])
        item.setData(0, KEY_ROLE, row.key)
        item.setData(0, SOURCE_ROLE, row.source)
        item.setData(0, KIND_ROLE, row.kind)
        item.setData(0, NAME_ROLE, row.label)
        item.setIcon(0, icons.icon("py-object" if row.kind == "object" else "py-scene"))
        badge = KIND_BADGE.get(row.kind, row.kind)
        item.setToolTip(0, row.tip or f"{row.label} ({badge})")
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )
        if row.state == "error":
            item.setForeground(0, QBrush(QColor(colours.error_text)))
        elif row.dirty or row.state == "untrusted":
            item.setForeground(0, QBrush(QColor(colours.warning)))
        return item

    def _remember(self, item: QTreeWidgetItem, collapsed: bool) -> None:
        if item.parent() is None and not self._filter:
            key = item.data(0, KEY_ROLE)
            (self._collapsed.add if collapsed else self._collapsed.discard)(key)

    # -- events -------------------------------------------------------------------------------

    def _on_current(self, item: QTreeWidgetItem | None, _previous) -> None:
        if item is not None and item.parent() is not None and item.data(0, KEY_ROLE) is not None:
            self.chosen.emit(item.data(0, SOURCE_ROLE), item.data(0, KEY_ROLE))

    def _on_activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        if item.parent() is None:
            item.setExpanded(not item.isExpanded())
        elif item.data(0, KEY_ROLE) is not None:
            self.opened.emit(item.data(0, SOURCE_ROLE), item.data(0, KEY_ROLE))

    def _on_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        where = self.viewport().mapToGlobal(pos)
        if item is None:
            self.menuRequested.emit("", "", where)
        elif item.parent() is None:
            self.menuRequested.emit("section", item.data(0, KEY_ROLE), where)
        elif item.data(0, KEY_ROLE) is not None:
            self.setCurrentItem(item)
            self.menuRequested.emit(item.data(0, SOURCE_ROLE), item.data(0, KEY_ROLE), where)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None or item.parent() is None or item.data(0, KEY_ROLE) is None:
            return
        mime = code_drag.encode(
            item.data(0, SOURCE_ROLE),
            item.data(0, KEY_ROLE),
            item.data(0, NAME_ROLE),
            item.data(0, KIND_ROLE),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)

    # -- files dropped from the desktop -------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if code_drag.python_files(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if code_drag.python_files(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        files = code_drag.python_files(event.mimeData())
        if not files:
            event.ignore()
            return
        event.acceptProposedAction()
        self.filesDropped.emit(files)
