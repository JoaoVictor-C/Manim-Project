"""Workspace pages (P6b, ADR 0041): the window's tabs, each arranged for one kind of work.

The editor's main views exist once - the viewer (canvas and transport), the
timeline, the Layers and Properties panels - and move between pages: showing a
page re-parents them into its own splitters (B55: about 14 ms), so playback, the
selection and undo stay one. Views a page does not use wait in a hidden parking
widget, never without a parent (a parentless widget would become a window).

A page subclasses ``Page``: ``build()`` makes its widget once, ``place(shared)``
puts the shared views it uses into its layout every time it is shown, and
``on_show`` / ``on_hide`` keep page-specific state. Its splitters' sizes are kept
while the editor runs, and between runs in the preferences (P6d.1: ``page_states`` /
``restore_states``, generic for every page). Pages are registered in ``MainWindow.__init__`` before the
menus are built, so View > Pages lists them with their Shift+number shortcuts.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, Signal
from PySide6.QtWidgets import (
    QSplitter,
    QStackedLayout,
    QStackedWidget,
    QToolButton,
    QWidget,
)

from ..style import icons
from ..style.page_switcher import PageSwitcher


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
        # Sizes read from the preferences, applied after the first show (a page that sets its
        # own first-show sizes in ``on_show`` would otherwise overwrite them).
        self._pending: list[QByteArray | None] | None = None

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

    def export_sizes(self) -> list[QByteArray | None]:
        """The splitters' sizes in a stable order, for the preferences (None: never shown, none known).

        The page being shown must ``save_sizes()`` first (``PageHost.page_states`` does)."""
        if self._pending is not None:  # read at start-up, not yet shown: keep them for next time
            return list(self._pending)
        return [self._states.get(id(splitter)) for splitter in self.splitters()]

    def import_sizes(self, states: list[QByteArray | None]) -> None:
        """Sizes from the preferences, applied by ``apply_pending`` once the page has been shown."""
        self._pending = list(states) if states else None

    def apply_pending(self) -> None:
        """Put back the sizes imported from the preferences (a state that no longer fits is skipped)."""
        pending, self._pending = self._pending, None
        if pending is None:
            return
        for splitter, state in zip(self.splitters(), pending, strict=False):
            if state is not None:
                splitter.restoreState(state)  # a state that no longer fits is refused: no change

    def on_show(self) -> None:
        """The page became current (after ``place``)."""

    def on_hide(self) -> None:
        """Another page is about to be shown."""


class PageHost(QWidget):
    """The window's central widget: the pages, stacked; or the welcome while no project is open.

    The page switcher and the panel switches live in the window's top bar (``attach_topbar``)."""

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
        self.bar = PageSwitcher()  # shown in the top bar; the pages' model (index, data, signals)
        self.bar.currentChanged.connect(self._on_tab)
        self.root = QStackedLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.addWidget(self.stack)
        self.welcome: QWidget | None = None
        self.topbar = None
        self.panel_buttons: list[tuple[QWidget, QToolButton]] = []
        self._window_buttons: list[QToolButton] = []
        for view in shared.all():
            view.setParent(self.parking)

    def attach_topbar(self, topbar) -> None:
        """Put the page switcher and the panel and window buttons in ``topbar``."""
        self.topbar = topbar
        topbar.set_switcher(self.bar)
        for _view, button in self.panel_buttons:
            topbar.add_panel_button(button)
        for button in self._window_buttons:
            topbar.add_window_button(button)

    def set_welcome(self, widget: QWidget) -> None:
        """The widget shown instead of the pages until a project is open."""
        self.welcome = widget
        self.root.addWidget(widget)

    def show_welcome(self, shown: bool) -> None:
        if self.welcome is not None:
            self.root.setCurrentWidget(self.welcome if shown else self.stack)
        if self.topbar is not None:
            self.topbar.set_project_mode(not shown)
            if not shown:
                self._sync_panel_buttons()

    def add_panel_button(self, view: QWidget, button: QToolButton) -> None:
        """A button that shows or hides ``view`` (a shared panel); it is shown while the current page
        has that panel."""
        self.panel_buttons.append((view, button))
        if self.topbar is not None:
            self.topbar.add_panel_button(button)
        button.setVisible(self.current is not None and view.parentWidget() is not self.parking)

    def add_window_button(self, button: QToolButton) -> None:
        """A button for the window itself (full screen), in the top bar."""
        self._window_buttons.append(button)
        if self.topbar is not None:
            self.topbar.add_window_button(button)

    def _sync_panel_buttons(self) -> None:
        for view, button in self.panel_buttons:
            button.setVisible(view.parentWidget() is not self.parking)
        if self.topbar is not None:
            self.topbar.refresh()  # the bar's right side changed size

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
        self._sync_panel_buttons()
        page.restore_sizes()
        self.stack.setCurrentWidget(page.widget)
        self.current = name
        index = next(i for i in range(self.bar.count()) if self.bar.tabData(i) == name)
        if self.bar.currentIndex() != index:
            self.bar.blockSignals(True)
            self.bar.setCurrentIndex(index)
            self.bar.blockSignals(False)
        page.on_show()
        page.apply_pending()  # after on_show: its first-show sizes must not win over the remembered ones
        self.pageChanged.emit(name)

    def page_states(self) -> dict[str, list[QByteArray | None]]:
        """Every page's splitter sizes now, for the preferences."""
        current = self.pages.get(self.current) if self.current else None
        if current is not None:
            current.save_sizes()
        return {name: page.export_sizes() for name, page in self.pages.items()}

    def restore_states(self, states: dict[str, list[QByteArray | None]]) -> None:
        """Sizes from the preferences: a page gets its own when first shown (the current one now)."""
        for name, sizes in states.items():
            if name in self.pages:
                self.pages[name].import_sizes(sizes)
        current = self.pages.get(self.current) if self.current else None
        if current is not None:
            current.apply_pending()

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
