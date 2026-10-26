"""Helpers (ADR 0058): modules of the project that code layers, Python objects and other helpers import.

A helper is plain Python saved in the project (``Project.helpers``): functions, classes, constants,
data. While user code runs, ``install`` puts an import finder at the front of ``sys.meta_path`` that
serves each helper's source as a module named after it, so ``import grid_tools`` or ``from grid_tools
import make_grid`` works. The modules are removed afterwards, so an edit is always picked up. Trust is
enforced at the import: given a ``trusted`` test, a helper that is not trusted raises ``ImportError``.

The static questions - what a source imports (``imports_of``), which helpers a code text needs
(``needed``) - read the source without running it; they are for showing a layer what it needs and
for opening a project, never the gate. ``digest`` is mixed into the signature of every code layer
and Python object, so editing a helper rebuilds all of them (coarse on purpose). Pure: no Qt, no
Manim.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import keyword
import linecache
import sys
import tokenize
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from io import StringIO
from types import ModuleType
from typing import TYPE_CHECKING

from .code_cache import code_hash

if TYPE_CHECKING:
    from ..model.schema import Project

MAX_CODE = 64 * 1024  # characters of source a helper may hold
MAX_HELPERS = 50
FILENAME_PREFIX = "<helper "  # what tracebacks name a helper's file: "<helper grid_tools>"
# Names a helper may not take: what the runners provide, Manim, numpy, this package (and its own module).
RESERVED = frozenset({"manim", "numpy", "np", "math", "m", "manim_studio", "helpers"})
RESERVED_PREFIX = "studio_"  # the names the editor gives its own modules ("studio_python_object")
NOT_TRUSTED = "helper '{name}' is not trusted yet: select it on the Code page and press Run"

STARTER = '''"""A helper: plain Python that code layers, Python objects and other helpers import.

Import it by its name, e.g. ``from {name} import double``. It is not run with Manim's names
imported: import what it needs itself (``from manim import *``, ``import numpy as np``).
"""


def double(x):
    """Twice x."""
    return 2 * x
'''

Sources = Mapping[str, str]  # helper name -> its source


def filename(name: str) -> str:
    """What tracebacks call helper ``name``'s file."""
    return f"{FILENAME_PREFIX}{name}>"


def helper_for_filename(name: str) -> str | None:
    """The helper a traceback filename such as ``"<helper grid>"`` belongs to, or None."""
    if not name.startswith(FILENAME_PREFIX) or not name.endswith(">"):
        return None
    helper = name[len(FILENAME_PREFIX) : -1]
    return helper if helper.isidentifier() else None


def sources(project: Project | Sources) -> dict[str, str]:
    """The project's helpers as ``{name: source}`` (a mapping is returned as a copy)."""
    if isinstance(project, Mapping):
        return dict(project)
    return {helper.name: helper.code for helper in project.helpers}


# -- names ------------------------------------------------------------------------------------------------


def check_name(name: str, existing: Iterable[str] = (), *, installed: bool = False) -> str | None:
    """Why ``name`` cannot name a helper, or None.

    A helper's name is a Python identifier, not a keyword, not one of ``existing``, and must not
    shadow the standard library, Manim, numpy, the names the runners provide or the editor's own
    modules. With ``installed``, a module installed on this computer is refused too (a helper named
    like it would hide it while user code runs); the file format does not ask that - a project must
    open on any computer - so only new names are checked against it.
    """
    if not isinstance(name, str) or not name:
        return "a helper needs a name"
    if not name.isidentifier() or not name.isascii():
        return f"{name!r} is not a Python name (use letters, digits and _, not starting with a digit)"
    if keyword.iskeyword(name) or keyword.issoftkeyword(name):
        return f"{name!r} is a Python keyword"
    if name in set(existing):
        return f"a helper named {name!r} already exists"
    if name in RESERVED or name.startswith(RESERVED_PREFIX):
        return f"{name!r} is a name the editor uses (Manim, numpy, np, math, m, studio_...)"
    if name in sys.stdlib_module_names or name in sys.builtin_module_names:
        return f"{name!r} is a module of Python's standard library"
    if installed and _installed(name):
        return f"{name!r} is a module installed on this computer: a helper would hide it"
    return None


def _installed(name: str) -> bool:
    """Whether a module ``name`` is loaded or could be imported here (found, never run)."""
    loaded = sys.modules.get(name)
    if loaded is not None and helper_for_filename(str(getattr(loaded, "__file__", ""))) is None:
        return True
    try:
        return importlib.machinery.PathFinder.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# -- what code imports ----------------------------------------------------------------------------------


