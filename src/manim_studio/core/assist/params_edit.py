"""Editing a Python object's ``PARAMS`` in its source (P13.3) - pure, no Qt, no Manim.

The Code page lets the user add, remove, rename and retype the parameters of a Python object with a
form (ADR 0051 explains ``PARAMS``). This module turns such a request into a new source text **without
disturbing anything else**: only the text of the entry being changed (or the line an added entry
takes) differs - the comments, blank lines, trailing commas, tabs and line endings (``\\n`` or
``\\r\\n``) of the rest of the file stay byte for byte. The tests check that a change followed by its
undo gives back the very same text.

``PARAMS`` is found as ``python_object`` finds it (the last top-level assignment) and must be a plain
``{...}`` literal: keys that are text, values that are plain literals, no ``**`` unpacking. Anything
else is refused with a reason the user can read (``ParamsEditError``) rather than guessed at. Code that
reads a parameter (``p["name"]``) is **not** touched: renaming a parameter leaves the ``build`` function
to the user.

Values are written the way people write them in ``PARAMS``: a float keeps its decimal point (``30.0``),
a whole number has none, ``True``/``False``, text in double quotes, and a number with limits is the
tuple ``(default, minimum, maximum)``. A colour is text: ``"#ff0000"``.
"""

from __future__ import annotations

import ast
import json
import math
from dataclasses import dataclass
from typing import Any

from .source_text import NEWLINE as _NEWLINE
from .source_text import SourceText as _Text

BOM = "\ufeff"


