"""The import window (P12.4): choose what each code file becomes before anything is added.

Opens for files chosen with Add code file, a folder of presets, files dragged from the desktop and
presets downloaded from the internet. Every item shows what it was detected as (a Python object, a
Manim scene, or a helper when it has neither a build(p) nor a Scene - a module the project's code
imports, ADR 0058) and is preselected as that; the user can change it to anything that is possible, set the
name, which scenes of a file to take, when and where it appears, whether it may run at once, and
whether to keep a copy in the preset library. Nothing here runs the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.assist import live_guard
from ...core.exchange import code_import
from ...core.exchange.code_import import AS_LABELS, HELPER, OBJECT, PRESET, SCENE, ImportChoice, ImportItem
from ..code.code_editor import CodeEditor
from ..style import theme


@dataclass
class _State:
    item: ImportItem
    name: str
    as_: str
    scenes: list[str] = field(default_factory=list)
    include: bool = True
    auto_time: bool = True
    time: float = 0.0
    auto_position: bool = True
    x: float = 0.0
    y: float = 0.0
    trust: bool = False
    also_preset: bool = False
    title: str = ""  # the name suggested for a layer or preset ("Grid Tools")
    module: str = ""  # the name suggested for a helper, a Python name ("grid_tools")


class ImportCodeDialog(QDialog):
    def __init__(
        self,
        items: list[ImportItem],
        *,
        playhead: float = 0.0,
        at: float | None = None,
        position: tuple[float, float] | None = None,
        has_project: bool = True,
        prefer_preset: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import code")
        self.resize(900, 600)
        self.has_project = has_project
        self.states: list[_State] = []
        for item in items:
            inspection = item.inspection
            found = code_import.detected(inspection)
            as_ = found or PRESET
            if (not has_project or prefer_preset) and found:
                as_ = PRESET
            module = code_import.helper_name(item.filename or item.origin or inspection.suggested_name)
            state = _State(
                item,
                module if as_ == HELPER else inspection.suggested_name,
                as_,
                list(inspection.scenes[:1]),
                include=found is not None,
                auto_time=at is None,
                time=playhead if at is None else at,
                auto_position=position is None,
                x=0.0 if position is None else position[0],
                y=0.0 if position is None else position[1],
                title=inspection.suggested_name,
                module=module,
            )
            self.states.append(state)
        self._row = -1
        self._loading = False

        layout = QVBoxLayout(self)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setObjectName("importItems")
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemChanged.connect(self._on_checked)
        self.split.addWidget(self.list)
        self.split.addWidget(self._build_form())
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([240, 660])
        layout.addWidget(self.split, 1)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setObjectName("importMessage")
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._fill_list()
        if self.states:
            self.list.setCurrentRow(0)
        self._refresh()

    # -- building -------------------------------------------------------------------------------

    def _build_form(self) -> QWidget:
        panel = QWidget()
        column = QVBoxLayout(panel)
        self.origin_label = QLabel("")
        self.origin_label.setWordWrap(True)
        self.origin_label.setProperty("role", "section")
        self.detected_label = QLabel("")
        self.detected_label.setWordWrap(True)
        column.addWidget(self.origin_label)
        column.addWidget(self.detected_label)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._on_edit)
        form.addRow("Name", self.name_edit)
        column.addLayout(form)

        kind_box = QGroupBox("Add it as")
        kind_row = QVBoxLayout(kind_box)
        self.radios: dict[str, QRadioButton] = {}
        for key in (OBJECT, SCENE, HELPER, PRESET):
            radio = QRadioButton(AS_LABELS[key])
            radio.toggled.connect(lambda on, k=key: on and self._on_kind(k))
            self.radios[key] = radio
            kind_row.addWidget(radio)
        self.scene_list = QListWidget()
        self.scene_list.setObjectName("importScenes")
        self.scene_list.setMaximumHeight(90)
        self.scene_list.itemChanged.connect(self._on_edit)
        kind_row.addWidget(self.scene_list)
        self.also_preset = QCheckBox("Also keep a copy in my presets")
        self.also_preset.toggled.connect(self._on_edit)
        kind_row.addWidget(self.also_preset)
        column.addWidget(kind_box)

        self.place_box = QGroupBox("In the project")
        place = QFormLayout(self.place_box)
        self.auto_time = QCheckBox("At the playhead")
        self.auto_time.toggled.connect(self._on_edit)
        self.time = QDoubleSpinBox()
        self.time.setRange(0.0, 100000.0)
        self.time.setDecimals(3)
        self.time.setSingleStep(0.1)
        self.time.setSuffix(" s")
        self.time.valueChanged.connect(self._on_edit)
        row = QHBoxLayout()
        row.addWidget(self.auto_time)
        row.addWidget(self.time)
        place.addRow("Appears", row)
        self.auto_position = QCheckBox("Where it fits")
        self.auto_position.toggled.connect(self._on_edit)
        self.x = QDoubleSpinBox()
        self.y = QDoubleSpinBox()
        for spin, prefix in ((self.x, "x "), (self.y, "y ")):
            spin.setRange(-1000.0, 1000.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.25)
            spin.setPrefix(prefix)
            spin.valueChanged.connect(self._on_edit)
        row = QHBoxLayout()
        row.addWidget(self.auto_position)
        row.addWidget(self.x)
        row.addWidget(self.y)
        place.addRow("Position", row)
        self.trust = QCheckBox("Allow it to run now")
        self.trust.setToolTip(
            "Code from files and from the internet is not run until you allow it: it shows a placeholder "
            "and asks. Tick this only for code you wrote or have read."
        )
        self.trust.toggled.connect(self._on_edit)
        column.addWidget(self.place_box)
        column.addWidget(self.trust)
        self.uses_label = QLabel("")  # what the code reaches, so the user can decide before allowing it
        self.uses_label.setWordWrap(True)
        self.uses_label.setProperty("role", "hint")
        column.addWidget(self.uses_label)

        self.params_label = QLabel("")
        self.params_label.setWordWrap(True)
        self.params_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.params_label)
        self.preview = CodeEditor()
        self.preview.setReadOnly(True)
        self.preview.setObjectName("importPreview")
        column.addWidget(self.preview, 1)
        return panel

    def _fill_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for state in self.states:
            entry = QListWidgetItem(state.name)
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(Qt.CheckState.Checked if state.include else Qt.CheckState.Unchecked)
            self.list.addItem(entry)
        self.list.blockSignals(False)
        self._relabel()

    def _relabel(self) -> None:
        self.list.blockSignals(True)
        for row, state in enumerate(self.states):
            entry = self.list.item(row)
            entry.setText(f"{state.name}  —  {AS_LABELS[state.as_]}")
            entry.setToolTip(state.item.origin)
        self.list.blockSignals(False)

    # -- state <-> form -------------------------------------------------------------------------

    def _on_row(self, row: int) -> None:
        self._store()
        self._row = row
        self._load()

    def _on_checked(self, entry: QListWidgetItem) -> None:
        row = self.list.row(entry)
        self.states[row].include = entry.checkState() == Qt.CheckState.Checked
        self._refresh()

    def _on_kind(self, key: str) -> None:
        if self._loading or self._row < 0:
            return
        self._store()
        state = self.states[self._row]
        # A helper is named like a Python module ("grid_tools"), a layer or preset like a title: the
        # suggested name follows the kind until the user types their own.
        if key == HELPER and state.name == state.title:
            state.name = state.module
        elif key != HELPER and state.as_ == HELPER and state.name == state.module:
            state.name = state.title
        state.as_ = key
        self._load()

    def _on_edit(self, *_args) -> None:
        if self._loading or self._row < 0:
            return
        self._store()
        self._relabel()
        self._sync_enabled()
        self._refresh()

    def _store(self) -> None:
        if self._row < 0 or self._row >= len(self.states) or self._loading:
            return
        state = self.states[self._row]
        state.name = self.name_edit.text()
        state.scenes = [
            self.scene_list.item(i).text()
            for i in range(self.scene_list.count())
            if self.scene_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        state.auto_time = self.auto_time.isChecked()
        state.time = self.time.value()
        state.auto_position = self.auto_position.isChecked()
        state.x, state.y = self.x.value(), self.y.value()
        state.trust = self.trust.isChecked()
        state.also_preset = self.also_preset.isChecked()

    def _load(self) -> None:
        if self._row < 0 or self._row >= len(self.states):
            return
        state = self.states[self._row]
        inspection = state.item.inspection
        options = code_import.possible(inspection)
        self._loading = True
        try:
            self.origin_label.setText(state.item.origin)
            found = code_import.detected(inspection)
            if found is not None:
                self.detected_label.setText(f"Detected: {AS_LABELS[found]}")
            else:
                self.detected_label.setText(
                    f"Not importable: {inspection.problem or 'no build(p) function and no Manim scene'}"
                )
            self.name_edit.setText(state.name)
            for key, radio in self.radios.items():
                reason = options[key]
                allowed = reason is None and not (key != PRESET and not self.has_project)
                radio.setEnabled(allowed)
                radio.setChecked(key == state.as_)
                suffix = " (detected)" if key == found else ""
                radio.setText(AS_LABELS[key] + suffix)
                if reason is not None:
                    radio.setToolTip(f"Not possible: {reason}")
                elif not self.has_project and key != PRESET:
                    radio.setToolTip("Open or create a project first")
                else:
                    radio.setToolTip("")
            self.scene_list.clear()
            for scene in inspection.scenes:
                entry = QListWidgetItem(scene)
                entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                entry.setCheckState(
                    Qt.CheckState.Checked if scene in state.scenes else Qt.CheckState.Unchecked
                )
                self.scene_list.addItem(entry)
            self.auto_time.setChecked(state.auto_time)
            self.time.setValue(state.time)
            self.auto_position.setChecked(state.auto_position)
            self.x.setValue(state.x)
            self.y.setValue(state.y)
            self.trust.setChecked(state.trust)
            self.also_preset.setChecked(state.also_preset)
            if inspection.params:
                shown = ", ".join(f"{p.name} = {p.default!r}" for p in inspection.params[:8])
                more = f" (+{len(inspection.params) - 8} more)" if len(inspection.params) > 8 else ""
                self.params_label.setText(f"Parameters: {shown}{more}")
            else:
                self.params_label.setText(inspection.summary)
            self.preview.set_text(state.item.source.lstrip("\ufeff"), 0)
            uses = live_guard.risky_uses(state.item.source)
            self.uses_label.setText(
                f"This code uses {', '.join(uses)}: it can reach files, programs or the network. "
                "Read it first."
                if uses
                else "This code does not use files, programs or the network (by what the text shows)."
            )
        finally:
            self._loading = False
        self._relabel()
        self._sync_enabled()
        self._refresh()

    def _sync_enabled(self) -> None:
        if self._row < 0:
            return
        state = self.states[self._row]
        inspection = state.item.inspection
        multi = len(inspection.scenes) > 1 and state.as_ in (SCENE, PRESET)
        self.scene_list.setVisible(multi)
        self.also_preset.setVisible(state.as_ != PRESET)
        self.place_box.setVisible(state.as_ not in (PRESET, HELPER))  # a helper has no time or place
        self.trust.setVisible(state.as_ != PRESET)
        self.time.setEnabled(not self.auto_time.isChecked())
        self.x.setEnabled(not self.auto_position.isChecked())
        self.y.setEnabled(not self.auto_position.isChecked())

    # -- the answer -----------------------------------------------------------------------------

    def choices(self) -> list[ImportChoice]:
        """What the user chose, for the checked items."""
        self._store()
        out = []
        for state in self.states:
            if not state.include:
                continue
            out.append(
                ImportChoice(
                    state.item,
                    state.name.strip(),
                    state.as_,
                    tuple(state.scenes),
                    None if state.auto_time or state.as_ == PRESET else state.time,
                    None if state.auto_position or state.as_ == PRESET else (state.x, state.y),
                    state.trust,
                    state.also_preset,
                )
            )
        return out

    def _refresh(self) -> None:
        """Say what is wrong, and only allow Import when every checked item is fine."""
        problems = []
        chosen = self.choices() if self.states else []
        for choice in chosen:
            why = code_import.validate(choice)
            if why is not None:
                problems.append(f"{choice.name or choice.item.origin}: {why}")
        if not chosen:
            problems.append("Nothing is checked")
        colour = theme.css(theme.THEME.warning)
        self.message.setStyleSheet(f"color: {colour};")
        self.message.setText("\n".join(problems[:3]))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not problems)
