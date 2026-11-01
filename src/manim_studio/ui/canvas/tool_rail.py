"""The Stage's tool rail (Lumen, ADR 0087): a slim vertical pill of tools, grouped by hairlines as a design
tool groups them.

* **Select** (V) and **Hand** (H);
* the **insert tools** - Shape (R), Line (L), Text (T), Math (E), Media (I), Graph (X), 3D (D). Each shows the
  glyph of the variant used last and a small corner triangle: a click arms the tool (the next click on the
  Stage places that variant); the triangle, a right-click or a long press opens a flyout of the group's
  variants, with their keys at the right and the one used last marked;
* **Anchor** (P), which moves the selected object's pivot.

The keys work while the canvas has the keyboard (``bind_shortcuts``) and never take a Ctrl combination. In a
short window the insert tools fold into one button that shows the group used last (its triangle opens every
group). The rail only says which tool is wanted (``modeRequested``) and which variant (``variantsChanged``);
the window sets the canvas's mode and remembers the variants.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QMouseEvent, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import QButtonGroup, QFrame, QMenu, QToolButton, QVBoxLayout, QWidget

from ..session import insert_catalogue as catalogue
from ..style import icons, object_glyphs, theme

BUTTON = 30  # px: a tool's button
PAD = 6  # px: above the first and below the last
SIDE = 3  # px: at the sides
SPACING = 2  # px: between buttons
RULE = 9  # px: a hairline and the space around it
BORDER = 1  # px: the pill's hairline
WIDTH = BUTTON + 2 * SIDE + 2 * BORDER
ICON = 18  # px: a tool's glyph
LONG_PRESS_MS = 420
TRIANGLE = 5.0  # px: the flyout mark's side
INSERT = "insert"  # the folded insert tools' one button


@dataclass(frozen=True)
class Tool:
    mode: str  # what ``modeRequested`` carries: select, hand, anchor or an insert group's key
    title: str
    keys: str
    icon: str  # a name in ``icons.NAMES`` (the glyph of the variant replaces it on an insert tool)
    hint: str = ""


SELECT_TOOLS = (
    Tool("select", "Select", "V", "tool-select", "Click an object to select it; drag to move it"),
    Tool("hand", "Hand", "H", "tool-hand", "Drag to pan the Stage"),
)
ANCHOR_TOOL = Tool("anchor", "Anchor", "P", "anchor", "Drag to move the selected object's pivot")


def _escape(text: str) -> str:
    return text.replace("&", "&&")


class RailButton(QToolButton):
    """A tool: a glyph, the accent halo while it is the active tool, and for an insert tool the corner
    triangle that opens its flyout (also a right-click, a long press)."""

    flyoutRequested = Signal()

    def __init__(self, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.mode = mode
        self.setObjectName("railButton")
        self.setCheckable(True)
        self.setFixedSize(BUTTON, BUTTON)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the keyboard stays with the canvas
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.glyph_icon: str | None = None  # a name in icons.NAMES
        self.glyph_type: str | None = None  # a library type, drawn as its outline
        self.has_flyout = False
        self._swallow_release = False
        self._long_press = QTimer(self)
        self._long_press.setSingleShot(True)
        self._long_press.setInterval(LONG_PRESS_MS)
        self._long_press.timeout.connect(self._on_long_press)

    def sizeHint(self) -> QSize:
        return QSize(BUTTON, BUTTON)

    # -- the flyout's triggers -------------------------------------------------------------------

    def _in_triangle(self, pos: QPointF) -> bool:
        return self.has_flyout and pos.x() >= BUTTON - 12 and pos.y() >= BUTTON - 12

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton and self.has_flyout:
            self._swallow_release = True
            self.flyoutRequested.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._in_triangle(event.position()):
            self._swallow_release = True
            self.flyoutRequested.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.has_flyout:
            self._long_press.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._long_press.stop()
        if self._swallow_release:
            self._swallow_release = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _on_long_press(self) -> None:
        if self.isDown():
            self._swallow_release = True
            self.setDown(False)
            self.flyoutRequested.emit()

    # -- painting -------------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        round_ = theme.RADIUS_SMALL + 1
        active = self.isChecked()
        if active:
            halo = theme.qcolor(c.accent)
            halo.setAlpha(70)
            painter.setPen(QPen(halo, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(-0.5, -0.5, 0.5, 0.5), round_ + 0.5, round_ + 0.5)
            painter.setPen(QPen(theme.qcolor(c.accent_line), 1))
            painter.setBrush(theme.qcolor(c.accent_soft))
            painter.drawRoundedRect(box, round_, round_)
        elif self.isDown() or self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor(c.line if self.isDown() else c.hover))
            painter.drawRoundedRect(box, round_, round_)
        tint = "accent_text" if active else "text"
        glyph = QRectF((BUTTON - ICON) / 2, (BUTTON - ICON) / 2, ICON, ICON)
        if self.glyph_type is not None:
            object_glyphs.paint(painter, glyph, self.glyph_type, tint, disabled=not self.isEnabled())
        elif self.glyph_icon is not None:
            icons.icon(self.glyph_icon, tint).paint(painter, glyph.toRect(), mode=QIcon.Mode.Normal)
        if self.has_flyout:
            corner = QPointF(BUTTON - 4.5, BUTTON - 4.5)
            mark = QPainterPath(QPointF(corner.x() - TRIANGLE, corner.y()))
            mark.lineTo(corner)
            mark.lineTo(corner.x(), corner.y() - TRIANGLE)
            mark.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor(c.accent_text if active else c.muted))
            painter.drawPath(mark)
        painter.end()


class _Rule(QWidget):
    """A hairline between groups of tools."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(BUTTON, RULE)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(theme.qcolor(theme.THEME.line_strong), 1))
        y = self.height() // 2
        painter.drawLine(7, y, self.width() - 8, y)
        painter.end()


