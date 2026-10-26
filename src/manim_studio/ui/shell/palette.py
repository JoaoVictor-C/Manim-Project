"""The command palette (Lumen, ADR 0063): Ctrl K reaches every command, layer and page by name.

``collect_items`` walks the window's menus (so a new menu item is in the palette without work) and adds the
layers of the project; ``CommandPalette`` is the centred card with one field and the ranked results. ``>``
narrows to commands and ``@`` to layers. Matching is by letters in order (``quick_open.score``), with the
matched letters drawn in the accent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..style import theme
from ..style.fuzzy import score

WIDTH = 680
ROW = 46
MAX_RESULTS = 40


@dataclass(frozen=True)
class PaletteItem:
    kind: str  # "command" | "layer" | "page"
    title: str
    detail: str = ""  # the menu path, or what the layer is
    shortcut: str = ""
    run: Callable[[], None] | None = None
    enabled: bool = True


def _clean(text: str) -> str:
    return text.replace("&", "").replace("\t", " ").strip()


def collect_actions(menu_or_bar: QWidget, path: str = "") -> list[PaletteItem]:
    """Every enabled, named action under a menu or menu bar (submenus walked), with its menu path."""
    out: list[PaletteItem] = []
    for action in menu_or_bar.actions():
        if action.isSeparator():
            continue
        title = _clean(action.text())
        sub = action.menu()
        if sub is not None:
            out += collect_actions(sub, f"{path} › {title}" if path else title)
        elif title:
            out.append(
                PaletteItem(
                    "command",
                    title.rstrip("…").rstrip("."),
                    path,
                    action.shortcut().toString(QKeySequenceFormat()) if action.shortcut().count() else "",
                    action.trigger,
                    action.isEnabled(),
                )
            )
    return out


def QKeySequenceFormat():
    from PySide6.QtGui import QKeySequence

    return QKeySequence.SequenceFormat.NativeText


def collect_items(window) -> list[PaletteItem]:
    """The window's commands, then its layers."""
    items = collect_actions(window.menuBar())
    project = window.project
    if project is not None:
        for layer in project.layers:
            kind = layer.spec.type if layer.spec is not None else "Layer"
            items.append(
                PaletteItem(
                    "layer",
                    layer.label,
                    f"{kind} layer",
                    "",
                    lambda i=layer.id: window.selection.select_layer(i),
                )
            )
    return items


def match_positions(query: str, text: str) -> list[int]:
    """Where the letters of ``query`` fall in ``text``, in order (empty: they do not all)."""
    if not query:
        return []
    low, found, position = text.casefold(), [], 0
    for letter in query.casefold().replace(" ", ""):
        index = low.find(letter, position)
        if index < 0:
            return []
        found.append(index)
        position = index + 1
    return found


def rank_items(items: list[PaletteItem], query: str) -> list[PaletteItem]:
    """The items that match ``query`` (``>`` commands only, ``@`` layers only), best first."""
    kind = None
    if query.startswith(">"):
        kind, query = "command", query[1:]
    elif query.startswith("@"):
        kind, query = "layer", query[1:]
    query = query.strip()
    pool = [i for i in items if kind is None or i.kind == kind]
    if not query:
        return pool[:MAX_RESULTS]
    scored = []
    for order, item in enumerate(pool):
        value = score(query, item.title)
        if value is None and item.detail:
            detail = score(query, item.detail)
            value = None if detail is None else detail - 40  # a match in the menu path ranks below the name
        if value is not None:
            scored.append((-value, order, item))
    return [item for _, _, item in sorted(scored, key=lambda t: (t[0], t[1]))][:MAX_RESULTS]