def imports_of(source: str) -> set[str]:
    """The top-level module names ``source`` imports, anywhere in it (``import a.b`` -> ``a``;
    relative imports are not modules of the project). Read without running it; a source that
    cannot be parsed imports nothing."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def needed(project: Project | Sources, code: str) -> list[str]:
    """The helpers ``code`` needs: those it imports and, transitively, those they import - each
    after the helpers it imports (dependency order), each once, safe with import cycles."""
    known = sources(project)
    order: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        for other in sorted(imports_of(known[name]) & known.keys()):
            visit(other)
        order.append(name)

    for name in sorted(imports_of(code) & known.keys()):
        visit(name)
    return order


def importers(project: Project, name: str) -> list[str]:
    """What imports helper ``name``: the ids of code layers and Python objects, then ``helper:<n>``
    for the other helpers (the keys ``trust.project_code`` uses), in project order."""
    from ..model.schema import CODE_TYPES, PYTHON_TYPES

    out = [
        layer.id
        for layer in project.layers
        if layer.spec is not None
        and layer.spec.type in CODE_TYPES | PYTHON_TYPES
        and name in imports_of(str(layer.spec.params.get("code", "")))
    ]
    return out + [
        f"helper:{h.name}" for h in project.helpers if h.name != name and name in imports_of(h.code)
    ]


def digest(project: Project | Sources) -> str:
    """A stable identity of every helper's name and code: ``""`` without helpers, so the signatures
    of a project that has none are what they were before helpers existed."""
    known = sources(project)
    if not known:
        return ""
    return _digest(tuple(sorted(known.items())))


@lru_cache(maxsize=64)
def _digest(items: tuple[tuple[str, str], ...]) -> str:
    """Asked per frame and per build: the same texts are hashed once (a str keeps its own hash)."""
    material = json.dumps([(name, code_hash(code)) for name, code in items])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def code_changed(old: Project, new: Project) -> bool:
    """Whether the helpers' names or code differ between two snapshots (a description does not)."""
    if old.helpers == new.helpers:
        return False
    return sources(old) != sources(new)


# -- serving them while user code runs ---------------------------------------------------------------------


class _HelperFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves helpers as top-level modules, compiled from their text (no bytecode cache)."""

    def __init__(self, known: dict[str, str], trusted: Callable[[str], bool] | None) -> None:
        self.known = known
        self.trusted = trusted
        self.created: list[str] = []  # module names this finder put into sys.modules

    def find_spec(self, fullname, path=None, target=None):
        if path is not None or fullname not in self.known:
            return None  # helpers are top-level modules without submodules
        return importlib.util.spec_from_loader(fullname, self, origin=filename(fullname))

    def create_module(self, spec):
        return None  # the default module

    def exec_module(self, module: ModuleType) -> None:
        name = module.__name__
        if self.trusted is not None and not self.trusted(name):
            raise ImportError(NOT_TRUSTED.format(name=name), name=name)
        source = self.known[name]
        module.__file__ = filename(name)
        module.__package__ = ""
        lines = source.splitlines(keepends=True)
        linecache.cache[module.__file__] = (len(source), None, lines, module.__file__)  # traceback text
        if name not in self.created:
            self.created.append(name)
        exec(compile(source, module.__file__, "exec", dont_inherit=True), module.__dict__)


def _is_helper_module(module: object, name: str) -> bool:
    return getattr(module, "__file__", None) == filename(name)


@contextmanager
def install(sources: Sources, *, trusted: Callable[[str], bool] | None = None) -> Iterator[None]:
    """While inside, ``import <helper>`` serves ``sources[helper]`` as a module.

    The finder goes to the front of ``sys.meta_path``; each module's ``__name__`` is the helper's
    name, its ``__file__`` (and the filename its code is compiled with) ``"<helper name>"``, its
    ``__package__`` empty. A helper may import another. On entry, helper modules left in
    ``sys.modules`` by an earlier run are dropped (so an edit is always picked up); on exit the
    finder is removed and every helper module it created is deleted. ``trusted(name)``, when
    given, decides which helpers may run: importing another raises ``ImportError`` saying so.
    """
    known = dict(sources)
    if not known:
        yield  # nothing to serve: user code imports exactly as before
        return
    for name in known:
        if _is_helper_module(sys.modules.get(name), name):
            del sys.modules[name]
    finder = _HelperFinder(known, trusted)
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        for name in finder.created:
            if _is_helper_module(sys.modules.get(name), name):
                del sys.modules[name]


# -- where an error happened ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Place:
    """Where an error came from: ``line`` in the user's code (its innermost frame there: the import
    or the call that led into a helper), and ``where`` - ``"code"``, or ``"helper:<name>"`` when the
    innermost user-written frame is in a helper, with that helper's ``helper_line``."""

    line: int | None = None
    where: str = "code"
    helper_line: int | None = None

    @property
    def helper(self) -> str | None:
        return self.where.removeprefix("helper:") if self.where.startswith("helper:") else None


