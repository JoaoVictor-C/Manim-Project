"""Code files (P12.1, ADR 0056): reading, inspecting and exporting ``.py`` files - pure, no Qt, no Manim.

The Code page opens files, the import window asks what a file is (a Python object, ADR 0051, or a
Manim scene, ADR 0019) and Export writes code out as files. This module is what they share:

* ``read_source`` reads a file as text (UTF-8, with or without a BOM, at most ``MAX_BYTES``).
* ``inspect`` says what a text is - **syntax only**: the code is parsed, never imported or run - and
  proposes a name for it.
* ``safe_stem`` / ``free_name`` make file names that are valid on Windows and do not collide.
* ``export_files`` writes several files into a folder and asks what to do, per file, only when
  the file is already there (replace, skip or keep both).
"""

from __future__ import annotations

import ast
import os
import re
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import python_object
from .scene_import import scene_classes

MAX_BYTES = 1024 * 1024  # the largest source file the editor reads
MAX_SUMMARY = 120
MAX_STEM = 100  # characters of a file name's stem (a path must stay short enough on Windows)
EXTENSION = ".py"
RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
)
FORBIDDEN = set('<>:"/\\|?*')

Kind = Literal["object", "scene", "unknown"]
Choice = Literal["replace", "skip", "copy"]


class SourceError(Exception):
    """A source file that cannot be read; ``reason`` is written for the user."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# -- reading -----------------------------------------------------------------------------------------


def read_source(path: str | Path) -> str:
    """The text of the file at ``path``: UTF-8, a BOM dropped, line endings kept as they are.

    Raises ``SourceError`` (with a reason for the user) when the file cannot be read, is not UTF-8
    text or is larger than ``MAX_BYTES``.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
        if size > MAX_BYTES:
            raise SourceError(f"{path.name} is too large ({size / 1024 / 1024:.1f} MB; the limit is 1 MB)")
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise SourceError(f"cannot read {path.name}: {exc.strerror or exc}") from exc
    if len(data) > MAX_BYTES:  # grew while it was read
        raise SourceError(f"{path.name} is too large (the limit is 1 MB)")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceError(f"{path.name} is not UTF-8 text (byte {exc.start} cannot be read)") from exc
    if "\x00" in text:
        raise SourceError(f"{path.name} is not a text file")
    return text


# -- inspecting --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Inspection:
    """What a source text is, read without running it.

    ``kind``: ``scene`` (it defines a Scene class; the code layer of ADR 0019 - wins when the text
    also looks like an object), ``object`` (it defines ``PARAMS`` or ``build``: a Python object, ADR
    0051) or ``unknown``. ``scenes``: the Scene classes, in order. ``params``: the parameters an
    object declares. ``problem``: a syntax error (or an unreadable ``PARAMS``) with its line, else
    None. ``suggested_name`` names the layer or preset; ``summary`` is one line saying what the code
    is (its docstring or leading comment).
    """

    kind: Kind
    scenes: tuple[str, ...]
    params: tuple[python_object.PyParam, ...]
    problem: str | None
    suggested_name: str
    summary: str


def inspect(source: str, filename: str = "") -> Inspection:
    """What ``source`` is (syntax only: nothing is imported or run); ``filename`` helps name it."""
    source = source.lstrip("\ufeff")
    stem = _file_stem(filename)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        where = f"line {exc.lineno}: " if exc.lineno else ""
        return Inspection(
            "unknown", (), (), f"{where}SyntaxError: {exc.msg}", _title(stem) or "Code", _comment(source)
        )
    except (ValueError, RecursionError, MemoryError) as exc:  # a NUL character, absurd nesting
        return Inspection("unknown", (), (), f"SyntaxError: {exc}", _title(stem) or "Code", _comment(source))
    scenes = tuple(scene_classes(source))
    params: tuple[python_object.PyParam, ...] = ()
    problem: str | None = None
    kind: Kind = "unknown"
    if scenes:
        kind = "scene"
    elif _is_object(tree):
        kind = "object"
        found = python_object.params_problem(source)
        if found is None:
            params = python_object.read_params(source)
        else:
            problem = str(found)
    name = scenes[0] if scenes else (_title(stem) or "Code")
    summary = _first_line(ast.get_docstring(tree) or "") or _comment(source)
    return Inspection(kind, scenes, params, problem, name, _clip(summary))


def _is_object(tree: ast.Module) -> bool:
    """Does the module define ``PARAMS`` or ``build`` at top level (a Python object, ADR 0051)?"""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "build":
            return True
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PARAMS" for t in node.targets
        ):
            return True
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PARAMS"
        ):
            return True
    return False


def _file_stem(filename: str) -> str:
    base = re.split(r"[\\/]", filename)[-1]
    if base.lower().endswith(EXTENSION):
        return base[: -len(EXTENSION)]
    return os.path.splitext(base)[0]


