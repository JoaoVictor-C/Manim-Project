"""The Code workspace's explorer (P12.5): a tree of what can be edited or used.

Sections (this project's code layers and Python objects, its helpers (ADR 0058), then the preset
library: built in, yours, from the internet) hold rows. The tree knows nothing about the project or
the library: the page gives it ``Section`` lists and hears back which row was opened, which was
asked for a menu, and which was dragged. Rows drag out as ``code_drag`` payloads, so they can be
dropped on the timeline, the canvas and the layers list - except helpers, which are imported by code
and have no place or time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QModelIndex, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QFont, QFontMetricsF, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ..session import code_drag
from ..style import icons, theme
from ..style.render_activity import INTERVAL_MS, spinner
from .code_chrome import chip_font, paint_chip, paint_kind

KEY_ROLE = Qt.ItemDataRole.UserRole
SOURCE_ROLE = Qt.ItemDataRole.UserRole + 1
KIND_ROLE = Qt.ItemDataRole.UserRole + 2
NAME_ROLE = Qt.ItemDataRole.UserRole + 3
STATE_ROLE = Qt.ItemDataRole.UserRole + 4
DIRTY_ROLE = Qt.ItemDataRole.UserRole + 5
BADGE_ROLE = Qt.ItemDataRole.UserRole + 6
ROW_HEIGHT = 38  # a 36 px row and its 1 px margins
HEADER_HEIGHT = 30

KIND_BADGE = {"object": "obj", "scene": "scene", "helper": "helper"}
ICONS = {"object": "py-object", "scene": "py-scene", "helper": "helper"}


@dataclass(frozen=True)
class Row:
    key: str  # a layer id, a preset id, or "helper:<name>" for a helper of the project
    label: str
    kind: str  # "object", "scene" or "helper"
    source: str  # "layer", "helper" or "preset"
    tip: str = ""
    dirty: bool = False  # unapplied changes (layers)
    state: str = ""  # "", "error", "untrusted", "queued", "running" - shown as a marker after the name
    match: str = ""  # more words the filter looks in (a preset's description, tags and kind)
    badge: str = (
        ""  # a quiet chip at the right when nothing more urgent is said ("built", "built in", "mine")
    )


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    rows: tuple[Row, ...] = ()
    empty: str = ""  # shown (greyed) when there are no rows
    extra: dict = field(default_factory=dict)


def row_chip(state: str, dirty: bool, badge: str) -> tuple[str, str] | None:
    """(text, tone) of the chip at the right of a row: what most needs saying, or the quiet badge."""
    if dirty:
        return "unapplied", "warn"
    found = {
        "error": ("error", "bad"),
        "untrusted": ("not run", "warn"),
        "running": ("running", "accent"),
        "queued": ("waiting", "neutral"),
    }.get(state)
    if found is not None:
        return found
    return (badge, "ok" if badge == "built" else "neutral") if badge else None


class ExplorerDelegate(QStyledItemDelegate):
    """Paints the explorer like the Layers rows (Lumen): section labels in small capitals, rows with a
    rounded kind chip, the name and a state chip, the current row tinted with the accent. The item text keeps
    its marks for the page and its tests; the painting reads the roles instead."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        if not index.parent().isValid():
            return QSize(option.rect.width(), HEADER_HEIGHT if index.row() else HEADER_HEIGHT - 4)
        return QSize(option.rect.width(), ROW_HEIGHT if index.data(KEY_ROLE) is not None else 28)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        colours = theme.THEME
        rect = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not index.parent().isValid():  # a section
            font = theme.font("section")
            font.setPixelSize(10)
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 110)
            painter.setFont(font)
            painter.setPen(theme.qcolor(colours.faint))
            text = str(index.data(Qt.ItemDataRole.DisplayRole) or "").upper()
            area = rect.adjusted(14, 0, -28, -2)
            painter.drawText(area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, text)
            tree = option.widget
            item = tree.itemFromIndex(index) if isinstance(tree, QTreeWidget) else None
            if item is not None and item.childCount():
                self._chevron(painter, QPointF(rect.right() - 18, rect.bottom() - 9), item.isExpanded())
            painter.restore()
            return
        if index.data(KEY_ROLE) is None:  # a greyed note ("No match", "Import a folder ...")
            painter.setFont(theme.font("caption"))
            painter.setPen(theme.qcolor(colours.faint))
            text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
            area = rect.adjusted(18, 0, -10, 0)
            shown = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(area.width()))
            painter.drawText(area, Qt.AlignmentFlag.AlignVCenter, shown)
            painter.restore()
            return
        row = rect.adjusted(6, 1, -6, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setPen(QPen(theme.qcolor(colours.accent_line), 1))
            painter.setBrush(theme.qcolor(colours.accent_soft))
            painter.drawRoundedRect(row.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS_ROW, theme.RADIUS_ROW)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor(colours.raised))
            painter.drawRoundedRect(row, theme.RADIUS_ROW, theme.RADIUS_ROW)
        kind = "preset" if index.data(SOURCE_ROLE) == "preset" else str(index.data(KIND_ROLE) or "scene")
        chip = QRectF(row.left() + 8, row.center().y() - 11, 22, 22)
        paint_kind(painter, chip, kind)
        right = row.right() - 8
        said = row_chip(
            str(index.data(STATE_ROLE) or ""), bool(index.data(DIRTY_ROLE)), str(index.data(BADGE_ROLE) or "")
        )
        if said is not None:
            text, tone = said
            if text == "running":
                text = f"{spinner()} running"
            width = QFontMetricsF(chip_font()).horizontalAdvance(text) + 14
            box = QRectF(right - width, row.center().y() - 9, width, 18)
            paint_chip(painter, box, text, tone)
            right = box.left() - 6
        name = str(index.data(NAME_ROLE) or index.data(Qt.ItemDataRole.DisplayRole) or "")
        font = theme.font("label")
        painter.setFont(font)
        state = index.data(STATE_ROLE)
        painter.setPen(theme.qcolor(colours.error_text if state == "error" else colours.text))
        left = chip.right() + 9
        shown = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(right - left))
        painter.drawText(
            QRectF(left, row.top(), right - left, row.height()), Qt.AlignmentFlag.AlignVCenter, shown
        )
        painter.restore()

    @staticmethod
    def _chevron(painter: QPainter, centre: QPointF, open_: bool) -> None:
        pen = QPen(theme.qcolor(theme.THEME.faint), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        x, y = centre.x(), centre.y()
        if open_:
            painter.drawPolyline([QPointF(x - 3.5, y - 1.5), QPointF(x, y + 2), QPointF(x + 3.5, y - 1.5)])
        else:
            painter.drawPolyline([QPointF(x - 1.5, y - 3.5), QPointF(x + 2, y), QPointF(x - 1.5, y + 3.5)])


class CodeExplorer(QTreeWidget):
    opened = Signal(str, str)  # source ("layer" | "helper" | "preset"), key: double-click or Enter
    chosen = Signal(str, str)  # source, key: the current row changed
    menuRequested = Signal(str, str, QPoint)  # source, key ("" for a section header), global position
    filesDropped = Signal(list)  # .py files dragged in from the desktop

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setObjectName("codeExplorer")
        # Lumen: no branch arrows or indent; a section's label carries its chevron and a click folds it
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setItemDelegate(ExplorerDelegate(self))
        self.setMouseTracking(True)
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self._spin_timer = QTimer(self)  # turns the spinner of the rows that are rendering (ADR 0059)
        self._spin_timer.setInterval(INTERVAL_MS)
        self._spin_timer.timeout.connect(self._spin)
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
        self._spin_timer.start() if self._running_items() else self._spin_timer.stop()
        if current is not None:
            item = self._find(*current)
            if item is not None:
                self.blockSignals(True)
                self.setCurrentItem(item)
                self.blockSignals(False)

    def _running_items(self) -> list[QTreeWidgetItem]:
        found = []
        for top in self._tops():
            for i in range(top.childCount()):
                if top.child(i).data(0, STATE_ROLE) == "running":
                    found.append(top.child(i))
        return found

    def _spin(self) -> None:
        items = self._running_items()
        if not items:
            self._spin_timer.stop()
            return
        glyph = spinner()
        for item in items:
            item.setText(0, f"{item.data(0, NAME_ROLE)}  {glyph}")

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
        elif row.state == "running":
            marks.append(spinner())
        elif row.state == "queued":
            marks.append("…")
        label = f"{row.label}  {' '.join(marks)}" if marks else row.label
        item = QTreeWidgetItem([label])
        item.setData(0, KEY_ROLE, row.key)
        item.setData(0, SOURCE_ROLE, row.source)
        item.setData(0, KIND_ROLE, row.kind)
        item.setData(0, NAME_ROLE, row.label)
        item.setData(0, STATE_ROLE, row.state)
        item.setData(0, DIRTY_ROLE, row.dirty)
        item.setData(0, BADGE_ROLE, row.badge)
        item.setIcon(0, icons.icon(ICONS.get(row.kind, "py-scene")))
        badge = KIND_BADGE.get(row.kind, row.kind)
        item.setToolTip(0, row.tip or f"{row.label} ({badge})")
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if row.kind != "helper":  # a helper is a module: nothing to drop on the timeline or the canvas
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        item.setFlags(flags)
        if row.state == "error":
            item.setForeground(0, QBrush(QColor(colours.error_text)))
        elif row.dirty or row.state == "untrusted":
            item.setForeground(0, QBrush(QColor(colours.warning)))
        elif row.state in ("running", "queued"):
            item.setForeground(0, QBrush(QColor(colours.accent)))
        return item

    def _remember(self, item: QTreeWidgetItem, collapsed: bool) -> None:
        if item.parent() is None and not self._filter:
            key = item.data(0, KEY_ROLE)
            (self._collapsed.add if collapsed else self._collapsed.discard)(key)

    # -- events -------------------------------------------------------------------------------

    def _on_current(self, item: QTreeWidgetItem | None, _previous) -> None:
        if item is not None and item.parent() is not None and item.data(0, KEY_ROLE) is not None:
            self.chosen.emit(item.data(0, SOURCE_ROLE), item.data(0, KEY_ROLE))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """A click on a section's label folds or unfolds it (the label is its arrow in Lumen)."""
        item = self.itemAt(event.position().toPoint())
        if item is not None and item.parent() is None and event.button() == Qt.MouseButton.LeftButton:
            item.setExpanded(not item.isExpanded())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None and item.parent() is None:  # the press already folded it
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

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
        if item.data(0, KIND_ROLE) == "helper":
            return  # helpers are imported by code, not placed (ADR 0058)
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