def locate(error: BaseException, code_filename: str) -> Place:
    """Where ``error`` was raised: the user's code is compiled as ``code_filename``, helpers as
    ``"<helper name>"``. A syntax error in a helper points at the helper's line."""
    line = None
    inner: tuple[str, int] | None = None  # (helper, line) when the innermost user frame is a helper
    tb = error.__traceback__
    while tb is not None:
        name = tb.tb_frame.f_code.co_filename
        if name == code_filename:
            line, inner = tb.tb_lineno, None
        elif (helper := helper_for_filename(name)) is not None:
            inner = (helper, tb.tb_lineno)
        tb = tb.tb_next
    if isinstance(error, SyntaxError):
        if error.filename == code_filename:
            return Place(error.lineno)
        if (helper := helper_for_filename(str(error.filename))) is not None:
            return Place(line, f"helper:{helper}", error.lineno)
    if inner is not None:
        return Place(line, f"helper:{inner[0]}", inner[1])
    return Place(line)


# -- renaming: imports of a helper in other code ------------------------------------------------------------


def rename_imports(source: str, old: str, new: str) -> str | None:
    """``source`` with its imports of module ``old`` turned into imports of ``new``, or None when
    nothing changes or it cannot be done safely (the source does not parse).

    ``from old import x`` becomes ``from new import x`` and ``import old as y`` becomes ``import new
    as y``. A plain ``import old`` becomes ``import new`` with every use of the name ``old`` renamed
    when that is safe (``old`` is bound by nothing else and ``new`` is not used at all); otherwise
    ``import new as old``, which keeps every use working. ``import old.sub`` is left alone (a helper
    has no submodules). Only the names themselves are rewritten, located by the parser.
    """
    try:
        tree = ast.parse(source)
        tokens = list(tokenize.generate_tokens(StringIO(source).readline))
    except (SyntaxError, ValueError, tokenize.TokenError):
        return None
    plain: list[ast.alias] = []
    edits: list[tuple[tuple[int, int], tuple[int, int], str]] = []  # ((row, col), (row, col), text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name != old:
                    continue
                start = (alias.lineno, alias.col_offset)
                if alias.asname is not None:
                    edits.append((start, (alias.lineno, alias.col_offset + len(old)), new))
                else:
                    plain.append(alias)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == old:
            token = _name_after_from(tokens, node.lineno, old)
            if token is None:
                return None
            text = source.splitlines(keepends=True)[token.start[0] - 1]
            begin = len(text[: token.start[1]].encode("utf-8"))  # token columns are characters
            edits.append(((token.start[0], begin), (token.end[0], begin + len(old.encode("utf-8"))), new))
    if plain:
        uses = _uses_if_safe(tree, old, new)
        for alias in plain:
            start, end = (alias.lineno, alias.col_offset), (alias.lineno, alias.col_offset + len(old))
            edits.append((start, end, new if uses is not None else f"{new} as {old}"))
        for use in uses or ():
            edits.append(((use.lineno, use.col_offset), (use.end_lineno, use.end_col_offset), new))
    if not edits:
        return None
    lines = source.splitlines(keepends=True)
    for (row, col), (end_row, end_col), text in sorted(edits, reverse=True):
        if row != end_row:
            return None  # a name never spans lines
        line = lines[row - 1]
        start, stop = _char_index(line, col), _char_index(line, end_col)
        lines[row - 1] = line[:start] + text + line[stop:]
    return "".join(lines)


def _char_index(line: str, utf8_offset: int) -> int:
    """The str index of a UTF-8 byte offset (what the parser reports) in ``line``."""
    return len(line.encode("utf-8")[:utf8_offset].decode("utf-8", errors="ignore"))


def _name_after_from(tokens: list[tokenize.TokenInfo], row: int, name: str):
    """The NAME token of module ``name`` in a ``from`` statement on line ``row``."""
    for index, token in enumerate(tokens):
        if token.type == tokenize.NAME and token.string == "from" and token.start[0] == row:
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            if following is not None and following.type == tokenize.NAME and following.string == name:
                after = tokens[index + 2] if index + 2 < len(tokens) else None
                if after is None or after.string != ".":
                    return following
    return None


def _uses_if_safe(tree: ast.AST, old: str, new: str) -> list[ast.Name] | None:
    """The loads of name ``old``, when renaming them to ``new`` is safe: ``old`` is bound by
    nothing but plain ``import old`` statements, and ``new`` appears nowhere. None otherwise."""
    uses: list[ast.Name] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id == new or (node.id == old and not isinstance(node.ctx, ast.Load)):
                return None
            if node.id == old:
                uses.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in (old, new):
                return None
        elif isinstance(node, ast.arg):
            if node.arg in (old, new):
                return None
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            if {old, new} & set(node.names):
                return None
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                plain_import = isinstance(node, ast.Import) and alias.name == old and alias.asname is None
                if bound == new or (bound == old and not plain_import):
                    return None
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            if node.name in (old, new):
                return None
        elif isinstance(node, ast.MatchMapping):
            if node.rest in (old, new):
                return None
    return uses