class ParamsEditError(ValueError):
    """``PARAMS`` cannot be edited this way; ``reason`` says why, for the user."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _NoParamsError(ParamsEditError):
    """There is no ``PARAMS`` to edit (or the code cannot be read at all)."""


# -- operations ------------------------------------------------------------------------------------


class _Unchanged:
    """The marker of a ``ChangeParam`` field that is left as it is (``None`` means "no limit")."""

    def __repr__(self) -> str:
        return "UNCHANGED"


UNCHANGED: Any = _Unchanged()


@dataclass(frozen=True)
class AddParam:
    """Add ``name`` with a default (a number, True/False or text); a number may have limits."""

    name: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class RemoveParam:
    """Remove ``name`` from ``PARAMS``."""

    name: str


@dataclass(frozen=True)
class RenameParam:
    """Give the parameter ``old`` the name ``new`` (its value and comment stay)."""

    old: str
    new: str


@dataclass(frozen=True)
class ChangeParam:
    """Change a parameter's default and/or limits; leave out what stays (``UNCHANGED``).

    A default of another type changes the parameter's type. ``minimum=None`` / ``maximum=None`` remove the
    limits (both go together: a limit alone cannot be written). A default that is not a number drops the
    limits unless they are given.
    """

    name: str
    default: Any = UNCHANGED
    minimum: Any = UNCHANGED
    maximum: Any = UNCHANGED


Operation = AddParam | RemoveParam | RenameParam | ChangeParam


# -- layout ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ParamEntry:
    """One ``"key": value`` of ``PARAMS``. Offsets are positions in the source text (characters)."""

    key: str
    key_start: int
    key_end: int  # the key's own text, quotes included
    value_start: int
    value_end: int  # the value's own text (a tuple includes its parentheses)
    value_text: str
    comma: int | None  # offset of the comma after the entry, if any
    comment: str  # the ``#`` comment on the entry's line after it (without the ``#``), stripped
    comment_start: int | None
    comment_end: int | None
    end: int  # just after the entry's comma, or its value when it has none
    own_line: bool  # the entry is alone on its line(s): nothing else before it or after it (but a comment)

    @property
    def start(self) -> int:
        return self.key_start


@dataclass(frozen=True)
class ParamsLayout:
    """Where ``PARAMS`` and its entries are in the source."""

    start: int  # the assignment statement
    end: int
    dict_start: int  # the ``{``
    dict_end: int  # just after the ``}``
    entries: tuple[ParamEntry, ...]
    multiline: bool  # the dict spans lines
    trailing_comma: bool  # the last entry has a comma after it
    indent: str  # the whitespace one entry is indented by (for an added entry)
    newline: str  # the line ending the file uses


def read_layout(source: str) -> ParamsLayout | None:
    """Where ``PARAMS`` and each entry are, or None when there is no ``PARAMS`` (or the code has a
    syntax error). Raises ``ParamsEditError`` when ``PARAMS`` is there but cannot be edited."""
    try:
        return _locate(source)
    except _NoParamsError:
        return None


# -- editing ---------------------------------------------------------------------------------------


def edit_params(source: str, op: Operation) -> str:
    """``source`` with ``op`` applied to its ``PARAMS``; ``ParamsEditError`` says why it cannot be."""
    layout = _locate(source)
    if isinstance(op, AddParam):
        edits, expected = _add(source, layout, op)
    elif isinstance(op, RemoveParam):
        edits, expected = _remove(source, layout, op)
    elif isinstance(op, RenameParam):
        edits, expected = _rename(source, layout, op)
    elif isinstance(op, ChangeParam):
        edits, expected = _change(source, layout, op)
    else:
        raise ParamsEditError(f"unknown change {op!r}")
    if not edits:
        return source
    out = source
    for start, end, text in sorted(edits, reverse=True):
        out = out[:start] + text + out[end:]
    _verify(out, expected)
    return out


def format_value(default: Any, minimum: float | None = None, maximum: float | None = None) -> str:
    """How a parameter's value is written in ``PARAMS`` (see the module text).

    ``ParamsEditError`` for a value that cannot be a parameter (not a number, text or True/False, a number
    that is not finite, limits on a value that is not a number, one limit alone, a default outside them).
    """
    if (minimum is None) != (maximum is None):
        raise ParamsEditError("limits need both a minimum and a maximum")
    if isinstance(default, bool):
        _no_limits(minimum, "True/False")
        return "True" if default else "False"
    if isinstance(default, str):
        _no_limits(minimum, "text")
        return json.dumps(default, ensure_ascii=False)
    if not _is_number(default):
        raise ParamsEditError(f"{default!r} cannot be a parameter (use a number, text or True/False)")
    if minimum is None:
        return _number(default)
    assert maximum is not None
    for bound in (minimum, maximum):
        if not _is_number(bound):
            raise ParamsEditError(f"the limit {bound!r} is not a number")
    if not minimum <= default <= maximum:
        raise ParamsEditError(f"the default {default!r} is not from {minimum!r} to {maximum!r}")
    return "(" + ", ".join(_numbers([default, minimum, maximum])) + ")"


def _no_limits(minimum: float | None, what: str) -> None:
    if minimum is not None:
        raise ParamsEditError(f"limits only fit a number, not {what}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value: float) -> str:
    return repr(value)  # 30.0, 0.25, 6


def _numbers(values: list[float], reuse: list[str | None] | None = None) -> list[str]:
    """The numbers of a tuple written alike: all whole numbers, or all with a decimal point."""
    whole = all(isinstance(v, int) for v in values)
    out = []
    for i, v in enumerate(values):
        if reuse is not None and reuse[i] is not None:
            out.append(reuse[i])
        else:
            out.append(repr(v) if whole else repr(float(v)))
    return out


# -- locating --------------------------------------------------------------------------------------


def _locate(source: str) -> ParamsLayout:
    bom = 1 if source.startswith(BOM) else 0
    text = source[bom:]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        raise _NoParamsError(
            f"the code has a syntax error ({getattr(exc, 'msg', exc)}): fix it first"
        ) from None
    found = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(t, ast.Name) and t.id == "PARAMS"
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    if not found:
        raise _NoParamsError("the code has no PARAMS = {...}")
    node = found[-1]  # the last assignment wins, as when the code runs
    value = node.value
    if not isinstance(value, ast.Dict):
        raise ParamsEditError('PARAMS is not a plain {...} dict (it can be edited only as {"name": default})')
    if any(key is None for key in value.keys):
        raise ParamsEditError("PARAMS uses ** to include other values: edit it by hand")
    where = _Text(text)

    def at(lineno: int | None, col: int | None) -> int:
        assert lineno is not None and col is not None
        return where.offset(lineno, col)

    keys: list[ast.Constant] = []
    for key, val in zip(value.keys, value.values, strict=True):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            raise ParamsEditError("a key of PARAMS is not plain text: edit it by hand")
        try:
            ast.literal_eval(val)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            raise ParamsEditError(
                f"the value of {key.value!r} in PARAMS is not a plain value (numbers, text, True/False): "
                "edit it by hand"
            ) from None
        keys.append(key)
    dict_start = at(value.lineno, value.col_offset)
    dict_end = at(value.end_lineno, value.end_col_offset)
    nodes = list(zip(keys, value.values, strict=True))
    entries: list[ParamEntry] = []
    for i, (key, val) in enumerate(nodes):
        limit = at(nodes[i + 1][0].lineno, nodes[i + 1][0].col_offset) if i + 1 < len(nodes) else dict_end - 1
        entries.append(_entry(where, key, val, limit, at))
    multiline = _NEWLINE.search(text, dict_start, dict_end) is not None
    trailing = bool(entries) and entries[-1].comma is not None
    newline = _newline_of(text, dict_start)
    layout = ParamsLayout(
        start=at(node.lineno, node.col_offset) + bom,
        end=at(node.end_lineno, node.end_col_offset) + bom,
        dict_start=dict_start + bom,
        dict_end=dict_end + bom,
        entries=tuple(_shift(e, bom) for e in entries),
        multiline=multiline,
        trailing_comma=trailing,
        indent=_indent_unit(text),
        newline=newline,
    )
    return layout


def _shift(entry: ParamEntry, by: int) -> ParamEntry:
    if not by:
        return entry

    def move(x: int | None) -> int | None:
        return None if x is None else x + by

    return ParamEntry(
        entry.key,
        entry.key_start + by,
        entry.key_end + by,
        entry.value_start + by,
        entry.value_end + by,
        entry.value_text,
        move(entry.comma),
        entry.comment,
        move(entry.comment_start),
        move(entry.comment_end),
        entry.end + by,
        entry.own_line,
    )


def _entry(where: _Text, key: ast.Constant, val: ast.expr, limit: int, at) -> ParamEntry:
    text = where.text
    key_start, key_end = at(key.lineno, key.col_offset), at(key.end_lineno, key.end_col_offset)
    value_start, value_end = at(val.lineno, val.col_offset), at(val.end_lineno, val.end_col_offset)
    # after the value: closing parentheses of a parenthesised value, then the comma, then a comment
    i, closed, comma = value_end, value_end, None
    comment_start = comment_end = None
    while i < limit:
        c = text[i]
        if c in " \t\f\r\n\\":
            i += 1
        elif c == ")":
            i += 1
            closed = i
        elif c == "#":
            end = where.line_end(i)
            if comment_start is None and where.line_start(i) <= value_end:
                comment_start, comment_end = i, end
            elif comment_start is None and comma is None:
                pass  # a comment on a line of its own between the value and its comma
            i = end
        elif c == ",":
            comma = i
            i += 1
            break
        else:
            break
    end = (comma + 1) if comma is not None else closed
    if comment_start is None:
        j = end
        while j < len(text) and text[j] in " \t\f":
            j += 1
        if j < len(text) and text[j] == "#":
            comment_start, comment_end = j, where.line_end(j)
    tail = comment_end if comment_end is not None and comment_end >= end else end
    before = text[where.line_start(key_start) : key_start]
    after = text[tail : where.line_end(tail)]
    own_line = not before.strip(" \t\f") and not after.strip(" \t\f")
    comment = text[comment_start + 1 : comment_end].strip() if comment_start is not None else ""
    return ParamEntry(
        key=key.value,
        key_start=key_start,
        key_end=key_end,
        value_start=value_start,
        value_end=value_end,
        value_text=text[value_start:value_end],
        comma=comma,
        comment=comment,
        comment_start=comment_start,
        comment_end=comment_end,
        end=end if comment_start is None else max(end, closed),
        own_line=own_line,
    )


def _newline_of(text: str, near: int) -> str:
    match = _NEWLINE.search(text, near) or _NEWLINE.search(text)
    return match.group() if match else "\n"


def _indent_unit(text: str) -> str:
    for line in _NEWLINE.split(text):
        if line.strip() and line[0] in " \t":
            lead = line[: len(line) - len(line.lstrip(" \t"))]
            return "\t" if lead.startswith("\t") else lead
    return "    "


# -- the operations --------------------------------------------------------------------------------

Edit = tuple[int, int, str]  # (start, end, replacement)
Items = list[tuple[str, Any]]  # what PARAMS must hold afterwards


def _items(source: str, layout: ParamsLayout) -> Items:
    return list(ast.literal_eval(source[layout.dict_start : layout.dict_end]).items())


def _find(layout: ParamsLayout, name: str) -> ParamEntry:
    matches = [e for e in layout.entries if e.key == name]
    if not matches:
        raise ParamsEditError(f"PARAMS has no parameter {name!r}")
    if len(matches) > 1:
        raise ParamsEditError(f"PARAMS lists {name!r} more than once: edit it by hand")
    return matches[0]


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not name.isidentifier():
        raise ParamsEditError(f"{name!r} is not a valid parameter name (use letters, digits and _)")


def _add(source: str, layout: ParamsLayout, op: AddParam) -> tuple[list[Edit], Items]:
    _check_name(op.name)
    if any(e.key == op.name for e in layout.entries):
        raise ParamsEditError(f"PARAMS already has a parameter {op.name!r}")
    value = format_value(op.default, op.minimum, op.maximum)
    entry = f"{json.dumps(op.name)}: {value}"
    expected = [*_items(source, layout), (op.name, ast.literal_eval(value))]
    nl = layout.newline
    open_, close = layout.dict_start, layout.dict_end - 1
    if not layout.entries:
        if not layout.multiline:
            return [(open_ + 1, close, entry)], expected
        where = _Text(source)
        line = where.line_start(close)
        lead = source[line:close]
        if lead.strip(" \t\f"):  # something else on the line of the closing brace: put it inline
            return [(close, close, entry)], expected
        return [(line, line, f"{lead}{layout.indent}{entry},{nl}")], expected
    last = layout.entries[-1]
    edits: list[Edit] = []
    if last.own_line and layout.multiline:
        where = _Text(source)
        lead = source[where.line_start(last.key_start) : last.key_start]
        at = where.after_line(last.end if last.comment_end is None else last.comment_end)
        eol = source[where.line_end(last.end) : at] or nl
        if last.comma is None:
            edits.append((_closed(source, last), _closed(source, last), ","))
            new = f"{lead}{entry}{eol}"
        else:
            new = f"{lead}{entry},{eol}"
        edits.append((at, at, new))
        return edits, expected
    if last.comma is None:
        at = _closed(source, last)
        return [(at, at, f", {entry}")], expected
    return [(last.comma + 1, last.comma + 1, f" {entry},")], expected


def _closed(source: str, entry: ParamEntry) -> int:
    """The offset just after an entry's value, closing parentheses included."""
    i = entry.value_end
    end = i
    limit = entry.comma if entry.comma is not None else len(source)
    while i < limit and source[i] in " \t\f\r\n)\\":
        i += 1
        if source[i - 1] == ")":
            end = i
    return end