class ToolRail(QFrame):
    """The pill. ``buttons`` maps each tool's mode to its button (the window and the tests click them)."""

    modeRequested = Signal(str)  # a tool was chosen: select, hand, anchor or an insert group's key
    variantsChanged = Signal()  # the variant an insert tool places changed (to be remembered)

    def __init__(self, variants: dict[str, str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stageToolRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(WIDTH)
        self.variants: dict[str, str] = {
            g.key: catalogue.variant_or_default(g.key, (variants or {}).get(g.key))
            for g in catalogue.INSERT_GROUPS
        }
        self.last_group = catalogue.INSERT_GROUPS[0].key  # what the folded button stands for
        self.mode = "select"
        self.folded = False
        self.buttons: dict[str, RailButton] = {}
        self._shortcuts: list[QShortcut] = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        column = QVBoxLayout(self)
        column.setContentsMargins(SIDE, PAD, SIDE, PAD)
        column.setSpacing(SPACING)
        for tool in SELECT_TOOLS:
            column.addWidget(self._tool_button(tool))
        self._rules = [_Rule(self), _Rule(self)]
        column.addWidget(self._rules[0])
        self.insert_buttons: list[RailButton] = []
        for group in catalogue.INSERT_GROUPS:
            button = self._insert_button(group)
            self.insert_buttons.append(button)
            column.addWidget(button)
        self.fold_button = RailButton(INSERT, self)  # the folded insert tools
        self.fold_button.has_flyout = True
        self.fold_button.flyoutRequested.connect(lambda: self._open_flyout(INSERT))
        self.fold_button.clicked.connect(lambda _c=False: self.modeRequested.emit(self.last_group))
        self.fold_button.hide()
        column.addWidget(self.fold_button)
        column.addWidget(self._rules[1])
        column.addWidget(self._tool_button(ANCHOR_TOOL))
        for button in (*self.buttons.values(), self.fold_button):
            self.group.addButton(button)
        self._refresh_all()
        self.set_mode("select")
        self.fit(10_000)

    # -- building ------------------------------------------------------------------------------

    def _tool_button(self, tool: Tool) -> RailButton:
        button = RailButton(tool.mode, self)
        button.glyph_icon = tool.icon
        button.setToolTip(f"{tool.title}  ({tool.keys})\n{tool.hint}")
        button.setAccessibleName(tool.title)
        button.clicked.connect(lambda _c=False, mode=tool.mode: self.modeRequested.emit(mode))
        self.buttons[tool.mode] = button
        return button

    def _insert_button(self, group: catalogue.InsertGroup) -> RailButton:
        button = RailButton(group.key, self)
        button.has_flyout = True
        button.flyoutRequested.connect(lambda key=group.key: self._open_flyout(key))
        button.clicked.connect(lambda _c=False, key=group.key: self.modeRequested.emit(key))
        self.buttons[group.key] = button
        return button

    # -- state ---------------------------------------------------------------------------------

    def variant(self, group_key: str) -> str:
        """The library type the group's tool places."""
        return self.variants[group_key]

    def set_variant(self, group_key: str, type_name: str) -> None:
        """Make ``type_name`` the one ``group_key`` places (the button shows it); False change: nothing."""
        type_name = catalogue.variant_or_default(group_key, type_name)
        changed = self.variants.get(group_key) != type_name
        self.variants[group_key] = type_name
        self._refresh_group(group_key)
        if changed:
            self.variantsChanged.emit()

    def set_mode(self, mode: str) -> None:
        """Show ``mode`` as the active tool (the window has already set the canvas's mode)."""
        self.mode = mode
        if mode in catalogue.GROUP_BY_KEY:
            self.last_group = mode
            self._refresh_fold()
        target = self.buttons.get(mode)
        if self.folded and mode in catalogue.GROUP_BY_KEY:
            target = self.fold_button
        if target is not None and not target.isChecked():
            target.setChecked(True)  # the group unchecks the others

    def _tip(self, group: catalogue.InsertGroup) -> str:
        type_name = self.variants[group.key]
        keys = group.keys
        return (
            f"{group.title}: {catalogue.label_of(type_name)}  ({keys})\n"
            "Click, then click the Stage to place it. The corner arrow, a right-click or a long press "
            "lists the others."
        )

    def _refresh_group(self, group_key: str) -> None:
        group = catalogue.GROUP_BY_KEY[group_key]
        button = self.buttons[group_key]
        button.glyph_type = self.variants[group_key]
        button.setToolTip(self._tip(group))
        button.setAccessibleName(f"{group.title} tool: {catalogue.label_of(self.variants[group_key])}")
        button.update()
        if group_key == self.last_group:
            self._refresh_fold()

    def _refresh_fold(self) -> None:
        group = catalogue.GROUP_BY_KEY[self.last_group]
        self.fold_button.glyph_type = self.variants[group.key]
        self.fold_button.setToolTip(self._tip(group))
        self.fold_button.setAccessibleName("Insert tools")
        self.fold_button.update()

    def _refresh_all(self) -> None:
        for group in catalogue.INSERT_GROUPS:
            self._refresh_group(group.key)
        self._refresh_fold()

    # -- folding for a short window --------------------------------------------------------------

    def full_height(self) -> int:
        count = len(SELECT_TOOLS) + len(catalogue.INSERT_GROUPS) + 1
        return self._height_for(count)

    def folded_height(self) -> int:
        return self._height_for(len(SELECT_TOOLS) + 1 + 1)

    @staticmethod
    def _height_for(buttons: int) -> int:
        items = buttons + 2  # and two hairlines
        return 2 * (PAD + BORDER) + buttons * BUTTON + 2 * RULE + (items - 1) * SPACING

    def fit(self, available: int) -> None:
        """Show the insert tools one by one when ``available`` px of height hold them, else as one button."""
        fold = available < self.full_height()
        self.folded = fold
        for button in self.insert_buttons:
            button.setVisible(not fold)
        self.fold_button.setVisible(fold)
        self.setFixedHeight(self.folded_height() if fold else self.full_height())
        self.set_mode(self.mode)

    # -- flyouts ---------------------------------------------------------------------------------

    def choose_variant(self, group_key: str, type_name: str) -> None:
        """A variant from a flyout: it becomes the group's and its tool is armed."""
        self.set_variant(group_key, type_name)
        self.modeRequested.emit(group_key)

    def flyout(self, group_key: str) -> QMenu:
        """The menu of a group's variants (``INSERT``: every group, each a submenu)."""
        menu = QMenu(self)
        menu.setObjectName("railFlyout")
        menu.setToolTipsVisible(True)
        if group_key == INSERT:
            for group in catalogue.INSERT_GROUPS:
                sub = self.flyout(group.key)
                sub.setTitle(group.title)
                sub.setIcon(object_glyphs.icon(self.variants[group.key]))
                menu.addMenu(sub)
        else:
            current = self.variants[group_key]
            group = catalogue.GROUP_BY_KEY[group_key]
            for entry in catalogue.variants(group_key):
                keys = catalogue.VARIANT_KEYS.get(entry.type_name, "")
                text = _escape(entry.label) + (f"\t{keys}" if keys else "")
                action = QAction(object_glyphs.icon(entry.type_name), text, menu)
                action.setCheckable(True)
                action.setChecked(entry.type_name == current)
                action.setToolTip(f"{entry.label} - {group.title}")
                action.triggered.connect(
                    lambda _c=False, key=group_key, name=entry.type_name: self.choose_variant(key, name)
                )
                menu.addAction(action)
        return menu

    def _open_flyout(self, group_key: str) -> None:
        button = self.fold_button if group_key == INSERT else self.buttons[group_key]
        menu = self.flyout(group_key)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(button.mapToGlobal(QPoint(button.width() + 8, -6)))

    # -- keys ------------------------------------------------------------------------------------

    def bind_shortcuts(self, widget: QWidget) -> list[QShortcut]:
        """The tools' keys, active while ``widget`` (the canvas) has the keyboard: a plain letter is never
        taken in a text field, and Ctrl combinations stay with the menus."""
        keys: list[tuple[str, str, str | None]] = []
        for tool in (*SELECT_TOOLS, ANCHOR_TOOL):
            keys.append((tool.keys, tool.mode, None))
        for group in catalogue.INSERT_GROUPS:
            keys.append((group.keys, group.key, None))
        for type_name, sequence in catalogue.VARIANT_KEYS.items():
            owner = next(
                (
                    g
                    for g in catalogue.INSERT_GROUPS
                    if type_name in {e.type_name for e in catalogue.variants(g.key)}
                ),
                None,
            )
            if owner is not None:
                keys.append((sequence, owner.key, type_name))
        for sequence, mode, type_name in keys:
            shortcut = QShortcut(QKeySequence(sequence), widget)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            if type_name is None:
                shortcut.activated.connect(lambda m=mode: self.modeRequested.emit(m))
            else:
                shortcut.activated.connect(lambda g=mode, t=type_name: self.choose_variant(g, t))
            self._shortcuts.append(shortcut)
        return self._shortcuts


class RailColumn(QWidget):
    """The strip at the Stage's left that holds the rail with a margin, and folds it when it does not fit."""

    MARGIN_LEFT = 8
    MARGIN_RIGHT = 4
    MARGIN_VERTICAL = 8

    def __init__(self, rail: ToolRail, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rail = rail
        self.setFixedWidth(self.MARGIN_LEFT + WIDTH + self.MARGIN_RIGHT)
        column = QVBoxLayout(self)
        column.setContentsMargins(
            self.MARGIN_LEFT, self.MARGIN_VERTICAL, self.MARGIN_RIGHT, self.MARGIN_VERTICAL
        )
        column.setSpacing(0)
        column.addWidget(rail, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        column.addStretch(1)

    def fit_to(self, height: int) -> None:
        """Show or fold the insert tools for a strip ``height`` px tall."""
        self.rail.fit(height - 2 * self.MARGIN_VERTICAL)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_to(self.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(self.width(), 0)


def _rules(c: theme.Colours) -> str:
    fill = theme.css(theme.mix(c.raised, c.window, 0.08) + "e6")
    return f"""
QFrame#stageToolRail {{
    background: {fill}; border: 1px solid {theme.css(c.line_strong)}; border-radius: 14px;
}}
QMenu#railFlyout::item {{ padding: 6px 14px 6px 8px; min-width: 150px; }}
QMenu#railFlyout::item:checked {{ color: {c.accent_text}; }}
QMenu#railFlyout::icon {{ padding-left: 0px; }}
QMenu#railFlyout::icon:checked {{
    background: {theme.css(c.accent_soft)}; border: 1px solid {theme.css(c.accent_line)}; border-radius: 5px;
}}
"""


theme.register_rules(_rules)