def _title(stem: str) -> str:
    """``right_triangle`` -> ``Right Triangle`` (a word keeps the capitals it has)."""
    words = [w for w in re.split(r"[\s_\-]+", stem.strip(". ")) if w]
    return " ".join(w[0].upper() + w[1:] for w in words)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _comment(source: str) -> str:
    """The first meaningful comment line at the top of the file (not a shebang or encoding line)."""
    for line in source.splitlines():
        text = line.strip()
        if not text:
            continue
        if not text.startswith("#"):
            return ""
        if text.startswith("#!") or re.match(r"#.*coding[:=]", text):
            continue
        text = text.lstrip("#").strip()
        if text:
            return text
    return ""


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_SUMMARY else text[: MAX_SUMMARY - 1].rstrip() + "…"


# -- file names --------------------------------------------------------------------------------------


def safe_stem(label: str, fallback: str = "Code") -> str:
    """A file name stem made from ``label`` that is valid on Windows: no ``<>:"/\\|?*`` or control
    characters, no trailing dots or spaces, and not a reserved device name (``CON``, ``NUL``,
    ``COM1``...: ``_`` is added after it). ``fallback`` (cleaned the same way) when nothing is left."""
    return _clean(label) or _clean(fallback) or "Code"


def _clean(label: str) -> str:
    text = "".join(c for c in label if c not in FORBIDDEN and ord(c) >= 32 and ord(c) != 127)
    text = text.strip()[:MAX_STEM].rstrip(". ")
    head, dot, rest = text.partition(".")
    if head.rstrip(" ").upper() in RESERVED:  # Windows treats CON.anything like CON
        text = f"{head}_{dot}{rest}"
    return text


def free_name(filename: str, taken: Iterable[str]) -> str:
    """``filename``, or ``Name (2).py``, ``Name (3).py``... when it is in ``taken`` (case-insensitive)."""
    used = {name.lower() for name in taken}
    if filename.lower() not in used:
        return filename
    stem, extension = os.path.splitext(filename)
    n = 2
    while f"{stem} ({n}){extension}".lower() in used:
        n += 1
    return f"{stem} ({n}){extension}"


# -- exporting ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportResult:
    """What ``export_files`` did, by file name. ``written``: new files; ``replaced``: files that
    were there and were overwritten; ``copied``: files written under another name because the name
    was taken; ``skipped``: files not written because the user chose to skip them or cancelled;
    ``failed``: ``(file name, reason)`` for files that could not be written. ``cancelled``: the user
    cancelled, so the files after the cancelling one were not written."""

    written: tuple[str, ...] = ()
    replaced: tuple[str, ...] = ()
    copied: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()
    cancelled: bool = False

    @property
    def saved(self) -> int:
        """How many files are on disk now."""
        return len(self.written) + len(self.replaced) + len(self.copied)


def export_files(
    items: Iterable[tuple[str, str]],
    folder: str | Path,
    decide: Callable[[str], Choice | None],
) -> ExportResult:
    """Write each ``(stem, source)`` of ``items`` to ``folder`` as ``<stem>.py``.

    Files are UTF-8 without a BOM, line endings as given, each written whole (to a temporary file in
    the folder, then moved over) so a failure never leaves half a file. Two items with one stem never
    overwrite each other: the later one is written as ``Name (2).py``. When a file is already there,
    ``decide(file name)`` says ``"replace"``, ``"skip"`` or ``"copy"`` (written as a free ``Name (2).py``);
    ``None`` cancels: it and the files after it are skipped. A file that cannot be written is
    recorded as failed and the others go on.
    """
    folder = Path(folder)
    todo = [(safe_stem(stem) + EXTENSION, source) for stem, source in items]
    written: list[str] = []
    replaced: list[str] = []
    copied: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []
    cancelled = False

    def result() -> ExportResult:
        return ExportResult(
            tuple(written), tuple(replaced), tuple(copied), tuple(skipped), tuple(failed), cancelled
        )

    try:
        folder.mkdir(parents=True, exist_ok=True)
        existing = {entry.name.lower() for entry in folder.iterdir()}
    except OSError as exc:
        reason = str(exc.strerror or exc)
        failed.extend((name, reason) for name, _ in todo)
        return result()
    used: set[str] = set()  # the names this export has written
    for index, (name, source) in enumerate(todo):
        action = "write"
        if name.lower() in used:  # an earlier item took the name: this one is a copy
            name, action = free_name(name, used | existing), "copy"
        elif name.lower() in existing:
            choice = decide(name)
            if choice is None:
                cancelled = True
                skipped.extend(_names(todo[index:], used))
                break
            if choice == "skip":
                skipped.append(name)
                continue
            if choice == "copy":
                name, action = free_name(name, used | existing), "copy"
            else:
                action = "replace"
        try:
            _write(folder / name, source)
        except (OSError, UnicodeError) as exc:
            failed.append((name, str(getattr(exc, "strerror", None) or exc)))
            continue
        used.add(name.lower())
        existing.add(name.lower())
        {"write": written, "replace": replaced, "copy": copied}[action].append(name)
    return result()


def _names(rest: list[tuple[str, str]], used: set[str]) -> list[str]:
    """The names the files not written would have had (a repeated name as ``Name (2).py``)."""
    seen, out = set(used), []
    for name, _ in rest:
        name = free_name(name, seen)
        seen.add(name.lower())
        out.append(name)
    return out


def _write(path: Path, source: str) -> None:
    """Write ``source`` to ``path`` whole: a temporary file next to it, then moved over it."""
    data = source.encode("utf-8")
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(data)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