def _remove(source: str, layout: ParamsLayout, op: RemoveParam) -> tuple[list[Edit], Items]:
    target = _find(layout, op.name)
    expected = [(k, v) for k, v in _items(source, layout) if k != op.name]
    entries = list(layout.entries)
    index = entries.index(target)
    last = index == len(entries) - 1
    previous = entries[index - 1] if index else None
    tail = target.comment_end if target.comment_end is not None else target.end
    where = _Text(source)
    if target.own_line:
        edits = [(where.line_start(target.key_start), where.after_line(tail), "")]
        if last and target.comma is None and previous is not None and previous.comma is not None:
            edits.append((previous.comma, previous.comma + 1, ""))  # keep the file's no-trailing-comma style
        return edits, expected
    if len(entries) == 1:
        if not layout.multiline:
            return [(layout.dict_start + 1, layout.dict_end - 1, "")], expected
        return [(target.key_start, tail, "")], expected
    if not last:
        end = tail
        while end < len(source) and source[end] in " \t\f":
            end += 1
        return [(target.key_start, end, "")], expected
    assert previous is not None
    return [(_closed(source, previous), _closed(source, target), "")], expected


def _rename(source: str, layout: ParamsLayout, op: RenameParam) -> tuple[list[Edit], Items]:
    target = _find(layout, op.old)
    _check_name(op.new)
    if op.new == op.old:
        return [], _items(source, layout)
    if any(e.key == op.new for e in layout.entries):
        raise ParamsEditError(f"PARAMS already has a parameter {op.new!r}")
    quote = "'" if source[target.key_start] == "'" else '"'
    expected = [(op.new if k == op.old else k, v) for k, v in _items(source, layout)]
    return [(target.key_start, target.key_end, f"{quote}{op.new}{quote}")], expected


