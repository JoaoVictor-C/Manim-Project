"""Part layers: resolving ``{tex, occurrence}`` keys to spans of a root's TeX (ADR 0012).

A part is the ``occurrence``-th match of ``tex`` inside its parent's text: the
root's whole TeX, or the parent part's span. Each part resolves to **one exact
span**, which the adapter wraps in its own ``\\special{dvisvgm:raw <g id=...>}``
group (``mark``). Manim's ``substrings_to_isolate`` is not used: it marks every
occurrence, so adding a part could move another one (B28).

Not every span can be marked. A marker right after ``^`` or ``_`` breaks LaTeX,
so a one-token span there is braced (``a^2`` -> ``a^{2}``, identical output)
and anything longer is refused, as are spans that cut a control word, start or
end on a script operator, have unbalanced braces, or cross another part.
Unresolvable parts are *orphaned*: kept, drawn nowhere, never retargeted.

Pure: no Manim, no Qt.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .schema import Layer, Project, Spec

SPANS_PARAM = "part_spans"  # build parameter holding [[start, end, braced], ...] (adapter)
_OPEN = "\\special{{dvisvgm:raw <g id='{}'>}}"
_CLOSE = "\\special{dvisvgm:raw </g>}"
_SPLIT_AT = frozenset("=+-<>")


def marker_id(index: int) -> str:
    """The SVG group id of the ``index``-th span (in ``Resolution.order``)."""
    return f"msp{index}"


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    braced: bool = False  # wrapped in {...}: a one-token script after ^ or _

    def contains(self, other: Span) -> bool:
        return self.start <= other.start and other.end <= self.end

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class Resolution:
    """Where every part of one root sits in the root's TeX."""

    text: str
    spans: dict[str, Span] = field(default_factory=dict)  # resolved part id -> span
    orphans: dict[str, str] = field(default_factory=dict)  # part id -> why it does not resolve
    order: tuple[str, ...] = ()  # marker index -> part id (spans by start, outer first)

    def marker_spans(self) -> list[list[int | bool]]:
        """The build parameter: ``[start, end, braced]`` per marker, in marker order."""
        return [[self.spans[i].start, self.spans[i].end, self.spans[i].braced] for i in self.order]


# -- finding spans ----------------------------------------------------------------


def find(text: str, key: str, occurrence: int, lo: int = 0, hi: int | None = None) -> int | None:
    """Start of the ``occurrence``-th non-overlapping match of ``key`` in ``text[lo:hi]``."""
    hi = len(text) if hi is None else hi
    if not key:
        return None
    position, seen = lo, 0
    while True:
        index = text.find(key, position, hi)
        if index < 0:
            return None
        if seen == occurrence:
            return index
        seen += 1
        position = index + len(key)


def count(text: str, key: str, lo: int = 0, hi: int | None = None) -> int:
    hi = len(text) if hi is None else hi
    n, position = 0, lo
    while key:
        index = text.find(key, position, hi)
        if index < 0:
            break
        n += 1
        position = index + len(key)
    return n


def check_span(text: str, start: int, end: int) -> Span | str:
    """The markable span ``text[start:end]``, or why it cannot be marked."""
    piece = text[start:end]
    if not piece.strip():
        return "the part is empty"
    if _unescaped_at(text, start, "^_") or _unescaped_at(text, end - 1, "^_"):
        return "the part starts or ends on ^ or _"
    if _escaped_or_in_command(text, start) or _escaped_or_in_command(text, end):
        return "the part cuts a command such as \\pi"
    if not _balanced(piece):
        return "the part has unbalanced braces"
    before = start - 1
    while before >= 0 and text[before] == " ":
        before -= 1
    if before >= 0 and _unescaped_at(text, before, "^_"):
        if not _one_token(piece.strip()):
            return "the part starts inside a superscript or subscript"
        return Span(start, end, braced=True)
    return Span(start, end)


