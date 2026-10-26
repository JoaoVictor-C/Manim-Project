"""The top bar (Lumen, ADR 0063): the menus, the page switcher and the commands people use all day.

It is a ``QMenuBar`` - the window's real one, so every menu, mnemonic and shortcut works as before - made
52 px tall, with the logo mark in its left corner, a cluster of tools in its right corner (undo, redo, the
search that opens the command palette, the panel switches, full screen and Export) and the page switcher
centred over it. In a narrow window the switcher shows only its icons and the search only its icon.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from ..style import icons, theme
from ..style.page_switcher import PageSwitcher

HEIGHT = 52
COMPACT_BELOW = 1240  # a window narrower than this gets icons only for the switcher and the search


class LogoMark(QWidget):
    """The application mark: a rounded square with the accent gradient and a drawn curve."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setToolTip("Manim Studio")

    def paintEvent(self, event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        from PySide6.QtGui import QLinearGradient, QPainterPath

        box = QRectF(self.rect())
        gradient = QLinearGradient(box.topLeft(), box.bottomRight())
        gradient.setColorAt(0.0, theme.qcolor(c.accent))
        gradient.setColorAt(1.0, theme.qcolor(c.accent_2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(box, 9, 9)
        path = QPainterPath()
        path.moveTo(6.5, 17.5)
        path.cubicTo(10, 17.5, 10, 9.5, 14, 9.5)
        path.cubicTo(18, 9.5, 18, 17.5, 21.5, 15)
        painter.setPen(QPen(theme.qcolor(c.on_accent), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class SearchButton(QPushButton):
    """The button that opens the command palette: a magnifier, a hint and the Ctrl K keycap."""

    HINT = "Search commands"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("searchButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setIcon(icons.icon("search", "muted"))
        self.setToolTip("Search commands, layers and snippets (Ctrl+K)")
        self.setFixedHeight(30)
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self.setText("" if compact else f"  {self.HINT}")
        self.setFixedWidth(34 if compact else 224)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self.width(), 30)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hovered = self.underMouse()
        painter.setPen(QPen(theme.qcolor(c.line_strong if hovered else c.line), 1))
        painter.setBrush(theme.qcolor(c.panel))
        painter.drawRoundedRect(box, theme.RADIUS, theme.RADIUS)
        icon = self.icon().pixmap(32, 32)
        painter.drawPixmap(10, (self.height() - 16) // 2, 16, 16, icon)
        if self._compact:
            return
        painter.setFont(theme.font("label"))
        painter.setPen(theme.qcolor(c.faint))
        painter.drawText(
            QRectF(34, 0, self.width() - 34 - 56, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.HINT,
        )
        key = QRectF(self.width() - 54, (self.height() - 18) / 2, 44, 18)
        painter.setPen(QPen(theme.qcolor(c.line_strong), 1))
        painter.setBrush(theme.qcolor(c.raised))
        painter.drawRoundedRect(key, 5, 5)
        painter.setFont(theme.font("caption", kind="mono"))
        painter.setPen(theme.qcolor(c.muted))
        painter.drawText(key, Qt.AlignmentFlag.AlignCenter, "Ctrl K")


class _Cluster(QWidget):
    """A transparent widget holding a row of controls."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(6)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)


class TopBar(QMenuBar):
    paletteRequested = Signal()
    exportRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        self.setNativeMenuBar(False)
        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        left = _Cluster()
        left.row.setContentsMargins(14, 0, 6, 0)
        self.mark = LogoMark()
        left.row.addWidget(self.mark)
        self.setCornerWidget(left, Qt.Corner.TopLeftCorner)
        self._left = left
        right = _Cluster()
        right.row.setContentsMargins(6, 0, 14, 0)
        self.undo_button = self._tool_button("Undo", "undo")
        self.redo_button = self._tool_button("Redo", "redo")
        self.search = SearchButton()
        self.search.clicked.connect(self.paletteRequested)
        self.panel_layout = QHBoxLayout()  # the panel switches (Layers, Properties, Timeline)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_layout.setSpacing(2)
        self.window_layout = QHBoxLayout()  # full screen
        self.window_layout.setContentsMargins(0, 0, 0, 0)
        self.window_layout.setSpacing(2)
        self.export_button = QPushButton(icons.icon("export", "on_accent"), "Export")
        self.export_button.setProperty("role", "primary")
        self.export_button.setToolTip("Render the video (Ctrl+E)")
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.setFixedHeight(30)
        self.export_button.clicked.connect(self.exportRequested)
        self._separators = [self._separator(), self._separator()]
        for widget in (self.undo_button, self.redo_button, self.search):
            right.row.addWidget(widget)
        right.row.addWidget(self._separators[0])
        right.row.addLayout(self.panel_layout)
        right.row.addLayout(self.window_layout)
        right.row.addWidget(self._separators[1])
        right.row.addWidget(self.export_button)
        right.setParent(self)  # placed by hand at the right edge (a corner widget would sit at the top)
        self._right = right
        self.switcher: PageSwitcher | None = None
        self._project_mode = False

    # -- parts -------------------------------------------------------------------------------------

    @staticmethod
    def _separator() -> QWidget:
        line = QWidget()
        line.setFixedSize(1, 20)
        line.setObjectName("topBarSeparator")
        line.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        return line

    def _tool_button(self, tip: str, glyph: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(icons.icon(glyph, "muted"))
        button.setObjectName("iconButton")
        button.setIconSize(QSize(16, 16))
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setFixedSize(30, 30)
        return button

    def set_switcher(self, switcher: PageSwitcher) -> None:
        """Show the page switcher, centred over the bar."""
        self.switcher = switcher
        switcher.setParent(self)
        switcher.show()
        self._position()

    def bind_history(self, undo: QAction, redo: QAction) -> None:
        """Make the undo and redo buttons act like (and enable like) the Edit menu's actions."""
        for button, action in ((self.undo_button, undo), (self.redo_button, redo)):
            button.clicked.connect(action.trigger)
            action.changed.connect(lambda a=action, b=button: self._sync(b, a))
            self._sync(button, action)

    @staticmethod
    def _sync(button: QToolButton, action: QAction) -> None:
        try:
            enabled, text, shortcut = action.isEnabled(), action.text().replace("&", ""), action.shortcut()
        except RuntimeError:  # the window is closing: the action went before the button heard about it
            return
        button.setEnabled(enabled)
        button.setToolTip(f"{text} ({shortcut.toString()})" if shortcut.count() else text)

    def add_panel_button(self, button: QToolButton) -> None:
        button.setObjectName("iconButton")
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(30, 30)
        self.panel_layout.addWidget(button)
        self._relayout()

    def add_window_button(self, button: QToolButton) -> None:
        button.setObjectName("iconButton")
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(30, 30)
        self.window_layout.addWidget(button)
        self._relayout()

    def set_project_mode(self, has_project: bool) -> None:
        """Without a project there is nothing to switch between or export: only the menus and search stay."""
        self._project_mode = has_project
        for widget in (self.undo_button, self.redo_button, self.export_button, *self._separators):
            widget.setVisible(has_project)
        for layout in (self.panel_layout, self.window_layout):
            for i in range(layout.count()):
                item = layout.itemAt(i).widget()
                if item is not None and not has_project:
                    item.hide()
        if self.switcher is not None:
            self.switcher.setVisible(has_project)
        self._relayout()

    # -- layout ------------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Lay the bar out again (a button was shown or hidden)."""
        self._relayout()

    def _relayout(self) -> None:
        """The corner clusters changed size: tell the menu bar, then centre the switcher again."""
        self._left.adjustSize()
        self.setCornerWidget(self._left, Qt.Corner.TopLeftCorner)
        self._position()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact = self.width() < COMPACT_BELOW
        if compact != self.search._compact:
            self.search.set_compact(compact)
            if self.switcher is not None:
                self.switcher.set_compact(compact)
            self._relayout()
        elif self.switcher is not None and self.switcher.is_compact() != compact:
            self.switcher.set_compact(compact)
        self._position()

    def _position(self) -> None:
        self._right.layout().invalidate()
        self._right.layout().activate()
        width = self._right.layout().sizeHint().width()
        self._right.setGeometry(self.width() - width, 0, width, HEIGHT)
        self._right.show()
        if self.switcher is None:
            return
        self.switcher.adjustSize()
        x = (self.width() - self.switcher.width()) // 2
        self.switcher.move(max(0, x), (self.height() - self.switcher.height()) // 2)
        self.switcher.raise_()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._position()


def install_topbar_rules() -> None:
    """The bar's own stylesheet rules (registered once)."""

    def rules(c: theme.Colours) -> str:
        item = "QMenuBar#topBar::item"
        return " ".join(
            (
                "QMenuBar#topBar { background: transparent; border: 0; padding: 0px 2px; }",
                f"{item} {{ padding: 12px 10px; margin: 0px; background: transparent; color: {c.muted};",
                "border-radius: 8px; font-weight: 500; }",
                f"{item}:selected, {item}:pressed {{ background: {c.raised}; color: {c.text}; }}",
                f"QWidget#topBarSeparator {{ background: {theme.css(c.line_strong)}; }}",
                "QToolButton#iconButton { padding: 0px; border-radius: 9px; }",
            )
        )

    theme.register_rules(rules)


install_topbar_rules()