def _change(source: str, layout: ParamsLayout, op: ChangeParam) -> tuple[list[Edit], Items]:
    target = _find(layout, op.name)
    shown = ast.literal_eval(target.value_text) if _literal(target.value_text) else None
    current = _current(source, target, shown)
    old_default, old_min, old_max = current
    default = old_default if op.default is UNCHANGED else op.default
    minimum = old_min if op.minimum is UNCHANGED else op.minimum
    maximum = old_max if op.maximum is UNCHANGED else op.maximum
    if not _is_number(default):
        explicit = op.minimum is not UNCHANGED or op.maximum is not UNCHANGED
        if not explicit:
            minimum = maximum = None  # a type with no limits: they go
        elif minimum is not None or maximum is not None:
            raise ParamsEditError("limits only fit a number")
    elif (minimum is None) != (maximum is None):
        raise ParamsEditError("limits need both a minimum and a maximum")
    value = format_value(default, minimum, maximum)
    if minimum is not None and _is_number(default):
        value = _keep_texts(source, target, shown, default, minimum, maximum) or value
    elif _is_number(default) and _is_number(shown) and type(shown) is type(default) and shown == default:
        value = target.value_text  # the same number: keep the way it was written
    if value == target.value_text:
        return [], _items(source, layout)
    expected = [(k, ast.literal_eval(value) if k == op.name else v) for k, v in _items(source, layout)]
    return [(target.value_start, target.value_end, value)], expected