def resolve(project: Project, root_id: str) -> Resolution:
    """Resolve every part under ``root_id`` (parents before children, siblings in list order)."""
    root = project.layer(root_id)
    text = str(root.spec.params.get("text", "")) if root.spec else ""
    spans: dict[str, Span] = {}
    orphans: dict[str, str] = {}
    whole = Span(0, len(text))
    for layer in project.descendants(root_id):
        parent_span = whole if layer.parent_id == root_id else spans.get(layer.parent_id)
        if parent_span is None:
            orphans[layer.id] = "its parent part does not resolve"
            continue
        result = _resolve_one(text, layer, parent_span)
        if not isinstance(result, Span):
            orphans[layer.id] = result
            continue
        ancestors = {a.id for a in project.ancestors(layer.id)}
        # Only a part's ancestors may share its glyphs: anything else would draw them twice.
        clash = next((o for o, s in spans.items() if o not in ancestors and s.overlaps(result)), None)
        if clash is not None:
            same = spans[clash] == result
            orphans[layer.id] = f"it {'matches the same text as' if same else 'overlaps'} part {clash!r}"
            continue
        spans[layer.id] = result
    order = tuple(sorted(spans, key=lambda i: (spans[i].start, -spans[i].end)))
    return Resolution(text, spans, orphans, order)


def _resolve_one(text: str, layer: Layer, parent: Span) -> Span | str:
    key = layer.part
    start = find(text, key.tex, key.occurrence, parent.start, parent.end)
    if start is None:
        n = count(text, key.tex, parent.start, parent.end)
        if n == 0:
            return f"{key.tex!r} is not in the text"
        return f"{key.tex!r} occurs {n} time{'s' * (n != 1)}, not {key.occurrence + 1}"
    return check_span(text, start, start + len(key.tex))


def build_spec(project: Project, root_id: str, resolution: Resolution | None = None) -> Spec:
    """The spec the root is built from: its own, plus its parts' marker spans if any."""
    root = project.layer(root_id)
    if not project.children(root_id):
        return root.spec
    resolution = resolution or resolve(project, root_id)
    if not resolution.order:
        return root.spec
    return root.spec.model_copy(
        update={"params": {**root.spec.params, SPANS_PARAM: resolution.marker_spans()}}
    )


# -- marking -------------------------------------------------------------------------


def mark(text: str, spans: Iterable[Iterable]) -> str:
    """``text`` with marker groups around ``spans`` (``[start, end, braced]``, marker order)."""
    events = []
    for index, (start, end, braced) in enumerate(spans):
        opening = ("{" if braced else "") + _OPEN.format(marker_id(index))
        closing = _CLOSE + ("}" if braced else "")
        # At one position: closes before opens; inner closes first, outer opens first.
        events.append((end, 0, -start, closing))
        events.append((start, 1, -end, opening))
    events.sort(key=lambda e: e[:3])
    out, last = [], 0
    for position, _, _, insert in events:
        out.append(text[last:position])
        out.append(insert)
        last = position
    out.append(text[last:])
    return "".join(out)


# -- splitting into terms ---------------------------------------------------------------


def split_terms(text: str) -> list[tuple[str, int]]:
    """Top-level terms between ``= + - < >`` as ``(tex, occurrence)`` keys that resolve.

    Operators inside braces or ``\\left ... \\right`` do not split. Terms that
    could not be marked (e.g. inside a script) are skipped.
    """
    terms, depth, start, i = [], 0, 0, 0
    while i < len(text):
        if text[i] == "\\":
            word = re.match(r"\\([A-Za-z]+|.)", text[i:])
            name = word.group(1) if word else ""
            depth += 1 if name == "left" else -1 if name == "right" else 0
            i += len(word.group(0)) if word else 1
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        elif depth == 0 and text[i] in _SPLIT_AT:
            terms.append((start, i))
            start = i + 1
        i += 1
    terms.append((start, len(text)))
    keys = []
    for lo, hi in terms:
        piece = text[lo:hi]
        first = lo + len(piece) - len(piece.lstrip())
        last = hi - (len(piece) - len(piece.rstrip()))
        if first >= last:
            continue
        tex = text[first:last]
        occurrence = count(text, tex, 0, first)
        if find(text, tex, occurrence) != first or not isinstance(check_span(text, first, last), Span):
            continue
        keys.append((tex, occurrence))
    return keys


