"""Layers > Add > Equation steps... (P11, ADR 0054): compose a derivation, get one
MathTex per step and the morphs between them.

The dialog has an editable LaTeX line, a symbol keyboard, a live MathTex preview, and an advanced
multi-line source editor. Steps can be edited, duplicated, deleted and reordered before they are
added. ``LayersPanel.add_equation_steps`` applies ``edits.add_equation_steps`` as one undo step.
Lines are checked for balanced structure immediately and built through the worker; the preview
reads the worker's warmed glyph paths so LaTeX never compiles in the UI thread.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.editing import equation_steps
from ...core.editing.edits import ENTRANCES
from ...core.editing.equation_steps import FUNCTIONS, MATCHING, OPERATIONS, StepsError
from ...core.engine import adapter
from ...core.model.schema import Spec
from ..session.preferences import Preferences
from ..style import theme
from ..style.fields import SwatchButton, caption, pick_colour, set_error

STEP_ROLE = Qt.ItemDataRole.UserRole  # a preview row's step index (None on a morph row)
CHECK_DELAY_MS = 600  # typing pauses this long before lines go to the build worker
PREVIEW_DELAY_MS = 700  # debounce symbol clicks so partial formulas do not flood the LaTeX worker
EXAMPLE = "A = L \\times L\nL = a+b\nA = (a+b) \\times (a+b)"

_BS = chr(92)
PALETTE = {
    "Basic": (
        *((str(number), str(number)) for number in range(10)),
        ("+", "+"), ("−", "-"), ("×", _BS + "times "), ("÷", _BS + "div "), ("=", "="),
        ("≠", _BS + "neq "), ("<", "<"), (">", ">"), ("≤", _BS + "leq "), ("≥", _BS + "geq "),
        ("( )", _BS + "left(" + _BS + "right)", len(_BS + "left(")),
        ("π", _BS + "pi "), ("∞", _BS + "infty "), ("±", _BS + "pm "),
        ("·", _BS + "cdot "), (",", ","), (".", "."),
    ),
    "Letters": tuple((letter, letter) for letter in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    "Structure": (
        ("a⁄b", _BS + "frac{}{}", len(_BS + "frac{")),
        ("xⁿ", "^{}", 2), ("xₙ", "_{}", 2),
        ("√", _BS + "sqrt{}", len(_BS + "sqrt{")),
        ("ⁿ√", _BS + "sqrt[]{}", len(_BS + "sqrt[")),
        ("( )", _BS + "left(" + _BS + "right)", len(_BS + "left(")),
        ("[ ]", _BS + "left[" + _BS + "right]", len(_BS + "left[")),
        ("| |", _BS + "left|" + _BS + "right|", len(_BS + "left|")),
        ("{ }", _BS + "left" + _BS + "{" + _BS + "right" + _BS + "}", len(_BS + "left" + _BS + "{")),
        ("x̅", _BS + "overline{}", len(_BS + "overline{")),
        ("→", _BS + "rightarrow "), ("↔", _BS + "leftrightarrow "), ("…", _BS + "ldots "),
    ),
    "Functions": (
        *((name, _BS + name + _BS + "left(" + _BS + "right)", len(_BS + name + _BS + "left("))
          for name in (
              "sin", "cos", "tan", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "ln", "log"
          )),
        ("logₐ", _BS + "log_{}{}", len(_BS + "log_{")),
        (
            "log₁₀",
            _BS + "log_{10}" + _BS + "left(" + _BS + "right)",
            len(_BS + "log_{10}" + _BS + "left("),
        ),
        (
            "log₂",
            _BS + "log_{2}" + _BS + "left(" + _BS + "right)",
            len(_BS + "log_{2}" + _BS + "left("),
        ),
        ("exp", "e^{}", 3), ("lim", _BS + "lim_{x" + _BS + "to} ", len(_BS + "lim_{x" + _BS + "to")),
        ("Σ", _BS + "sum_{}^{}", len(_BS + "sum_{")),
        ("∫", _BS + "int_{}^{}", len(_BS + "int_{")),
        ("d/dx", _BS + "frac{d}{dx}", len(_BS + "frac{d}{d")),
        ("min", _BS + "min" + _BS + "left(" + _BS + "right)", len(_BS + "min" + _BS + "left(")),
        ("max", _BS + "max" + _BS + "left(" + _BS + "right)", len(_BS + "max" + _BS + "left(")),
    ),
    "Greek": tuple(
        (symbol, _BS + name + " ")
        for symbol, name in (
            ("α", "alpha"), ("β", "beta"), ("γ", "gamma"), ("δ", "delta"),
            ("ε", "epsilon"), ("θ", "theta"), ("λ", "lambda"), ("μ", "mu"),
            ("ρ", "rho"), ("σ", "sigma"), ("φ", "phi"), ("ω", "omega"),
        )
    ),
}


class _EquationPreview(QWidget):
    """A large, fitted drawing of the active equation, built from MathTex glyph outlines."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.paths: list[QPainterPath] = []
        self.colour = "#ffffff"
        self.message = "Type LaTeX or use the symbol keyboard to preview an equation."

    def show_message(self, text: str) -> None:
        self.paths = []
        self.message = text
        self.update()

    def show_outlines(self, outlines, colour: str) -> None:
        self.paths = []
        self.colour = colour
        for outline in outlines:
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for points in outline.subpaths:
                if len(points) < 4:
                    continue
                path.moveTo(QPointF(float(points[0, 0]), float(points[0, 1])))
                for index in range(0, len(points) - 3, 4):
                    path.cubicTo(
                        QPointF(float(points[index + 1, 0]), float(points[index + 1, 1])),
                        QPointF(float(points[index + 2, 0]), float(points[index + 2, 1])),
                        QPointF(float(points[index + 3, 0]), float(points[index + 3, 1])),
                    )
                path.closeSubpath()
            if not path.isEmpty():
                self.paths.append(path)
        self.message = "No visible glyphs in this line." if not self.paths else ""
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.THEME.panel))
        painter.setPen(QPen(theme.qcolor(theme.THEME.line), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if not self.paths:
            painter.setPen(theme.qcolor(theme.THEME.muted))
            painter.drawText(
                self.rect().adjusted(14, 10, -14, -10), Qt.AlignmentFlag.AlignCenter, self.message
            )
            return
        bounds = QRectF()
        for path in self.paths:
            bounds = bounds.united(path.boundingRect())
        room = QRectF(self.rect()).adjusted(24, 18, -24, -18)
        scale = min(room.width() / max(bounds.width(), 1e-6), room.height() / max(bounds.height(), 1e-6))
        transform = QTransform()
        transform.translate(room.center().x(), room.center().y())
        transform.scale(scale, -scale)
        transform.translate(-bounds.center().x(), -bounds.center().y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.colour))
        for path in self.paths:
            painter.drawPath(transform.map(path))


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
        matching: str = "smart",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Equation steps")
        self.builds = builds
        self.prefs = prefs or Preferences()
        self.matching = matching
        self.latex_missing = adapter.latex_problem()
        # Hooks for tests and other front-ends.
        # check_line(tex, ask): (built, error) when known, else None; ask sends it to the worker.
        self.check_line: Callable[[str, bool], tuple[bool, str] | None] = self._check_with_worker
        self.ask_colour: Callable[[str | None], str | None] = lambda current: pick_colour(self, current)
        self.can_check = bool(builds is not None and builds.client.available)
        self._shortcuts: list[QShortcut] = []
        self.steps: list[str] = []
        self.problems: dict[int, str] = {}  # step index -> why it cannot be added
        self._writing_source = False
        self._refreshing_steps = False
        self._loading_equation = False
        self._equation_dirty = False
        self._editing_step: int | None = None

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("One equation per line, in LaTeX, e.g.\n" + EXAMPLE)
        self.text.setToolTip(
            "Advanced editor: each line is one step (a MathTex). Lines starting with % are comments. At most "
            f"{equation_steps.MAX_STEPS} steps of {equation_steps.MAX_LINE} characters."
        )
        self.text.setFont(theme.font("body", kind="mono"))
        self.equation = QLineEdit()
        self.equation.setMaxLength(equation_steps.MAX_LINE)
        self.equation.setPlaceholderText("Type LaTeX here or insert symbols below")
        self.equation.setFont(theme.font("body", kind="mono"))
        self.equation.setToolTip(
            "Edit the current equation directly with LaTeX, or use the symbol palette. "
            "Press Ctrl+Enter to add or update the selected step."
        )
        self.backspace = QToolButton()
        self.backspace.setText("⌫")
        self.backspace.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.backspace.setToolTip("Remove the symbol before the cursor")
        self.backspace.clicked.connect(self._backspace)
        self.next_slot = QToolButton()
        self.next_slot.setText("Next")
        self.next_slot.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_slot.setToolTip(
            "Move the cursor to the next empty argument, such as a fraction denominator"
        )
        self.next_slot.clicked.connect(self._next_slot)
        self.clear_equation = QToolButton()
        self.clear_equation.setText("Clear")
        self.clear_equation.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_equation.setToolTip("Clear the current line and discard its unsaved edits")
        self.clear_equation.clicked.connect(self.clear_composed_line)
        self.live_preview = _EquationPreview()
        self.live_preview.setToolTip("A rendered preview of the current equation line")
        self.palette = self._make_palette()
        self.add_composed_step = QPushButton("Add as new step")
        self.add_composed_step.setProperty("role", "primary")
        self.add_composed_step.setToolTip("Add the composed equation as another step")
        self.add_composed_step.clicked.connect(self.add_composed_line)
        self.update_composed_step = QPushButton("Update selected step")
        self.update_composed_step.setToolTip("Replace the step selected in the list with this equation")
        self.update_composed_step.clicked.connect(self.update_composed_line)
        self.update_composed_step.setEnabled(False)
        self.revert_composed_step = QPushButton("Revert")
        self.revert_composed_step.setToolTip("Discard edits and reload the selected step")
        self.revert_composed_step.clicked.connect(self.revert_composed_line)
        self.revert_composed_step.setEnabled(False)
        self.equation.textChanged.connect(self._on_equation_changed)

        self.operation = QComboBox()
        for op in OPERATIONS.values():
            self.operation.addItem(op.label, op.name)
        self.operation.insertSeparator(self.operation.count())
        for function in FUNCTIONS.values():
            self.operation.addItem(function.label, function.name)
        self.operation.setToolTip(
            "Apply an algebra operation or function to both sides of the last line "
            "(or the selected step)"
        )
        self.term = QLineEdit()
        self.term.setToolTip("The term the operation uses: what to add, the factor, or symbol = value")
        self._term_mode: str | None = None
        self.operation_hint = QLabel()
        self.operation_hint.setWordWrap(True)
        self.operation_hint.setProperty("normalRole", "muted")
        self.operation_hint.setProperty("role", "muted")
        self.add_line = QPushButton("Add line")
        self.add_line.setToolTip("Append the derived line to the steps (Ctrl+Shift+Enter)")
        self.add_line.clicked.connect(self.derive_line)
        self.operation.currentIndexChanged.connect(self._on_operation)
        self.term.returnPressed.connect(self.derive_line)

        self.preview = QListWidget()
        self.preview.setToolTip(
            "The steps as they will be added, each with its check, and the Transform between each "
            "pair. The Transform uses the project's Smart or Classic matching setting. "
            "Select a step to preview, edit, or derive from it."
        )
        self.preview.currentRowChanged.connect(self._select_step)
        self.preview.setMinimumHeight(115)
        self.preview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.preview.customContextMenuRequested.connect(self._step_context_menu)
        self.move_step_up = self._step_button("↑", "Move the selected step earlier (Alt+Up)")
        self.move_step_up.clicked.connect(lambda: self.move_selected_step(-1))
        self.move_step_down = self._step_button("↓", "Move the selected step later (Alt+Down)")
        self.move_step_down.clicked.connect(lambda: self.move_selected_step(1))
        self.duplicate_step = self._step_button("Duplicate", "Duplicate the selected step (Ctrl+D)")
        self.duplicate_step.clicked.connect(self.duplicate_selected_step)
        self.delete_step = self._step_button("Delete", "Delete the selected step (Delete)")
        self.delete_step.clicked.connect(self.delete_selected_step)
        step_tools = QHBoxLayout()
        step_tools.addWidget(self.move_step_up)
        step_tools.addWidget(self.move_step_down)
        step_tools.addStretch(1)
        step_tools.addWidget(self.duplicate_step)
        step_tools.addWidget(self.delete_step)
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
            "LaTeX runs that are new relative to the preceding step get the highlight colour "
            "(as coloured parts)."
        )
        self.highlight_colour = self._colour_button(
            self.prefs.option("steps/highlight_colour", equation_steps.HIGHLIGHT_COLOUR)
        )
        self.highlight_colour.setToolTip("The colour of inserted or changed terms")
        self.highlight.toggled.connect(self.highlight_colour.setEnabled)
        self.highlight_colour.setEnabled(self.highlight.isChecked())
        self.place = QComboBox()
        self.place.addItems(["Free spot", "Centre"])
        self.place.setCurrentText(self.prefs.option("steps/place", "Free spot"))
        self.place.setToolTip("Where the steps go: below the objects already there, or the centre")

        self.font_size.valueChanged.connect(self._schedule_equation_preview)

        derive_row = QHBoxLayout()
        derive_row.addWidget(self.operation)
        derive_row.addWidget(self.term, 1)
        derive_row.addWidget(self.add_line)
        derive_box = QGroupBox("Derive the next line")
        derive_box.setToolTip("Make the next step by doing the same thing to both sides of the equation")
        derive_layout = QVBoxLayout(derive_box)
        derive_layout.addLayout(derive_row)
        derive_layout.addWidget(self.operation_hint)
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

        compose_row = QHBoxLayout()
        compose_row.addWidget(self.equation, 1)
        compose_row.addWidget(self.backspace)
        compose_row.addWidget(self.next_slot)
        compose_row.addWidget(self.clear_equation)
        compose_actions = QHBoxLayout()
        compose_actions.addWidget(self.add_composed_step)
        compose_actions.addWidget(self.update_composed_step)
        compose_actions.addWidget(self.revert_composed_step)
        compose_box = QGroupBox("Equation editor")
        compose_layout = QVBoxLayout(compose_box)
        compose_layout.addWidget(
            caption("Type LaTeX directly or use the symbols, structures, and functions below")
        )
        compose_layout.addLayout(compose_row)
        compose_layout.addWidget(self.live_preview, 1)
        compose_layout.addWidget(self.palette)
        compose_layout.addLayout(compose_actions)

        self.latex_source = QGroupBox("Edit LaTeX source (advanced)")
        self.latex_source.setCheckable(True)
        self.latex_source.setChecked(False)
        self.latex_source.setToolTip("Open the direct LaTeX editor for full control over every step")
        source_layout = QVBoxLayout(self.latex_source)
        source_layout.addWidget(self.text)
        self.text.setVisible(False)
        self.latex_source.toggled.connect(self._toggle_latex_source)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add steps")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setProperty("role", "ghost")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip(
            "Add one MathTex per step and Transform clips between them (one undo step)"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip("Close without adding")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.status.setProperty("normalRole", "muted")
        self.status.setProperty("role", "muted")
        left = QVBoxLayout()
        left.setSpacing(5)
        left.addWidget(compose_box, 3)
        left.addWidget(derive_box)
        left.addWidget(caption("Steps and transitions"))
        left.addWidget(self.preview, 1)
        left.addLayout(step_tools)
        left.addWidget(self.latex_source)
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
        self._preview_timer = QTimer(self, singleShot=True, interval=PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self._refresh_equation_preview)
        self.text.textChanged.connect(self._on_text_changed)
        if builds is not None:
            builds.checked.connect(self._on_build_checked)
        self._install_shortcuts()
        self._on_operation()
        self._update_compose_actions()
        self.refresh()
        self.resize(1080, 760)

    # -- building ---------------------------------------------------------------------------------

    def _make_palette(self) -> QTabWidget:
        """A compact math keyboard: buttons insert readable symbols and LaTeX structures."""
        tabs = QTabWidget()
        tabs.setMinimumHeight(132)
        tabs.setToolTip("Choose a symbol or structure to insert it at the equation cursor")
        for category, entries in PALETTE.items():
            columns = 13 if category == "Letters" else 9
            page = QWidget()
            grid = QGridLayout(page)
            grid.setContentsMargins(6, 6, 6, 6)
            grid.setHorizontalSpacing(5)
            grid.setVerticalSpacing(5)
            for index, entry in enumerate(entries):
                label, tex, *offset = entry
                cursor_offset = offset[0] if offset else len(tex)
                button = QToolButton(page)
                button.setText(label)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.setProperty("role", "outlined")
                button.setMinimumSize(42, 28)
                button.setToolTip(f"Insert {label}  ({tex})")
                button.clicked.connect(
                    lambda _checked=False, value=tex, at=cursor_offset: self._insert_tex(value, at)
                )
                grid.addWidget(button, index // columns, index % columns)
            grid.setRowStretch((len(entries) + columns - 1) // columns, 1)
            tabs.addTab(page, category)
        return tabs

    @staticmethod
    def _step_button(text: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setProperty("role", "outlined")
        return button

    def _install_shortcuts(self) -> None:
        """Give the equation and step list the keyboard flow of a small editor."""
        for key, callback in (
            ("Ctrl+Return", self.commit_composed_line),
            ("Ctrl+Shift+Return", self.derive_line),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        for key, callback in (
            ("Alt+Up", lambda: self.move_selected_step(-1)),
            ("Alt+Down", lambda: self.move_selected_step(1)),
            ("Ctrl+D", self.duplicate_selected_step),
            ("Delete", self.delete_selected_step),
        ):
            shortcut = QShortcut(QKeySequence(key), self.preview)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _step_context_menu(self, point) -> None:
        item = self.preview.itemAt(point)
        if item is None:
            return
        self.preview.setCurrentItem(item)
        index = self._selected_step_index()
        if index is None:
            return
        menu = QMenu(self.preview)
        can_reorder = not self._equation_dirty
        move_up = menu.addAction("Move step up")
        move_up.setEnabled(can_reorder and index > 0)
        move_up.triggered.connect(lambda _checked=False: self.move_selected_step(-1))
        move_down = menu.addAction("Move step down")
        move_down.setEnabled(can_reorder and index + 1 < len(self.steps))
        move_down.triggered.connect(lambda _checked=False: self.move_selected_step(1))
        duplicate = menu.addAction("Duplicate step")
        duplicate.setEnabled(can_reorder and len(self.steps) < equation_steps.MAX_STEPS)
        duplicate.triggered.connect(self.duplicate_selected_step)
        delete = menu.addAction("Delete step")
        delete.setEnabled(can_reorder)
        delete.triggered.connect(self.delete_selected_step)
        menu.exec(self.preview.mapToGlobal(point))

    def _insert_tex(self, tex: str, cursor_offset: int | None = None) -> None:
        """Insert a palette item and place the cursor in its first editable slot."""
        current = self.equation.text()
        selected = self.equation.selectionStart()
        start = selected if selected >= 0 else self.equation.cursorPosition()
        end = start + len(self.equation.selectedText()) if selected >= 0 else start
        value = current[:start] + tex + current[end:]
        if len(value) > equation_steps.MAX_LINE:
            self._say(f"A line can contain at most {equation_steps.MAX_LINE} characters.", error=True)
            return
        self.equation.setText(value)
        position = start + (len(tex) if cursor_offset is None else cursor_offset)
        self.equation.setCursorPosition(min(position, len(value)))
        self.equation.setFocus(Qt.FocusReason.OtherFocusReason)

    def _backspace(self) -> None:
        current = self.equation.text()
        start = self.equation.selectionStart()
        if start >= 0:
            end = start + len(self.equation.selectedText())
        else:
            end = self.equation.cursorPosition()
            if end == 0:
                return
            start = end - 1
            slash = current.rfind(_BS, 0, end)
            if slash >= 0:
                command_end = slash + 1
                while command_end < len(current) and current[command_end].isalpha():
                    command_end += 1
                if command_end == end:
                    start = slash
        self.equation.setText(current[:start] + current[end:])
        self.equation.setCursorPosition(start)

    def _next_slot(self) -> None:
        current = self.equation.text()
        start = max(self.equation.cursorPosition(), self.equation.selectionStart())
        position = current.find("{", start)
        if position >= 0:
            self.equation.setCursorPosition(position + 1)
            self.equation.setFocus(Qt.FocusReason.OtherFocusReason)

    def _update_compose_actions(self) -> None:
        tex = self.equation.text().strip()
        valid = bool(tex) and len(tex) <= equation_steps.MAX_LINE and equation_steps.line_problem(tex) is None
        self.add_composed_step.setEnabled(valid and len(self.steps) < equation_steps.MAX_STEPS)
        self.update_composed_step.setEnabled(
            valid and self._editing_step is not None and self._editing_step < len(self.steps)
        )
        self.revert_composed_step.setEnabled(
            self._editing_step is not None and self._editing_step < len(self.steps)
        )

    def _on_equation_changed(self) -> None:
        if not self._loading_equation:
            self._equation_dirty = True
        self._update_compose_actions()
        self._update_step_actions()
        self._schedule_equation_preview()

    def clear_composed_line(self) -> None:
        """Discard the line draft without changing the step list."""
        self._loading_equation = True
        self.equation.clear()
        self._loading_equation = False
        self._equation_dirty = False
        self._update_compose_actions()
        self._update_step_actions()
        self._say("Current line cleared.")

    def revert_composed_line(self) -> bool:
        """Reload the selected step and discard its uncommitted edits."""
        index = self._editing_step
        if index is None or index >= len(self.steps):
            return False
        self._equation_dirty = False
        self._loading_equation = True
        self.equation.setText(self.steps[index])
        self.equation.setCursorPosition(len(self.steps[index]))
        self._loading_equation = False
        self.refresh()
        return True

    def _schedule_equation_preview(self, *_args) -> None:
        if hasattr(self, "_preview_timer"):
            self._preview_timer.start()

    def _refresh_equation_preview(self) -> None:
        tex = self.equation.text().strip()
        if not tex:
            self.live_preview.show_message("Type LaTeX or choose symbols below to preview a line.")
            return
        problem = equation_steps.line_problem(tex)
        if problem is not None:
            self.live_preview.show_message(f"Finish the equation structure to preview it: {problem}")
            return
        if self.latex_missing:
            self.live_preview.show_message(self.latex_missing)
            return
        if self.builds is None:
            self.live_preview.show_message("The LaTeX preview needs the build worker.")
            return
        spec = Spec(type="MathTex", params={"text": tex, "font_size": self.font_size.value()})
        known = self.builds.check(spec, ask=True)
        if known is None:
            message = (
                "Preparing the LaTeX preview…"
                if self.builds.client.available
                else "The preview will appear when the LaTeX build worker is available."
            )
            self.live_preview.show_message(message)
            return
        ok, error = known
        if not ok:
            self.live_preview.show_message(error or "LaTeX could not build this line.")
            return
        try:
            outlines = adapter.glyph_outlines(spec)
        except Exception as exc:
            self.live_preview.show_message(adapter.build_failure(exc))
            return
        self.live_preview.show_outlines(outlines, self.colour.property("colour"))

    def _on_build_checked(self, *_args) -> None:
        self.refresh()
        self._refresh_equation_preview()

    def commit_composed_line(self) -> bool:
        """Ctrl+Enter updates the selected step, or appends a new one when none is selected."""
        if self._editing_step is not None:
            updated = self.update_composed_line()
            if not updated:
                self._say("Finish the equation before updating the selected step.", error=True)
            return updated
        return self.add_composed_line()

    def add_composed_line(self) -> bool:
        """Append the equation in the visual builder as a new step."""
        tex = self.equation.text().strip()
        if not tex or equation_steps.line_problem(tex) is not None:
            self._say("Finish the equation before adding it as a step.", error=True)
            return False
        if len(self.steps) >= equation_steps.MAX_STEPS:
            self._say(f"A derivation can have at most {equation_steps.MAX_STEPS} steps.", error=True)
            return False
        current = self.text.toPlainText().rstrip()
        self._set_source_text(f"{current}\n{tex}" if current else tex)
        self._editing_step = None
        self._equation_dirty = False
        self.preview.setCurrentRow(-1)
        self._loading_equation = True
        self.equation.clear()
        self._loading_equation = False
        self._equation_dirty = False
        self._update_compose_actions()
        self._update_step_actions()
        return True

    def update_composed_line(self) -> bool:
        """Replace the selected step with the current builder equation."""
        index = self._editing_step
        tex = self.equation.text().strip()
        if (
            index is None
            or index >= len(self.steps)
            or not tex
            or equation_steps.line_problem(tex) is not None
        ):
            return False
        lines = self.text.toPlainText().splitlines()
        line_indices = self._step_line_indices(lines)
        if index >= len(line_indices):
            return False
        lines[line_indices[index]] = tex
        self._set_source_text("\n".join(lines))
        self._equation_dirty = False
        self._select_preview_step(index)
        self._update_compose_actions()
        return True

    def _set_source_text(self, text: str) -> None:
        self._writing_source = True
        self.text.setPlainText(text)
        self._writing_source = False
        self.refresh()
        self._check_timer.start()
        self._schedule_equation_preview()

    @staticmethod
    def _step_line_indices(lines: list[str]) -> list[int]:
        """Map visible steps to their lines while leaving source comments in place."""
        return [
            index
            for index, line in enumerate(lines)
            if line.strip() and not line.strip().startswith("%")
        ]

    @staticmethod
    def _source_step_blocks(lines: list[str]) -> tuple[list[list[str]], list[str]]:
        """Keep comments and spacing with the following step when the sequence is reordered."""
        blocks: list[list[str]] = []
        pending: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("%"):
                pending.append(line)
                continue
            blocks.append([*pending, line])
            pending = []
        return blocks, pending

    def _selected_step_index(self) -> int | None:
        item = self.preview.currentItem()
        index = item.data(STEP_ROLE) if item is not None else None
        return index if isinstance(index, int) and index < len(self.steps) else None

    def _select_preview_step(self, index: int) -> None:
        for row in range(self.preview.count()):
            item = self.preview.item(row)
            if item.data(STEP_ROLE) == index:
                if self.preview.currentRow() == row:
                    self._select_step(row)
                else:
                    self.preview.setCurrentRow(row)
                return

    def _update_step_actions(self) -> None:
        index = self._selected_step_index()
        can_edit_sequence = index is not None and not self._equation_dirty
        self.move_step_up.setEnabled(can_edit_sequence and index > 0)
        self.move_step_down.setEnabled(can_edit_sequence and index + 1 < len(self.steps))
        self.duplicate_step.setEnabled(
            can_edit_sequence and len(self.steps) < equation_steps.MAX_STEPS
        )
        self.delete_step.setEnabled(can_edit_sequence)

    def move_selected_step(self, delta: int) -> bool:
        index = self._selected_step_index()
        target = index + delta if index is not None else -1
        if self._equation_dirty or index is None or not 0 <= target < len(self.steps):
            return False
        blocks, trailing = self._source_step_blocks(self.text.toPlainText().splitlines())
        blocks[index], blocks[target] = blocks[target], blocks[index]
        lines = [line for block in blocks for line in block] + trailing
        self._set_source_text("\n".join(lines))
        self._equation_dirty = False
        self._select_preview_step(target)
        return True

    def duplicate_selected_step(self) -> bool:
        index = self._selected_step_index()
        if self._equation_dirty or index is None:
            return False
        if len(self.steps) >= equation_steps.MAX_STEPS:
            self._say(f"A derivation can have at most {equation_steps.MAX_STEPS} steps.", error=True)
            return False
        blocks, trailing = self._source_step_blocks(self.text.toPlainText().splitlines())
        formula = blocks[index][-1]
        blocks.insert(index + 1, [formula])
        lines = [line for block in blocks for line in block] + trailing
        self._set_source_text("\n".join(lines))
        self._equation_dirty = False
        self._select_preview_step(index + 1)
        return True

    def delete_selected_step(self) -> bool:
        index = self._selected_step_index()
        if self._equation_dirty or index is None:
            return False
        blocks, trailing = self._source_step_blocks(self.text.toPlainText().splitlines())
        del blocks[index]
        lines = [line for block in blocks for line in block] + trailing
        self._set_source_text("\n".join(lines))
        self._equation_dirty = False
        if self.steps:
            self._select_preview_step(min(index, len(self.steps) - 1))
        else:
            self._editing_step = None
            self._loading_equation = True
            self.equation.clear()
            self._loading_equation = False
            self._equation_dirty = False
        return True

    def _select_step(self, row: int) -> None:
        if self._refreshing_steps:
            return
        item = self.preview.item(row) if row >= 0 else None
        index = item.data(STEP_ROLE) if item is not None else None
        if self._equation_dirty and index != self._editing_step:
            previous = self._editing_step
            if previous is None:
                self.preview.setCurrentRow(-1)
            else:
                self._select_preview_step(previous)
            self._say("Update or revert the current line before selecting another step.", error=True)
            return
        if row < 0:
            self._editing_step = None
            self._update_compose_actions()
            self._update_step_actions()
            return
        if isinstance(index, int) and index < len(self.steps):
            preserve_edit = self._equation_dirty and self._editing_step == index
            self._editing_step = index
            if not preserve_edit:
                self._loading_equation = True
                self.equation.setText(self.steps[index])
                self.equation.setCursorPosition(len(self.steps[index]))
                self._loading_equation = False
                self._equation_dirty = False
        self._update_compose_actions()
        self._update_step_actions()

    def _toggle_latex_source(self, shown: bool) -> None:
        self.text.setVisible(shown)
        if shown:
            if not self._equation_dirty:
                self._load_source_cursor_line()
            self.text.setFocus()
        self._update_compose_actions()

    def _load_source_cursor_line(self) -> None:
        raw_lines = self.text.toPlainText().splitlines()
        cursor_line = self.text.textCursor().blockNumber()
        index = -1
        for line_number, line in enumerate(raw_lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("%"):
                continue
            index += 1
            if line_number == cursor_line:
                self._editing_step = index
                self._loading_equation = True
                self.equation.setText(stripped)
                self.equation.setCursorPosition(len(stripped))
                self._loading_equation = False
                self._equation_dirty = False
                for row in range(self.preview.count()):
                    item = self.preview.item(row)
                    if item.data(STEP_ROLE) == index:
                        self.preview.setCurrentRow(row)
                        break
                self._update_compose_actions()
                self._update_step_actions()
                return
        self._editing_step = None
        self._loading_equation = True
        self.equation.clear()
        self._loading_equation = False
        self._equation_dirty = False
        self._update_compose_actions()
        self._update_step_actions()

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
        if button is getattr(self, "colour", None) and hasattr(self, "_preview_timer"):
            self._schedule_equation_preview()

    # -- deriving ---------------------------------------------------------------------------------

    def _on_operation(self) -> None:
        name = self.operation.currentData()
        op = OPERATIONS.get(name) or FUNCTIONS.get(name)
        if op is None:  # the separator is not a usable choice
            self.operation.setCurrentIndex(0)
            return
        if name == "substitute":
            term_mode = "substitution"
        elif name == "log":
            term_mode = "log-base"
        elif name in ("add", "subtract", "multiply", "divide"):
            term_mode = "expression"
        else:
            term_mode = None
        if term_mode != self._term_mode:
            self.term.clear()
            if name == "log":
                self.term.setText("10")
            self._term_mode = term_mode
        self.term.setEnabled(bool(op.term))
        self.term.setPlaceholderText(op.term or "(no term needed)")
        if name == "ln":
            self.operation_hint.setText("Natural logarithms require positive inputs.")
        elif name in ("log", "log10", "log2"):
            self.operation_hint.setText(
                "Logs need positive inputs and a positive base other than 1."
            )
        elif name in ("sin", "cos", "tan"):
            self.operation_hint.setText(
                "These functions are periodic, so applying one can introduce extra solutions."
            )
        elif name in ("arcsin", "arccos"):
            self.operation_hint.setText(
                "Inverse sine and cosine use their principal ranges; check the values stay in [-1, 1]."
            )
        elif name in FUNCTIONS:
            self.operation_hint.setText("This applies the selected function to both sides.")
        elif name == "divide":
            self.operation_hint.setText("The divisor must be non-zero.")
        elif name == "sqrt":
            self.operation_hint.setText("For real solutions, both sides must be non-negative.")
        else:
            self.operation_hint.clear()

    def derive_line(self) -> bool:
        """Append the line the operation makes from the selected step (else the last line)."""
        if self._equation_dirty:
            try:
                equation_steps.split_equation(self.equation.text().strip())
            except StepsError as error:
                self._say(f"Cannot derive from this line: {error}", error=True)
                return False
            committed = (
                self.update_composed_line()
                if self._editing_step is not None
                else self.add_composed_line()
            )
            if not committed:
                self._say("Finish the edited equation before deriving from it.", error=True)
                return False
        if not self.steps:
            self._say("Type an equation first: the next line is derived from it.", error=True)
            return False
        index = self._selected_step_index()
        source = self.steps[index if index is not None else -1]
        try:
            line = equation_steps.derive(source, self.operation.currentData(), self.term.text())
        except StepsError as error:
            self._say(f"Cannot derive the next line: {error}", error=True)
            return False
        text = self.text.toPlainText().rstrip("\n")
        self._set_source_text(f"{text}\n{line}" if text else line)
        self.preview.setCurrentRow(self.preview.count() - 1)
        return True

    # -- checking ---------------------------------------------------------------------------------

    def _on_text_changed(self) -> None:
        if self._writing_source:
            return
        self.refresh()
        if self.latex_source.isChecked():
            self._load_source_cursor_line()
        self._check_timer.start()
        self._schedule_equation_preview()

    def _check_with_worker(self, tex: str, ask: bool) -> tuple[bool, str] | None:
        if self.builds is None:
            return None
        return self.builds.check(Spec(type="MathTex", params={"text": tex}), ask=ask)

    def refresh(self, check: bool = False) -> None:
        """Read the lines again: their checks, the planned morphs, the summary and the OK button.
        ``check`` also asks about lines whose LaTeX is not known yet (else only known answers)."""
        selected_index = self._selected_step_index()
        selected_row = self.preview.currentRow()
        self._refreshing_steps = True
        self.preview.clear()
        self.problems = {}
        try:
            self.steps = equation_steps.parse_steps(self.text.toPlainText())
        except StepsError as error:
            self.steps = []
            self._refreshing_steps = False
            self._say(str(error), error=True)
            self._set_ok(False)
            self._update_compose_actions()
            self._update_step_actions()
            return
        waiting = 0
        for index, tex in enumerate(self.steps):
            if index > 0:
                plan = equation_steps.plan_transition(self.steps[index - 1], tex)
                matching = "Smart" if self.matching == "smart" else "Classic"
                note = f"    then a {matching} Transform"
                if plan.kind == MATCHING and plan.new:
                    note += f" ({len(plan.new)} new run{'s' * (len(plan.new) != 1)})"
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
        if selected_index is not None and selected_index < len(self.steps):
            self._select_preview_step(selected_index)
        elif 0 <= selected_row < self.preview.count():
            self.preview.setCurrentRow(selected_row)
        self._refreshing_steps = False
        if 0 <= self.preview.currentRow() < self.preview.count():
            self._select_step(self.preview.currentRow())
        else:
            self._update_compose_actions()
            self._update_step_actions()
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
            self._say(
                "Type an equation with LaTeX or the symbol palette, then add it as a step."
            )
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
