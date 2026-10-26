"""A file that already exists (P12.4): replace it, skip it, or keep both.

``ConflictAsker`` is the ``decide`` callable ``core.code_files.export_files`` takes: it is called with
the file name only when that file exists, shows the question, and - when "do this for all the rest"
is ticked - answers the later conflicts of the same export without asking again. Cancel answers None,
which stops the export.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QPushButton, QWidget

from ..code.dialog_frame import DialogFrame, ghost, primary

REPLACE, SKIP, COPY = "replace", "skip", "copy"


class ConflictDialog(QDialog):
    def __init__(
        self, filename: str, folder: str = "", parent: QWidget | None = None, what: str = "file"
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{what.capitalize()} already exists")
        self.setMinimumWidth(420)
        self.answer: str | None = None
        where = f" in {folder}" if folder else ""
        frame = DialogFrame(self, "error", f"{what.capitalize()} already exists", tone="warn")
        text = QLabel(
            f"<b>{_escape(filename)}</b> already exists{_escape(where)}.<br>What should happen to it?"
        )
        text.setWordWrap(True)
        frame.body.addWidget(text)
        self.all_box = QCheckBox(f"Do this for all the remaining {what}s that already exist")
        frame.body.addWidget(self.all_box)
        self.buttons: dict[str, QPushButton] = {}
        for key, label, tip in (
            (REPLACE, "Replace", f"Overwrite the existing {what}"),
            (SKIP, "Skip", f"Leave the existing {what} alone and do not add this one"),
            (COPY, "Keep both", "Add this one next to it with a number: Name (2)"),
        ):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, k=key: self._choose(k))
            self.buttons[key] = button
        self.buttons[COPY].setDefault(True)
        cancel = ghost(QPushButton("Cancel"))
        cancel.setToolTip("Stop here; files already written stay")
        cancel.clicked.connect(self.reject)
        # the actions at the right, the suggested one (Keep both) last; Cancel stays apart at the left
        frame.add_footer(cancel)
        frame.footer.addStretch(1)
        for key in (SKIP, REPLACE, COPY):
            frame.add_footer(self.buttons[key])
        primary(self.buttons[COPY])

    def _choose(self, key: str) -> None:
        self.answer = key
        self.accept()

    def for_all(self) -> bool:
        return self.all_box.isChecked()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ConflictAsker:
    """Ask once per conflict, or once for all of them. ``ask(filename) -> (answer, for_all)`` is the
    hook tests and other front-ends replace; the default shows ``ConflictDialog``."""

    def __init__(self, parent: QWidget | None = None, folder: str | Path = "", what: str = "file") -> None:
        self.parent = parent
        self.what = what
        self.folder = str(folder)
        self.sticky: str | None = None
        self.ask: Callable[[str], tuple[str | None, bool]] = self._dialog

    def _dialog(self, filename: str) -> tuple[str | None, bool]:
        dialog = ConflictDialog(filename, self.folder, self.parent, self.what)
        dialog.exec()
        return dialog.answer, dialog.for_all()

    def __call__(self, filename: str) -> str | None:
        if self.sticky is not None:
            return self.sticky
        answer, for_all = self.ask(filename)
        if answer is not None and for_all:
            self.sticky = answer
        return answer
