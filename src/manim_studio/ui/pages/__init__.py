"""Workspace pages (P6b, ADR 0041): the window's tabs, each arranged for one kind of work.

The editor's main views exist once - the viewer (canvas and transport), the
timeline, the Layers and Properties panels - and move between pages: showing a
page re-parents them into its own splitters (B55: about 14 ms), so playback, the
selection and undo stay one. Views a page does not use wait in a hidden parking
widget, never without a parent (a parentless widget would become a window).

A page subclasses ``Page``: ``build()`` makes its widget once, ``place(shared)``
puts the shared views it uses into its layout every time it is shown, and
``on_show`` / ``on_hide`` keep page-specific state. Its splitters' sizes are kept
while the editor runs. Pages are registered in ``MainWindow.__init__`` before the
menus are built, so View > Pages lists them with their Shift+number shortcuts.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtWidgets import QSplitter, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from .. import icons


@dataclass(frozen=True)
class Shared:
    """The views every page may show (one instance each)."""

    viewer: QWidget  # the canvas with its transport
    timeline: QWidget
    layers: QWidget
    properties: QWidget

    def all(self) -> tuple[QWidget, ...]:
        return (self.viewer, self.timeline, self.layers, self.properties)


class Page:
    """One workspace page. Subclasses set ``name``, ``title`` and ``icon`` and build their layout."""

    name = "page"
    title = "Page"
    icon = "compose"
    tooltip = ""

    def __init__(self, window) -> None:
        self.window = window
        self.widget = self.build()
        self._states: dict[int, QByteArray] = {}

    def build(self) -> QWidget:
        raise NotImplementedError

    def place(self, shared: Shared) -> None:
        """Put the shared views this page uses into its layout (called on every show)."""

    def splitters(self) -> list[QSplitter]:
        return self.widget.findChildren(QSplitter) + (
            [self.widget] if isinstance(self.widget, QSplitter) else []
        )

    def save_sizes(self) -> None:
        self._states = {id(s): s.saveState() for s in self.splitters()}

    def restore_sizes(self) -> bool:
        """Put back the splitters' sizes from the last time the page was shown (False the first time)."""
        restored = False
        for splitter in self.splitters():
            state = self._states.get(id(splitter))
            if state is not None:
                splitter.restoreState(state)
                restored = True
        return restored

    def on_show(self) -> None:
        """The page became current (after ``place``)."""

    def on_hide(self) -> None:
        """Another page is about to be shown."""


class PageHost(QWidget):
    """The window's central widget: the pages, stacked, over the page bar."""

    pageChanged = Signal(str)

    def __init__(self, shared: Shared, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.shared = shared
        self.pages: dict[str, Page] = {}
        self.current: str | None = None
        self.hidden: set[QWidget] = set()  # panels hidden from the View menu
        self.stack = QStackedWidget()
        self.parking = QWidget(self)  # views the current page does not use
        self.parking.hide()
        self.bar = QTabBar()
        self.bar.setObjectName("pageBar")
        self.bar.setShape(QTabBar.Shape.RoundedSouth)
        self.bar.setExpanding(False)
        self.bar.setDrawBase(False)
        self.bar.currentChanged.connect(self._on_tab)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignHCenter)
        for view in shared.all():
            view.setParent(self.parking)

    def add(self, page: Page) -> None:
        self.pages[page.name] = page
        self.stack.addWidget(page.widget)
        index = self.bar.addTab(icons.icon(page.icon), page.title)
        self.bar.setTabToolTip(index, page.tooltip or page.title)
        self.bar.setTabData(index, page.name)
        if self.current is None:
            self.show_page(page.name)

    def show_page(self, name: str) -> None:
        if name not in self.pages:
            raise KeyError(name)
        if name == self.current:
            return
        old = self.pages.get(self.current) if self.current else None
        if old is not None:
            old.on_hide()
            old.save_sizes()
        for view in self.shared.all():
            view.setParent(self.parking)
        page = self.pages[name]
        page.place(self.shared)
        for view in self.shared.all():  # a panel hidden from View stays hidden on every page
            if view.parentWidget() is not self.parking:
                view.setVisible(view not in self.hidden)
        page.restore_sizes()
        self.stack.setCurrentWidget(page.widget)
        self.current = name
        index = next(i for i in range(self.bar.count()) if self.bar.tabData(i) == name)
        if self.bar.currentIndex() != index:
            self.bar.blockSignals(True)
            self.bar.setCurrentIndex(index)
            self.bar.blockSignals(False)
        page.on_show()
        self.pageChanged.emit(name)

    def set_visible(self, view: QWidget, visible: bool) -> None:
        """Show or hide a shared panel on every page (View > Layers, View > Properties)."""
        if visible:
            self.hidden.discard(view)
        else:
            self.hidden.add(view)
        if view.parentWidget() is not self.parking:
            view.setVisible(visible)

    def _on_tab(self, index: int) -> None:
        name = self.bar.tabData(index)
        if name:
            self.show_page(name)
