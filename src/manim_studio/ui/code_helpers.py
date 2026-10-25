"""Helpers on the Code page (ADR 0058): the explorer section, Run, the management commands, Extract.

A helper is shown in the editor like a code layer, under the key ``helper:<name>`` (the key trust uses,
``trust.HELPER_KEY``), so tabs, drafts, the dirty marker and Revert work for it unchanged. This module
is the glue the page calls for what only a helper has:

* **Run** applies the editor's text (``edits.update_helper``, one undo step), trusts it, and imports it
  once in a throwaway process (``HelperChecker``); what it printed, or its error at its line, shows in
  the Output.
* **New helper**, **Rename** (imports of it in other code follow, and so does their trust), **Delete**
  (refused while code imports it, unless the user insists), **Duplicate**, **Export**.
* **Extract selection to helper** moves whole top-level functions and classes into a new helper and
  imports them back (``core.helper_extract``).
* The rows of the explorer's Helpers section, and which helpers some code needs that may not run yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from pydantic import ValidationError
from PySide6.QtWidgets import QMenu, QWidget

from ..core import code_import, edits, helper_extract, helpers
from ..core.trust import HELPER_KEY
from .code_explorer import Row
from .code_render import CodeStatus
from .helper_checker import HelperChecker

if TYPE_CHECKING:
    from .pages.code import CodePage

EMPTY = "Add a helper: reusable Python your code can import"


def key_of(name: str) -> str:
    """The page's (and trust's) key for helper ``name``."""
    return f"{HELPER_KEY}{name}"


def name_of(key: str | None) -> str | None:
    """The helper a page key names, or None for a layer id."""
    if key is None or not key.startswith(HELPER_KEY):
        return None
    return key[len(HELPER_KEY) :]


@dataclass
class HelperStatus(CodeStatus):
    """What the Output says about a helper: ``untrusted``, ``trusted`` (allowed, not tested in this
    session), ``checking``, ``ready`` (it imported) or ``error``; ``output`` is what it printed."""

    output: str = ""

    @property
    def text(self) -> str:
        if self.state == "checking":
            return "Testing: importing the helper in a separate process..."
        if self.state == "untrusted":
            return "Not run yet: Run (Ctrl+Enter) allows it on this computer and tests its import"
        if self.state == "trusted":
            return "Allowed to run - Run tests its import"
        if self.state == "ready":
            return "Imported without errors"
        return super().text


class HelperActions:
    """The page's helper commands; ``page`` is the Code page."""

    def __init__(self, page: CodePage) -> None:
        self.page = page
        self.checker = HelperChecker(parent=page.split)
        self.checker.finished.connect(self._on_checked)
        self.results: dict[str, tuple[str, HelperStatus]] = {}  # name -> (code tested, what happened)

    @property
    def window(self):
        return self.page.window

    def names(self) -> list[str]:
        project = self.window.project
        return [] if project is None else [h.name for h in project.helpers]

    def _say(self, text: str, ms: int = 8000) -> None:
        self.window.statusBar().showMessage(text, ms)

    # -- what the page shows ----------------------------------------------------------------------

    def status(self, name: str) -> HelperStatus | None:
        code = self.page._code_of(key_of(name))
        if code is None:
            return None
        if self.checker.running(name) == code:
            return HelperStatus("checking")
        if not self.window.trust.is_trusted(code):
            return HelperStatus("untrusted")
        result = self.results.get(name)
        if result is not None and result[0] == code:
            return result[1]
        return HelperStatus("trusted")

    def rows(self, dirty: set[str]) -> tuple[Row, ...]:
        project = self.window.project
        if project is None:
            return ()
        rows = []
        for helper in project.helpers:
            key = key_of(helper.name)
            status = self.status(helper.name)
            state = status.state if status is not None and status.state in ("error", "untrusted") else ""
            tip = {
                "error": "Has an error: see the output",
                "untrusted": "Not run yet: Run allows it and tests its import",
            }.get(state, helper.description or f"import {helper.name}")
            if key in dirty:
                tip = "Unapplied changes: Run applies them"
            rows.append(
                Row(key, helper.name, "helper", "helper", tip, key in dirty, state, helper.description)
            )
        return tuple(rows)

    def used_by(self, name: str) -> str:
        """Who imports helper ``name``, said in a few words for the Output."""
        project = self.window.project
        if project is None:
            return ""
        users = helpers.importers(project, name)
        if not users:
            return f"no code imports it yet: write `import {name}` or `from {name} import ...`"
        labels = [self.page._label_of(user) for user in users]
        shown = ", ".join(labels[:4]) + (f" and {len(labels) - 4} more" if len(labels) > 4 else "")
        return f"imported by {shown}"

    def defines(self, code: str) -> str:
        names = helper_extract.defined_names(code)
        if not names:
            return ""
        return "defines " + ", ".join(names[:8]) + (", ..." if len(names) > 8 else "")

    def untrusted_needed(self, code: str, exclude: str | None = None) -> list[str]:
        """The helpers ``code`` imports (directly or through another helper) that may not run here."""
        project = self.window.project
        if project is None or not project.helpers:
            return []
        skip = name_of(exclude)
        return [
            name
            for name in helpers.needed(project, code)
            if name != skip and not self.window.trust.is_trusted(project.helper(name).code)
        ]

    # -- running -------------------------------------------------------------------------------------

    def run(self, name: str, text: str) -> None:
        """Run on a helper: apply ``text`` (one undo step), trust it, test-import it."""
        page = self.page
        window = self.window
        key = key_of(name)
        window.trust.trust([text])  # code the user applies here is theirs (ADR 0019)
        page.history_keeper.ran(key, text)
        if text != page._code_of(key):
            page._failed = None
            try:
                window.builds.submit(partial(edits.update_helper, name=name, code=text), "Edit helper")
            except (edits.EditError, ValidationError) as error:
                message = _first(error)
                page._failed = (key, text, message)
                self._say(f"Edit helper: {message}", 10000)
                page._refresh_output()
                return
        window.importer.trust_helper(name)
        self.check(name, text)

    def run_applied(self, name: str) -> None:
        """Allow helper ``name``'s code as it is in the project, and test it (the Output's button)."""
        project = self.window.project
        if project is None or name not in self.names():
            return
        code = project.helper(name).code
        self.window.trust.trust([code])
        self.window.importer.trust_helper(name)
        self.check(name, code)
        self._say(f"The helper {name} is allowed to run now", 6000)

    def check(self, name: str, code: str) -> None:
        """Import helper ``name`` (as ``code``) once in a throwaway process."""
        project = self.window.project
        if project is None:
            return
        sources = helpers.sources(project)
        sources[name] = code
        trusted = [n for n, c in sources.items() if self.window.trust.is_trusted(c)]
        self.checker.start(name, code, sources, trusted)
        self.page._on_helper_status(key_of(name))

    def _on_checked(self, name: str, code: str, result: dict) -> None:
        output = str(result.get("output") or "")
        if result.get("ok"):
            status = HelperStatus("ready", output=output)
            self._say(f"The helper {name} imports without errors", 6000)
        else:
            where = str(result.get("where") or "code")
            if where == "code":
                where = key_of(name)  # nothing more precise: the helper as a whole
            status = HelperStatus(
                "error",
                error=str(result.get("error") or "it failed"),
                error_type=str(result.get("type") or ""),
                where=where,
                traceback=str(result.get("traceback") or ""),
                helper_line=result.get("helper_line") if isinstance(result.get("helper_line"), int) else None,
                output=output,
            )
            self._say(f"The helper {name} failed: {status.error}", 10000)
        self.results[name] = (code, status)
        self.page._on_helper_status(key_of(name))

    # -- managing -----------------------------------------------------------------------------------

    def ask_new_name(self, current: str, existing: list[str]) -> str | None:
        """Ask for a helper name; a name that cannot be used is said and None returned."""
        answer = self.page.ask_name(current)
        if answer is None:
            return None
        name = answer.strip()
        problem = helpers.check_name(name, existing, installed=True)
        if problem is not None:
            self._say(f"Helper name: {problem}", 10000)
            return None
        return name

    def _submit(self, op, label: str) -> bool | None:
        """Apply an edit; None when it was refused (the reason is said)."""
        try:
            return self.window.builds.submit(op, label)
        except (edits.EditError, ValidationError) as error:
            self._say(f"{label}: {_first(error)}", 10000)
            return None

    def new_helper(self) -> None:
        """Add a helper with the starter code and open it here (one undo step)."""
        if self.window.project is None:
            self._say("Create or open a project first.", 5000)
            return
        existing = self.names()
        name = self.ask_new_name(code_import.helper_name("my_helper", existing), existing)
        if name is None:
            return
        code = helpers.STARTER.replace("{name}", name)
        self.window.trust.trust([code])  # the editor's own starter, like a new Python object's
        if self._submit(partial(edits.add_helper, name=name, code=code), "New helper") is None:
            return
        self.page.open_when_ready(key_of(name))

    def rename(self, name: str) -> None:
        """Rename a helper; the code importing it is rewritten, and keeps its trust."""
        project = self.window.project
        if project is None or name not in self.names():
            return
        others = [n for n in self.names() if n != name]
        new = self.ask_new_name(name, others)
        if new is None or new == name:
            return
        try:
            edit = edits.rename_helper(project, name, new)
        except (edits.EditError, ValidationError) as error:
            self._say(f"Rename helper: {_first(error)}", 10000)
            return
        self.window.trust.carry(edit.rewritten)  # trust is by text: the rewritten imports keep theirs
        old_key, new_key = key_of(name), key_of(new)
        self.page.rekey(old_key, new_key)
        if name in self.results:
            self.results[new] = self.results.pop(name)
        if self._submit(partial(edits.rename_helper, old=name, new=new), "Rename helper") is None:
            self.page.rekey(new_key, old_key)
            return
        self.page._after_change()  # the tab and the title say the new name
        fixed = len(edit.rewritten)
        also = f"; {fixed} import{'s' if fixed != 1 else ''} of it rewritten" if fixed else ""
        self._say(f"Renamed the helper {name} to {new}{also}", 8000)

    def delete(self, name: str) -> None:
        """Delete a helper (one undo step); while code imports it, say who and ask first."""
        project = self.window.project
        if project is None or name not in self.names():
            return
        try:
            edits.remove_helper(project, name)
        except edits.EditError as error:
            question = (
                f"The {error}. Delete it anyway? That code will fail at its import until you add the "
                "helper back (Ctrl+Z undoes)."
            )
            if not self.page.confirm("Delete helper", question):
                return
            self._submit(partial(edits.remove_helper, name=name, force=True), "Delete helper")
            return
        self._submit(partial(edits.remove_helper, name=name), "Delete helper")

    def duplicate(self, name: str) -> None:
        project = self.window.project
        if project is None or name not in self.names():
            return
        helper = project.helper(name)
        new = code_import.helper_name(f"{name}_copy", self.names())
        op = partial(edits.add_helper, name=new, code=helper.code, description=helper.description)
        if self._submit(op, "Duplicate helper") is not None:  # the same text: trusted if the first is
            self.page.open_when_ready(key_of(new))

    def export(self, name: str) -> None:
        """Write helper ``name`` (the text in the editor, if it is open) as ``<name>.py``."""
        self.window.importer.export_code(self.page._export_entries(), checked={key_of(name)})

    # -- extract ------------------------------------------------------------------------------------

    def extract(self) -> None:
        """Move the selected top-level functions and classes (or the one at the cursor) into a new
        helper and import them back: the helper is one undo step of the project, the code's change
        one step of the editor's undo (nothing is applied until Run)."""
        page = self.page
        key = page.layer_id
        if key is None or page.preset_id is not None or self.window.project is None:
            self._say("Open a code layer, a Python object or a helper first", 5000)
            return
        editor = page.editor
        cursor = editor.textCursor()
        text = editor.text()
        span: dict = {"cursor": cursor.blockNumber() + 1}
        if cursor.hasSelection():
            document = editor.document()
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            first = document.findBlock(start).blockNumber() + 1
            last_block = document.findBlock(end)
            last = last_block.blockNumber() + 1
            if end == last_block.position() and last > first:
                last -= 1  # the selection ends at the start of a line: that line is not in it
            span = {"first": first, "last": last}
        try:
            trial = helper_extract.extract(text, "helper_name", **span)
        except helper_extract.ExtractError as error:
            self._say(f"Extract to helper: {error}", 10000)
            return
        existing = self.names()
        name = self.ask_new_name(code_import.helper_name(trial.names[0], existing), existing)
        if name is None:
            return
        try:
            result = helper_extract.extract(text, name, origin=page._label_of(key), **span)
        except helper_extract.ExtractError as error:
            self._say(f"Extract to helper: {error}", 10000)
            return
        self.window.trust.trust([result.helper_code])  # moved from the user's own text
        op = partial(edits.add_helper, name=name, code=result.helper_code)
        if self._submit(op, "Extract to helper") is None:
            return
        editor.replace_text(result.code)  # one step of the editor's own undo
        moved = ", ".join(result.names)
        self._say(f"Moved {moved} to the helper {name}: Run applies the code (Ctrl+Z in the editor undoes)")

    # -- menus --------------------------------------------------------------------------------------

    def row_menu(self, key: str, parent: QWidget) -> QMenu:
        """The right-click menu of a helper row."""
        name = name_of(key) or ""
        menu = QMenu(parent)
        page = self.page
        for text, slot, tip in (
            ("Open", partial(page.open_item, key), "Edit this helper"),
            (
                "Run",
                partial(page.run_item, key),
                "Apply it, allow it to run and test its import (Ctrl+Enter)",
            ),
            ("Rename...", partial(self.rename, name), "Rename it; the code importing it is updated (F2)"),
            ("Duplicate", partial(self.duplicate, name), "Add a copy under another name"),
            ("Save as preset...", partial(page.save_item_as_preset, key), "Keep this helper in your presets"),
            ("Export...", partial(self.export, name), f"Write it as {name}.py"),
            ("Delete", partial(self.delete, name), "Delete the helper (Delete; Ctrl+Z brings it back)"),
        ):
            menu.addAction(text, slot).setToolTip(tip)
        return menu

    def section_menu(self, parent: QWidget) -> QMenu:
        """The right-click menu of the Helpers section header."""
        menu = QMenu(parent)
        menu.addAction("New helper...", self.new_helper).setToolTip(
            "Add a helper: plain Python (functions, constants, data) your code imports by its name"
        )
        menu.addAction("Add file...", self.page.add_code_file).setToolTip(
            "Add .py files: a file without build(p) or a Scene is offered as a helper"
        )
        menu.addAction("Extract selection to helper...", self.extract).setToolTip(
            "Move the selected top-level functions and classes into a new helper and import them back"
        )
        return menu


def _first(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return str(error.errors()[0]["msg"]).removeprefix("Value error, ")
    return str(error)
