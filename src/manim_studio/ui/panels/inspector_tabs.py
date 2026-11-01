"""The inspector's tab strip (Lumen, ADR 0063, 0084): **Properties | Clip | Scene** in the card header.

The tabs say what the panel shows and let you go there: *Properties* the selected object, *Clip* one of its
clips (the one under the playhead, else the first), *Scene* the project's own settings. They follow the
selection (a clip picked on the timeline lights *Clip*); a tab with nothing to show is off, with the reason
as its tooltip. A sound, a subtitle or a marker shown in the panel lights none of them.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton, QWidget

from ..style import theme

PROPERTIES, CLIP, SCENE = "properties", "clip", "scene"
TABS = (
    (PROPERTIES, "Properties", "The selected object: its transform, appearance and lifetime"),
    (CLIP, "Clip", "The animation clip of the selected object at the playhead (or its first)"),
    (SCENE, "Scene", "The project's own settings: length, size, frame rate, background, camera"),
)
OFF_TIPS = {
    PROPERTIES: "Select an object to see its properties",
    CLIP: "Select an object that has an animation clip",
}


def _rules(c: theme.Colours) -> str:
    return f"""
QToolButton[inspectorTab="true"] {{
    background: transparent; border: 0; border-bottom: 2px solid transparent; border-radius: 0;
    padding: 0 11px; color: {c.muted}; font-weight: 550;
}}
QToolButton[inspectorTab="true"]:hover {{ color: {c.text}; background: transparent; }}
QToolButton[inspectorTab="true"]:checked {{
    color: {c.text}; background: transparent; border-bottom: 2px solid {c.accent};
}}
QToolButton[inspectorTab="true"]:disabled {{ color: {c.disabled}; }}
"""


theme.register_rules(_rules)


class InspectorTabs(QWidget):
    tabChosen = Signal(str)  # a click on an enabled tab: "properties", "clip" or "scene"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inspectorTabs")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        for key, text, tip in TABS:
            button = QToolButton(self)
            button.setProperty("inspectorTab", True)
            button.setCheckable(True)
            button.setText(text)
            button.setToolTip(tip)
            button.setAccessibleName(text)
            button.setAutoRaise(True)
            button.setFixedHeight(36)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(button)
            self.buttons[key] = button
            row.addWidget(button)
            button.clicked.connect(lambda _checked=False, k=key: self.tabChosen.emit(k))
        row.addStretch(1)

    def current(self) -> str | None:
        return next((k for k, b in self.buttons.items() if b.isChecked()), None)

    def show_state(self, current: str | None, *, properties: bool, clip: bool) -> None:
        """Light ``current`` (None: no tab) and switch off the tabs that have nothing to show."""
        for key, enabled in ((PROPERTIES, properties), (CLIP, clip), (SCENE, True)):
            button = self.buttons[key]
            button.setEnabled(enabled)
            tip = next(t for k, _text, t in TABS if k == key)
            button.setToolTip(tip if enabled else OFF_TIPS[key])
        self._group.setExclusive(False)
        for key, button in self.buttons.items():
            button.setChecked(key == current)
        self._group.setExclusive(True)
