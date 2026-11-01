"""The Add object popover (Lumen, ADR 0087): where objects come from, as in a design tool's insert panel.

A card that floats where it was asked for (the Layers header's "+", the footer's Add object, Shift+A):

* a **search field** on top - type to filter every object; the arrows move over the results, Enter adds the
  one marked (the first, at first), Escape closes;
* the **Recent** row: the last six objects added, as chips (the glyph alone when the names do not fit);
* the categories as a column of icons on the left, and the objects of the one open as a grid of tiles - each
  the drawn outline of the object and its name;
* a footer line, **Presets...**, which opens the presets browser.

The popover only *offers*: choosing a tile emits ``picked`` with its ``Entry`` and closes; the Layers panel
adds the object by the same paths as ever (``add_object``, ``add_python_object``, the equation steps dialog).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QGuiApplication, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..session import insert_catalogue as catalogue
from ..session.insert_catalogue import Entry
from ..style import fuzzy, icons, object_glyphs, theme

CARD_WIDTH = 460
CARD_HEIGHT = 452
SHADOW = 16  # px of the window around the card, for its shadow
COLUMNS = 4
TILE = QSize(90, 78)
TILE_GAP = 6
CATEGORY_BUTTON = 34
RECENT_MAX = 6
CHIP_HEIGHT = 26
CHIP_ICON = 14
GLYPH = 30  # px: the drawing on a tile


class _Tile(QAbstractButton):
    """An object: its drawing over its name. The one the keyboard is on (``current``) is ringed."""

    def __init__(self, entry: Entry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.current = False
        self.setObjectName("addTile")
        self.setFixedSize(TILE)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip(entry.tip or entry.label)
        self.setAccessibleName(f"Add {entry.label}")
        self.setText(entry.label)

    def paintEvent(self, event) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.isDown():
            painter.setBrush(theme.qcolor(c.line))
        elif self.current:
            painter.setBrush(theme.qcolor(c.accent_soft))
            painter.setPen(QPen(theme.qcolor(c.accent_line), 1))
        elif self.underMouse():
            painter.setBrush(theme.qcolor(c.hover))
        painter.drawRoundedRect(box, theme.RADIUS_ROW, theme.RADIUS_ROW)
        glyph = QRectF((self.width() - GLYPH) / 2, 10, GLYPH, GLYPH)
        tint = "accent_text" if self.current else "text"
        object_glyphs.paint(painter, glyph, self.entry.type_name or _glyph_name(self.entry), tint)
        painter.setFont(theme.font("caption"))
        painter.setPen(theme.qcolor(c.text if self.current else c.muted))
        text = QRectF(4, 46, self.width() - 8, self.height() - 50)
        painter.drawText(
            text, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            self.entry.label,
        )  # fmt: skip
        painter.end()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        owner = self.window()
        if isinstance(owner, AddObjectPopover):
            owner.mark(self)


def _glyph_name(entry: Entry) -> str:
    """What to draw for an entry that is not a library type: a Python object, the steps, the camera."""
    return {"python": "Python", "steps": "MathTex", "camera": "Camera"}.get(entry.kind, "")


class _Chip(QAbstractButton):
    """A recent object: its drawing, and its name when there is room."""

    def __init__(self, entry: Entry, labelled: bool, width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry, self.labelled = entry, labelled
        self.setObjectName("addChip")
        self.setFixedSize(width, CHIP_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip(entry.label)
        self.setAccessibleName(f"Add {entry.label} again")
        self.setText(entry.label)

    @staticmethod
    def label_width(entry: Entry) -> int:
        return 10 + CHIP_ICON + 6 + QFontMetrics(theme.font("caption")).horizontalAdvance(entry.label) + 10

    def paintEvent(self, event) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(theme.qcolor(c.line_strong if self.underMouse() else c.line), 1))
        painter.setBrush(
            theme.qcolor(c.line if self.isDown() else c.surface_3 if self.underMouse() else c.panel)
        )
        painter.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        left = 10.0 if self.labelled else (self.width() - CHIP_ICON) / 2
        glyph = QRectF(left, (self.height() - CHIP_ICON) / 2, CHIP_ICON, CHIP_ICON)
        object_glyphs.paint(painter, glyph, self.entry.type_name or _glyph_name(self.entry), "text")
        if self.labelled:
            painter.setFont(theme.font("caption"))
            painter.setPen(theme.qcolor(c.muted))
            text = QRectF(glyph.right() + 6, 0, self.width() - glyph.right() - 10, self.height())
            painter.drawText(
                text, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.entry.label
            )
        painter.end()


class _CategoryButton(QAbstractButton):
    """A category of the left column: its icon, with the accent while it is the open one."""

    def __init__(self, category: catalogue.Category, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.category = category
        self.setObjectName("addCategory")
        self.setCheckable(True)
        self.setFixedSize(CATEGORY_BUTTON, CATEGORY_BUTTON)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip(category.title)
        self.setAccessibleName(category.title)
        self.setText(category.title)

    def paintEvent(self, event) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.isChecked():
            painter.setPen(QPen(theme.qcolor(c.accent_line), 1))
            painter.setBrush(theme.qcolor(c.accent_soft))
        elif self.underMouse():
            painter.setBrush(theme.qcolor(c.hover))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, theme.RADIUS_SMALL + 1, theme.RADIUS_SMALL + 1)
        icon_box = QRect(0, 0, 18, 18)
        icon_box.moveCenter(self.rect().center())
        tint = "accent_text" if self.isChecked() else "muted"
        icons.icon(self.category.icon, tint).paint(painter, icon_box)
        painter.end()


class AddObjectPopover(QWidget):
    """The card. ``refresh`` before it is shown, ``popup`` to show it at an anchor."""

    picked = Signal(object)  # an Entry
    presetsRequested = Signal()

    def __init__(
        self,
        recent_keys: Callable[[], list[str]],
        has_camera: Callable[[], bool],
        parent: QWidget | None = None,
    ) -> None:
        flags = Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
        super().__init__(parent, flags)
        self.setObjectName("addPopover")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.recent_keys, self.has_camera = recent_keys, has_camera
        self.category = catalogue.CATEGORIES[0].key
        self.tiles: list[_Tile] = []
        self.index = 0
        self._entries: list[Entry] = []

        self.search = QLineEdit()
        self.search.setObjectName("addSearch")
        self.search.setPlaceholderText("Search objects")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(32)
        self.search.setAccessibleName("Search objects")
        self.search.addAction(icons.icon("search", tint="faint"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _t: self._fill_grid())
        self.search.installEventFilter(self)

        self.recent_label = QLabel("RECENT")
        self.recent_label.setProperty("role", "section")
        self.recent_label.setFont(theme.font("section"))
        self.recent_row = QHBoxLayout()
        self.recent_row.setContentsMargins(0, 0, 0, 0)
        self.recent_row.setSpacing(TILE_GAP)
        self.recent_empty = QLabel("What you add shows up here")
        self.recent_empty.setProperty("role", "hint")
        recent = QHBoxLayout()
        recent.setContentsMargins(0, 0, 0, 0)
        recent.setSpacing(10)
        recent.addWidget(self.recent_label)
        recent.addLayout(self.recent_row, 1)
        recent.addWidget(self.recent_empty, 1)

        self.categories: dict[str, _CategoryButton] = {}
        self.category_group = QButtonGroup(self)
        self.category_group.setExclusive(False)
        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(2)
        for category in catalogue.CATEGORIES:
            button = _CategoryButton(category)
            button.clicked.connect(lambda _c=False, key=category.key: self.set_category(key))
            self.categories[category.key] = button
            side.addWidget(button)
        side.addStretch(1)

        self.title = QLabel()
        self.title.setProperty("role", "section")
        self.title.setFont(theme.font("section"))
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(TILE_GAP)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty = QLabel("Nothing matches")
        self.empty.setProperty("role", "hint")
        self.scroll = QScrollArea()
        self.scroll.setObjectName("addScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.grid_host)
        self.scroll.viewport().setAutoFillBackground(False)
        self.grid_host.setAutoFillBackground(False)
        body_right = QVBoxLayout()
        body_right.setContentsMargins(0, 0, 0, 0)
        body_right.setSpacing(6)
        body_right.addWidget(self.title)
        body_right.addWidget(self.scroll, 1)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        body.addLayout(side)
        body.addLayout(body_right, 1)

        self.presets_button = QToolButton()
        self.presets_button.setObjectName("addPresets")
        self.presets_button.setText("Presets...")
        self.presets_button.setIcon(icons.icon("presets", tint="muted"))
        self.presets_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.presets_button.setToolTip("Browse the animation presets by their moving preview (Ctrl+Shift+P)")
        self.presets_button.setAccessibleName("Presets")
        self.presets_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.presets_button.setAutoRaise(True)
        self.presets_button.clicked.connect(self._on_presets)
        self.hint = QLabel("Enter adds   Esc closes")
        self.hint.setProperty("role", "hint")
        self.hint.setFont(theme.font("caption"))
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self.presets_button)
        footer.addStretch(1)
        footer.addWidget(self.hint)
        rule = QFrame()
        rule.setObjectName("addRule")
        rule.setFixedHeight(1)

        self.card = QFrame()
        self.card.setObjectName("addCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.card.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        column = QVBoxLayout(self.card)
        column.setContentsMargins(12, 12, 12, 8)
        column.setSpacing(10)
        column.addWidget(self.search)
        column.addLayout(recent)
        column.addLayout(body, 1)
        column.addWidget(rule)
        column.addLayout(footer)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(theme.qcolor(theme.THEME.shadow))
        self.card.setGraphicsEffect(shadow)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        outer.addWidget(self.card)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # -- what it shows ------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Read the catalogue, the recent keys and the project's camera afresh (before showing)."""
        self._entries = [e for e in catalogue.entries() if not (e.kind == "camera" and self.has_camera())]
        present = {e.category for e in self._entries}
        for key, button in self.categories.items():
            button.setVisible(key in present)
        if self.category not in present:
            self.category = catalogue.CATEGORIES[0].key
        self._fill_recent()
        self._fill_grid()

    def _fill_recent(self) -> None:
        while self.recent_row.count():
            item = self.recent_row.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        known = {e.key: e for e in self._entries}
        recent = [known[k] for k in self.recent_keys() if k in known][:RECENT_MAX]
        self.recent_empty.setVisible(not recent)
        if not recent:
            return
        room = CARD_WIDTH - 24 - self.recent_label.sizeHint().width() - 10
        full = [_Chip.label_width(e) for e in recent]
        labelled = sum(full) + TILE_GAP * (len(recent) - 1) <= room
        for entry, width in zip(recent, full, strict=True):
            chip = _Chip(entry, labelled, width if labelled else CHIP_HEIGHT + 4)
            chip.clicked.connect(lambda _c=False, e=entry: self.choose(e))
            self.recent_row.addWidget(chip)
        self.recent_row.addStretch(1)

    def set_category(self, key: str) -> None:
        self.category = key
        if self.search.text():
            self.search.clear()  # a click on a category leaves the search
        else:
            self._fill_grid()

    def _matches(self, query: str) -> list[Entry]:
        """The entries ``query`` names, best first: a name that starts with it, a word that does, the text in
        a name, in the type or category; letters in order only when nothing contains the text."""
        needle = query.casefold()
        tiers: list[tuple[float, Entry]] = []
        for entry in self._entries:
            label = entry.label.casefold()
            if label.startswith(needle):
                tier = 4.0
            elif any(word.startswith(needle) for word in label.replace("-", " ").split()):
                tier = 3.0
            elif needle in label:
                tier = 2.0
            elif needle in entry.search_text.casefold():
                tier = 1.0
            else:
                continue
            tiers.append((tier - len(label) / 1000, entry))
        if not tiers:  # no name holds the text: letters in order (``rtri`` finds Right triangle)
            for entry in self._entries:
                score = fuzzy.score(query, entry.label)
                if score is not None:
                    tiers.append((score / 1000, entry))
        tiers.sort(key=lambda pair: -pair[0])
        return [entry for _score, entry in tiers]

    def _fill_grid(self) -> None:
        query = self.search.text().strip()
        if query:
            shown = self._matches(query)
            self.title.setText(f"{len(shown)} RESULT{'S' * (len(shown) != 1)}")
        else:
            shown = [e for e in self._entries if e.category == self.category]
            self.title.setText(catalogue.CATEGORY_BY_KEY[self.category].title.upper())
        for key, button in self.categories.items():
            button.setChecked(not query and key == self.category)
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self.tiles = []
        section = None
        row = col = 0
        grouped = not query and len({e.section for e in shown}) > 1  # headings only where there are groups
        for entry in shown:
            if grouped and entry.section != section:
                section = entry.section  # plugins and code group by where they come from
                if col:
                    row, col = row + 1, 0
                heading = QLabel(section.upper())
                heading.setProperty("role", "hint")
                heading.setFont(theme.font("section"))
                self.grid.addWidget(heading, row, 0, 1, COLUMNS)
                row += 1
            tile = _Tile(entry)
            tile.clicked.connect(lambda _c=False, e=entry: self.choose(e))
            self.grid.addWidget(tile, row, col)
            self.tiles.append(tile)
            col += 1
            if col == COLUMNS:
                row, col = row + 1, 0
        if not shown:
            self.grid.addWidget(self.empty, 0, 0, 1, COLUMNS)
            self.empty.show()
        self.index = 0
        self._mark_current()

    # -- the keyboard ------------------------------------------------------------------------------

    def _mark_current(self) -> None:
        for i, tile in enumerate(self.tiles):
            wanted = i == self.index
            if tile.current != wanted:
                tile.current = wanted
                tile.update()
        if self.tiles:
            self.scroll.ensureWidgetVisible(self.tiles[self.index], 0, 8)

    def mark(self, tile: _Tile) -> None:
        """The mouse is over ``tile``: Enter would add it."""
        if tile in self.tiles:
            self.index = self.tiles.index(tile)
            self._mark_current()

    def step(self, rows: int = 0, columns: int = 0) -> None:
        if not self.tiles:
            return
        self.index = max(0, min(len(self.tiles) - 1, self.index + rows * COLUMNS + columns))
        self._mark_current()

    def current_entry(self) -> Entry | None:
        return self.tiles[self.index].entry if self.tiles else None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            return self._search_key(event)
        return super().eventFilter(watched, event)

    def _search_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            entry = self.current_entry()
            if entry is not None:
                self.choose(entry)
            return True
        if key == Qt.Key.Key_Down:
            self.step(rows=1)
            return True
        if key == Qt.Key.Key_Up:
            self.step(rows=-1)
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not self.search.text():
            self.step(columns=1 if key == Qt.Key.Key_Right else -1)
            return True
        if key in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp) and not self.search.text():
            keys = [k for k, b in self.categories.items() if not b.isHidden()]
            step = 1 if key == Qt.Key.Key_PageDown else -1
            self.set_category(keys[(keys.index(self.category) + step) % len(keys)])
            return True
        if key == Qt.Key.Key_Escape:
            self.close()
            return True
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if not self.search.hasFocus() and event.text() and event.text().isprintable():
            self.search.setFocus()
            QGuiApplication.sendEvent(self.search, event)  # typing anywhere in the card searches
            return
        super().keyPressEvent(event)

    # -- choosing ----------------------------------------------------------------------------------

    def choose(self, entry: Entry) -> None:
        """Close the card and hand ``entry`` over (after this event: a dialog must not open from a popup)."""
        self.close()
        QTimer.singleShot(0, lambda: self.picked.emit(entry))

    def _on_presets(self) -> None:
        self.close()
        QTimer.singleShot(0, self.presetsRequested.emit)

    # -- showing -----------------------------------------------------------------------------------

    def popup(self, anchor: QWidget, below: bool = False) -> None:
        """Show the card with its edge on ``anchor``: above it (the footer's button) or below it."""
        self.refresh()
        self.search.clear()
        self.adjustSize()
        rect = QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size())
        screen = anchor.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        width, height = self.width(), self.height()
        x = rect.left() - SHADOW
        y = rect.bottom() + 4 - SHADOW if below else rect.top() - height + SHADOW - 4
        x = max(area.left(), min(x, area.right() - width))
        y = max(area.top(), min(y, area.bottom() - height))
        self.move(x, y)
        self.show()
        self.search.setFocus()
        self.search.selectAll()


def _rules(c: theme.Colours) -> str:
    return f"""
QFrame#addCard {{
    background: {c.raised}; border: 1px solid {theme.css(c.line_strong)}; border-radius: 14px;
}}
QFrame#addCard QLabel {{ background: transparent; }}
QFrame#addRule {{ background: {theme.css(c.line)}; border: 0; }}
QScrollArea#addScroll {{ background: transparent; border: 0; }}
QScrollArea#addScroll > QWidget > QWidget {{ background: transparent; }}
QLineEdit#addSearch {{ background: {c.field}; }}
QToolButton#addPresets {{
    background: transparent; border: 0; color: {c.muted}; padding: 4px 8px; font-weight: 500;
}}
QToolButton#addPresets:hover {{ background: {theme.css(c.hover)}; color: {c.text}; }}
"""


theme.register_rules(_rules)
