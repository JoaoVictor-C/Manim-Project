"""Layers > Add > Equation steps... (P11, ADR 0054): type the steps of a derivation, get one
MathTex per step and the morphs between them.

The dialog only asks; ``LayersPanel.add_equation_steps`` applies ``edits.add_equation_steps``
as one undo step. Each line is checked as it is typed: at once for what can be read without
LaTeX (unbalanced braces), and through the build worker for LaTeX itself (``BuildService.check``,
which also warms the formulas for the edit that follows). Nothing here builds LaTeX in the UI
thread. Between two lines the preview shows the morph the steps will get.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.editing import equation_steps
from ...core.editing.edits import ENTRANCES
from ...core.editing.equation_steps import MATCHING, OPERATIONS, StepsError
from ...core.engine import adapter
from ...core.model.schema import Spec
from ..session.preferences import Preferences
from ..style import theme
from ..style.fields import SwatchButton, caption, pick_colour, set_error

STEP_ROLE = Qt.ItemDataRole.UserRole  # a preview row's step index (None on a morph row)
CHECK_DELAY_MS = 600  # typing pauses this long before lines go to the build worker
EXAMPLE = "A = L \\times L\nL = a+b\nA = (a+b) \\times (a+b)"


@dataclass(frozen=True)
class StepsRequest:
    """What the dialog asks ``edits.add_equation_steps`` for."""

    steps: tuple[str, ...]
    start: float
    step_duration: float
    hold: float
    font_size: float
    colour: str
    highlight_colour: str | None
    entrance: str
    free_spot: bool  # below the other objects (as a new object goes), else the centre


class EquationStepsDialog(QDialog):
    def __init__(
        self,
        start: float = 0.0,
        builds=None,  # BuildService: checks lines through the build worker when it runs
        prefs: Preferences | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Equation steps")
        self.builds = builds
        self.prefs = prefs or Preferences()
        self.latex_missing = adapter.latex_problem()
        # Hooks for tests and other front-ends.
        # check_line(tex, ask): (built, error) when known, else None; ask sends it to the worker.
        self.check_line: Callable[[str, bool], tuple[bool, str] | None] = self._check_with_worker
        self.ask_colour: Callable[[str | None], str | None] = lambda current: pick_colour(self, current)
        self.can_check = bool(builds is not None and builds.client.available)
        self.steps: list[str] = []
        self.problems: dict[int, str] = {}  # step index -> why it cannot be added

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("One equation per line, in LaTeX, e.g.\n" + EXAMPLE)
        self.text.setToolTip(
            "Each line is one step (a MathTex). Lines starting with % are comments. At most "
            f"{equation_steps.MAX_STEPS} steps of {equation_steps.MAX_LINE} characters."
        )
        self.operation = QComboBox()
        for op in OPERATIONS.values():
            self.operation.addItem(op.label, op.name)
        self.operation.setToolTip("How the next line is made from the last line (or the selected step)")
        self.term = QLineEdit()
        self.term.setToolTip("The term the operation uses: what to add, the factor, or symbol = value")
        self.add_line = QPushButton("Add line")
        self.add_line.setToolTip("Append the derived line to the steps")
        self.add_line.clicked.connect(self.derive_line)
        self.operation.currentIndexChanged.connect(self._on_operation)
        self.term.returnPressed.connect(self.derive_line)

        self.preview = QListWidget()
        self.preview.setToolTip(
            "The steps as they will be added, each with its check, and the morph between two steps: "
            "a matching morph keeps the shared terms and moves them; a replacement morph turns one "
            "equation into the other. Select a step to derive the next line from it."
        )
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setToolTip("What will be added, and whether every line builds")

        self.start = self._seconds(start, "When the first step starts to appear (the playhead by default)")
        self.step_duration = self._seconds(
            self.prefs.option("steps/step_duration", 1.0), "How long the entrance and each morph last"
        )
        self.step_duration.setMinimum(0.1)
        self.hold = self._seconds(self.prefs.option("steps/hold", 1.0), "How long each step stays still")
        self.font_size = QDoubleSpinBox(minimum=4, maximum=400, decimals=0)
        self.font_size.setValue(self.prefs.option("steps/font_size", 48.0))
        self.font_size.setToolTip("The size of the equations (Manim's font_size; 48 is its default)")
        self.entrance = QComboBox()
        self.entrance.addItems(list(ENTRANCES))
        self.entrance.setCurrentText(self.prefs.option("steps/entrance", "Write"))
        self.entrance.setToolTip("How the first step appears")
        self.colour = self._colour_button(self.prefs.option("steps/colour", equation_steps.BASE_COLOUR))
        self.colour.setToolTip("The colour of the equations")
        self.highlight = QCheckBox("Colour new terms")
        self.highlight.setChecked(self.prefs.option("steps/highlight", True))
        self.highlight.setToolTip(
            "Terms that are new in a step get the highlight colour (as coloured parts); "
            "in the next step they are plain again"
        )
        self.highlight_colour = self._colour_button(
            self.prefs.option("steps/highlight_colour", equation_steps.HIGHLIGHT_COLOUR)
        )
        self.highlight_colour.setToolTip("The colour of the new terms")
        self.highlight.toggled.connect(self.highlight_colour.setEnabled)
        self.highlight_colour.setEnabled(self.highlight.isChecked())
        self.place = QComboBox()
        self.place.addItems(["Free spot", "Centre"])
        self.place.setCurrentText(self.prefs.option("steps/place", "Free spot"))
        self.place.setToolTip("Where the steps go: below the objects already there, or the centre")

        derive_row = QHBoxLayout()
        derive_row.addWidget(self.operation)
        derive_row.addWidget(self.term, 1)
        derive_row.addWidget(self.add_line)
        derive_box = QGroupBox("Derive the next line")
        derive_box.setToolTip("Make the next step by doing the same thing to both sides of the equation")
        derive_box.setLayout(derive_row)
        highlight_row = QHBoxLayout()
        highlight_row.addWidget(self.highlight)
        highlight_row.addWidget(self.highlight_colour, 1)
        form = QFormLayout()
        form.addRow("Start (s):", self.start)
        form.addRow("Step duration (s):", self.step_duration)
        form.addRow("Hold (s):", self.hold)
        form.addRow("Font size:", self.font_size)
        form.addRow("Enters with:", self.entrance)
        form.addRow("Colour:", self.colour)
        form.addRow(highlight_row)
        form.addRow("Place:", self.place)
        options = QGroupBox("Options")
        options.setLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add steps")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setProperty("role", "ghost")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip(
            "Add one MathTex per step and the morphs between them (one undo step)"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip("Close without adding")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.text.setFont(theme.font("body", kind="mono"))
        self.status.setProperty("normalRole", "muted")
        self.status.setProperty("role", "muted")
        left = QVBoxLayout()
        left.setSpacing(5)
        left.addWidget(caption("Steps (one LaTeX equation per line):"))
        left.addWidget(self.text, 2)
        left.addSpacing(theme.SPACE)
        left.addWidget(derive_box)
        left.addSpacing(theme.SPACE)
        left.addWidget(caption("Preview:"))
        left.addWidget(self.preview, 2)
        columns = QHBoxLayout()
        columns.setSpacing(4 * theme.SPACE)
        columns.addLayout(left, 3)
        columns.addWidget(options, 2, Qt.AlignmentFlag.AlignTop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(3 * theme.SPACE)
        layout.addLayout(columns, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)

        self._check_timer = QTimer(self, singleShot=True, interval=CHECK_DELAY_MS)
        self._check_timer.timeout.connect(lambda: self.refresh(check=True))
        self.text.textChanged.connect(self._on_text_changed)
        if builds is not None:
            builds.checked.connect(lambda *_: self.refresh())
        self._on_operation()
        self.refresh()
        self.resize(820, 560)

    # -- building ---------------------------------------------------------------------------------

    def _seconds(self, value: float, tip: str) -> QDoubleSpinBox:
        box = QDoubleSpinBox(minimum=0.0, maximum=3600.0, decimals=2, singleStep=0.25)
        box.setValue(float(value))
        box.setSuffix(" s")
        box.setToolTip(tip)
        return box

    def _colour_button(self, value: str) -> QPushButton:
        button = SwatchButton()  # Lumen: a swatch and the hex, like a colour field
        button.clicked.connect(lambda: self._pick(button))
        self._show_colour(button, value)
        return button

    def _pick(self, button: QPushButton) -> None:
        colour = self.ask_colour(button.property("colour"))
        if colour is not None:
            self._show_colour(button, colour)

    def _show_colour(self, button: SwatchButton, value: str) -> None:
        button.setProperty("colour", value)
        button.setText(value)
        button.set_colour(value)

    # -- deriving ---------------------------------------------------------------------------------

    def _on_operation(self) -> None:
        op = OPERATIONS[self.operation.currentData()]
        self.term.setEnabled(bool(op.term))
        self.term.setPlaceholderText(op.term or "(no term needed)")

    def derive_line(self) -> bool:
        """Append the line the operation makes from the selected step (else the last line)."""
        if not self.steps:
            self._say("Type an equation first: the next line is derived from it.", error=True)
            return False
        item = self.preview.currentItem()
        index = item.data(STEP_ROLE) if item is not None else None
        source = self.steps[index if isinstance(index, int) else -1]
        try:
            line = equation_steps.derive(source, self.operation.currentData(), self.term.text())
        except StepsError as error:
            self._say(f"Cannot derive the next line: {error}", error=True)
            return False
        text = self.text.toPlainText().rstrip("\n")
        self.text.setPlainText(f"{text}\n{line}" if text else line)
        self.preview.setCurrentRow(self.preview.count() - 1)
        return True

    # -- checking ---------------------------------------------------------------------------------

    def _on_text_changed(self) -> None:
        self.refresh()
        self._check_timer.start()

    def _check_with_worker(self, tex: str, ask: bool) -> tuple[bool, str] | None:
        if self.builds is None:
            return None
        return self.builds.check(Spec(type="MathTex", params={"text": tex}), ask=ask)

    def refresh(self, check: bool = False) -> None:
        """Read the lines again: their checks, the planned morphs, the summary and the OK button.
        ``check`` also asks about lines whose LaTeX is not known yet (else only known answers)."""
        selected = self.preview.currentRow()
        self.preview.clear()
        self.problems = {}
        try:
            self.steps = equation_steps.parse_steps(self.text.toPlainText())
        except StepsError as error:
            self.steps = []
            self._say(str(error), error=True)
            self._set_ok(False)
            return
        waiting = 0
        for index, tex in enumerate(self.steps):
            if index > 0:
                plan = equation_steps.plan_transition(self.steps[index - 1], tex)
                note = f"    then a {plan.label}"
                if plan.kind == MATCHING and plan.new:
                    note += f" ({len(plan.new)} new term{'s' * (len(plan.new) != 1)})"
                row = QListWidgetItem(note)
                row.setData(STEP_ROLE, None)
                row.setFlags(Qt.ItemFlag.NoItemFlags)
                self.preview.addItem(row)
            state = self._line_state(tex, check)
            if state == "waiting":
                waiting += 1
            elif state:
                self.problems[index] = state
            row = QListWidgetItem(
                f"{index + 1}.  {tex}" + (f"    - {state}" if state and state != "waiting" else "")
            )
            row.setData(STEP_ROLE, index)
            if index in self.problems:
                row.setForeground(theme.qcolor(theme.THEME.error_text))
                row.setToolTip(self.problems[index])
            self.preview.addItem(row)
        if 0 <= selected < self.preview.count():
            self.preview.setCurrentRow(selected)
        self._summarise(waiting)

    def _line_state(self, tex: str, check: bool) -> str:
        """ "" when the line is fine (or cannot be checked here), "waiting" while the worker
        builds it, else why it cannot be added."""
        problem = equation_steps.line_problem(tex)
        if problem is not None:
            return problem
        if self.latex_missing:
            return ""
        known = self.check_line(tex, check)
        if known is None:
            return "waiting" if self.can_check else ""
        ok, error = known
        return "" if ok else (error or "LaTeX cannot build it")

    def _summarise(self, waiting: int) -> None:
        n = len(self.steps)
        if n == 0:
            self._say("Type the steps, one equation per line, or derive them from the first.")
            self._set_ok(False)
            return
        if self.problems:
            first = min(self.problems)
            self._say(f"Step {first + 1} cannot be added: {self.problems[first]}", error=True)
            self._set_ok(False)
            return
        morphs = n - 1
        text = f"{n} step{'s' * (n != 1)}, {morphs} morph{'s' * (morphs != 1)}."
        if self.latex_missing:
            text += f" {self.latex_missing}: the steps are added and drawn as placeholders until it is."
        elif waiting:
            text += f" Checking {waiting} line{'s' * (waiting != 1)} with LaTeX..."
        elif not self.can_check:
            text += " LaTeX builds the lines when the steps are added."
        self._say(text)
        self._set_ok(True)

    def _say(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        set_error(self.status, error)

    def _set_ok(self, enabled: bool) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(enabled)

    # -- the answer -------------------------------------------------------------------------------

    def request(self) -> StepsRequest:
        return StepsRequest(
            steps=tuple(self.steps),
            start=self.start.value(),
            step_duration=self.step_duration.value(),
            hold=self.hold.value(),
            font_size=self.font_size.value(),
            colour=self.colour.property("colour"),
            highlight_colour=self.highlight_colour.property("colour") if self.highlight.isChecked() else None,
            entrance=self.entrance.currentText(),
            free_spot=self.place.currentText() == "Free spot",
        )

    def remember(self) -> None:
        """Keep the options for next time (not the start: it follows the playhead)."""
        for name, value in (
            ("step_duration", self.step_duration.value()),
            ("hold", self.hold.value()),
            ("font_size", self.font_size.value()),
            ("entrance", self.entrance.currentText()),
            ("colour", self.colour.property("colour")),
            ("highlight", self.highlight.isChecked()),
            ("highlight_colour", self.highlight_colour.property("colour")),
            ("place", self.place.currentText()),
        ):
            self.prefs.set_option(f"steps/{name}", value)

    def accept(self) -> None:
        self.refresh()
        if not self.steps or self.problems:
            return
        self.remember()
        super().accept()