def _literal(text: str) -> bool:
    try:
        ast.literal_eval(text)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return True


def _current(source: str, entry: ParamEntry, shown: Any) -> tuple[Any, Any, Any]:
    """A parameter's (default, minimum, maximum) as written; ``ParamsEditError`` for an odd value."""
    if isinstance(shown, tuple):
        if len(shown) == 3 and all(_is_number(v) for v in shown):
            return shown
        raise ParamsEditError(f"the value of {entry.key!r} is not a parameter value: edit it by hand")
    if isinstance(shown, (bool, str)) or _is_number(shown):
        return shown, None, None
    raise ParamsEditError(f"the value of {entry.key!r} is not a parameter value: edit it by hand")


def _keep_texts(
    source: str, entry: ParamEntry, shown: Any, default: float, minimum: float, maximum: float
) -> str | None:
    """A new ``(default, minimum, maximum)`` that reuses the text of the numbers that did not change."""
    new = [default, minimum, maximum]
    if isinstance(shown, tuple):
        try:
            tree = ast.parse(entry.value_text.strip(), mode="eval").body
        except SyntaxError:
            return None
        if not isinstance(tree, ast.Tuple) or len(tree.elts) != 3:
            return None
        texts: list[str | None] = [ast.get_source_segment(entry.value_text.strip(), e) for e in tree.elts]
        old = list(shown)
    elif isinstance(shown, (int, float)) and not isinstance(shown, bool):
        texts, old = [entry.value_text, None, None], [shown, None, None]
    else:
        return None
    whole_old = all(isinstance(v, int) for v in old if v is not None)
    whole_new = all(isinstance(v, int) for v in new)
    reuse: list[str | None] = [
        texts[i] if (old[i] is not None and old[i] == new[i] and whole_old == whole_new) else None
        for i in range(3)
    ]
    return "(" + ", ".join(_numbers(new, reuse)) + ")"


def _verify(source: str, expected: Items) -> None:
    """The edit must give back exactly the parameters that were meant; otherwise nothing is changed."""
    try:
        layout = _locate(source)
        got = _items(source, layout)
    except (ParamsEditError, ValueError, SyntaxError):
        got = None
    if got != expected:
        raise ParamsEditError("this PARAMS is written in a way that cannot be edited safely: edit it by hand")