class _Delegate(QStyledItemDelegate):
    def __init__(self, palette: CommandPalette) -> None:
        super().__init__(palette.list)
        self.palette = palette

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), ROW)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item: PaletteItem = index.data(Qt.ItemDataRole.UserRole)
        c = theme.THEME
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(option.rect).adjusted(6, 2, -6, -2)
        selected = bool(option.state & option.state.State_Selected)
        if selected:
            painter.setPen(QPen(theme.qcolor(c.accent_line), 1))
            painter.setBrush(theme.qcolor(c.accent_soft))
            painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)
        # the kind chip
        chip = QRectF(box.left() + 10, box.center().y() - 15, 30, 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(c.surface_3))
        painter.drawRoundedRect(chip, 9, 9)
        glyph = {"command": "›", "layer": "▤", "page": "▭"}.get(item.kind, "•")
        painter.setPen(theme.qcolor(c.accent_text if selected else c.muted))
        painter.setFont(theme.font("heading"))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, glyph)
        # the title with the matched letters in the accent
        left = int(chip.right()) + 12
        title_font: QFont = theme.font("label")
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        metrics = QFontMetrics(title_font)
        positions = set(match_positions(self.palette.query_text(), item.title))
        x = float(left)
        top = box.top() + 7
        for index_, letter in enumerate(item.title):
            width = metrics.horizontalAdvance(letter)
            painter.setPen(theme.qcolor(c.accent_text if index_ in positions else c.text))
            painter.drawText(
                QRectF(x, top, width + 2, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                letter,
            )
            x += width
        # the second line
        if item.detail:
            painter.setFont(theme.font("caption"))
            painter.setPen(theme.qcolor(c.faint))
            painter.drawText(
                QRectF(left, box.top() + 24, box.width() - 150, 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                QFontMetrics(theme.font("caption")).elidedText(
                    item.detail, Qt.TextElideMode.ElideRight, int(box.width() - 150)
                ),
            )
        # the shortcut
        if item.shortcut:
            key_font = theme.font("caption", kind="mono")
            painter.setFont(key_font)
            text_width = QFontMetrics(key_font).horizontalAdvance(item.shortcut) + 14
            key = QRectF(box.right() - text_width - 12, box.center().y() - 10, text_width, 20)
            painter.setPen(QPen(theme.qcolor(c.line_strong), 1))
            painter.setBrush(theme.qcolor(c.raised))
            painter.drawRoundedRect(key, 6, 6)
            painter.setPen(theme.qcolor(c.muted))
            painter.drawText(key, Qt.AlignmentFlag.AlignCenter, item.shortcut)
        elif item.kind == "layer":
            painter.setFont(theme.font("caption"))
            painter.setPen(theme.qcolor(c.faint))
            painter.drawText(
                QRectF(box.right() - 90, box.top(), 78, box.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "Layer",
            )
        painter.restore()


class CommandPalette(QDialog):
    """Ctrl K: one field, ranked results, Enter runs the chosen one."""

    def __init__(self, items: list[PaletteItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.items = items
        self.chosen: PaletteItem | None = None
        self.shown: list[PaletteItem] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QWidget()
        self.card.setObjectName("paletteCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.card)
        column = QVBoxLayout(self.card)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.search = QLineEdit()
        self.search.setObjectName("paletteSearch")
        self.search.setPlaceholderText("Search commands, layers and pages…   (> commands, @ layers)")
        self.search.setFont(theme.font("heading"))
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._accept_current)
        column.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("paletteList")
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setItemDelegate(_Delegate(self))
        self.list.itemActivated.connect(lambda _item: self._accept_current())
        self.list.itemClicked.connect(lambda _item: self._accept_current())
        column.addWidget(self.list)
        self.footer = QLabel("↑↓ move    ↵ run    Esc close")
        self.footer.setProperty("role", "hint")
        self.footer.setContentsMargins(18, 8, 18, 10)
        column.addWidget(self.footer)
        self.setFixedWidth(WIDTH)
        self.list.setFixedHeight(ROW * 7 + 8)
        self._filter("")
        self.search.setFocus()

    def query_text(self) -> str:
        text = self.search.text()
        return text[1:] if text[:1] in ">@" else text

    def _filter(self, text: str) -> None:
        self.shown = rank_items(self.items, text)
        self.list.clear()
        for item in self.shown:
            entry = QListWidgetItem()
            entry.setData(Qt.ItemDataRole.UserRole, item)
            if not item.enabled:
                entry.setFlags(entry.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(entry)
        if self.shown:
            self.list.setCurrentRow(0)

    def _accept_current(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.shown) and self.shown[row].enabled:
            self.chosen = self.shown[row]
            self.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, self.list.currentRow() + step)))
            return
        super().keyPressEvent(event)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            self.reject()
        return super().event(event)

    def open_over(self, window: QWidget) -> None:
        """Centre the palette near the top of ``window``."""
        self.adjustSize()
        origin = window.mapToGlobal(QPoint(0, 0))
        self.move(origin.x() + (window.width() - self.width()) // 2, origin.y() + 84)


def install_palette_rules() -> None:
    def rules(c: theme.Colours) -> str:
        return " ".join(
            (
                f"QWidget#paletteCard {{ background: {c.raised};",
                f"border: 1px solid {theme.css(c.line_strong)};",
                "border-radius: 18px; }",
                "QLineEdit#paletteSearch { background: transparent; border: 0; padding: 16px 20px;",
                f"border-bottom: 1px solid {theme.css(c.line)}; border-radius: 0; }}",
                "QListWidget#paletteList { background: transparent; border: 0; padding: 6px; }",
                "QListWidget#paletteList::item { background: transparent; border: 0; }",
            )
        )

    theme.register_rules(rules)


install_palette_rules()
_ = (QApplication, QColor, QRect, QMenu, QAction)  # (kept for the type hints above)