# -- helpers ---------------------------------------------------------------------------


def _unescaped_at(text: str, index: int, chars: str) -> bool:
    return 0 <= index < len(text) and text[index] in chars and not _escaped(text, index)


def _escaped(text: str, index: int) -> bool:
    slashes = 0
    while index - slashes - 1 >= 0 and text[index - slashes - 1] == "\\":
        slashes += 1
    return slashes % 2 == 1


def _escaped_or_in_command(text: str, cut: int) -> bool:
    """Does a marker at ``cut`` split ``\\x`` or a control word like ``\\alpha``?"""
    if cut <= 0 or cut >= len(text):
        return False
    if text[cut - 1] == "\\" and not _escaped(text, cut - 1):
        return True
    if not (text[cut - 1].isalpha() and text[cut].isalpha()):
        return False
    j = cut - 1
    while j >= 0 and text[j].isalpha():
        j -= 1
    return j >= 0 and text[j] == "\\" and not _escaped(text, j)


def _balanced(piece: str) -> bool:
    depth = 0
    for i, ch in enumerate(piece):
        if ch in "{}" and _escaped(piece, i):
            continue
        depth += 1 if ch == "{" else -1 if ch == "}" else 0
        if depth < 0:
            return False
    return depth == 0


def _one_token(piece: str) -> bool:
    """A single character, a control sequence, or one braced group."""
    if len(piece) == 1:
        return piece not in "{}\\"
    if re.fullmatch(r"\\(?:[A-Za-z]+|.)", piece):
        return True
    return (
        piece.startswith("{") and piece.endswith("}") and _balanced(piece[1:-1]) and _group_spans_all(piece)
    )


def _group_spans_all(piece: str) -> bool:
    depth = 0
    for i, ch in enumerate(piece):
        if ch in "{}" and _escaped(piece, i):
            continue
        depth += 1 if ch == "{" else -1 if ch == "}" else 0
        if depth == 0 and i < len(piece) - 1:
            return False
    return True


# -- noticing retargeted parts after a text edit ------------------------------------------------


def retargeted(old: Project, new: Project) -> dict[str, str]:
    """Parts whose match may have moved because their object's text changed.

    A part follows its key (the n-th match), so an edit that adds, removes or
    reorders matches can point it at another place. Flags parts that stopped
    resolving, whose match count changed, or whose nearest character on the left
    changed (a swap such as ``b + b = c`` -> ``c + b = b``). A heuristic: text
    appended after a part does not trip it, a reworded left neighbour does.
    """
    old_ids = {layer.id for layer in old.layers}
    out: dict[str, str] = {}
    for root in new.roots():
        if root.id not in old_ids or not new.children(root.id):
            continue
        before_root = old.layer(root.id)
        if before_root.spec is None or before_root.spec.params.get("text") == root.spec.params.get("text"):
            continue
        before, after = resolve(old, root.id), resolve(new, root.id)
        for part in new.descendants(root.id):
            if part.id not in before.spans:
                continue
            if part.id in after.orphans:
                out[part.id] = f"no longer found ({after.orphans[part.id]})"
                continue
            was, now = before.spans[part.id], after.spans[part.id]
            parent_was = before.spans.get(part.parent_id, Span(0, len(before.text)))
            parent_now = after.spans.get(part.parent_id, Span(0, len(after.text)))
            tex = part.part.tex
            moved = count(before.text, tex, parent_was.start, parent_was.end) != count(
                after.text, tex, parent_now.start, parent_now.end
            ) or _context(before.text, was) != _context(after.text, now)
            if moved:
                out[part.id] = "may now match another place"
    return out


def _context(text: str, span: Span) -> str:
    """The nearest non-space character before the span ("" at the start)."""
    before = text[: span.start].rstrip()
    return before[-1:] if before else ""
