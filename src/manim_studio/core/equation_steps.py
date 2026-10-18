"""Equation steps (P11, ADR 0054): algebra typed one line per step, animated as morphs.

The user types the steps of a derivation, one LaTeX equation per line, and Studio makes one
MathTex layer per step with a morph from each step to the next (``edits.add_equation_steps``).
This module is the pure part, working on LaTeX strings only (no Manim, no Qt):

* ``parse_steps``: the lines of the text box as steps;
* ``derive``: the next line from a line, by an operation on both sides of ``LHS = RHS`` (add,
  subtract, multiply or divide by a term; square, square root, reciprocal, ``\\ln``, ``e^x``;
  substitute a value for a symbol);
* ``plan_transition``: what to do between two steps - which pieces both share (they move to
  their new places), which are new in the second (they can be coloured, as part layers that
  ``parts`` can resolve), and which morph kind fits.

A small tokenizer reads LaTeX into a tree of nodes: single tokens (a letter, a number, a
command such as ``\\alpha`` or ``\\times``, an operator), groups (``{...}``, ``(...)``,
``[...]``, ``\\left( ... \\right)``) and commands with arguments (``\\frac{a}{b}``,
``\\sqrt{x}``, ``\\text{...}``). Pieces for matching are the tree flattened in reading order;
the brackets and command heads are *structural* pieces that never stand out on their own.

Designed independently from the problem and Studio's own machinery; no third-party
algebra-animation library's code or documentation was consulted.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from . import parts

MAX_STEPS = 40
MAX_LINE = 400  # characters in one line
BASE_COLOUR = "#FFFFFF"  # content: Manim's default fill for text
HIGHLIGHT_COLOUR = "#FFFF00"  # content: Manim's YELLOW, the colour of its indications
MATCHING = "TransformMatchingTex"  # shared pieces move, the rest fades (ADR 0020)
REPLACING = "Transform"  # Studio's Transform is Manim's ReplacementTransform (ADR 0005)


class StepsError(ValueError):
    """A step or an operation that cannot be read or applied, with the reason."""


# -- the steps ------------------------------------------------------------------------------------


def parse_steps(text: str) -> list[str]:
    """One equation per non-empty line, in order; lines starting with ``%`` are comments."""
    steps = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("%"):
            continue
        if len(line) > MAX_LINE:
            raise StepsError(f"line {number} has {len(line)} characters: at most {MAX_LINE}")
        steps.append(line)
    if len(steps) > MAX_STEPS:
        raise StepsError(f"{len(steps)} steps: at most {MAX_STEPS}")
    return steps


def line_problem(tex: str) -> str | None:
    """Why ``tex`` cannot be read as one equation (unbalanced braces, ``\\left`` without
    ``\\right``), or None. LaTeX itself may still refuse it; this is the quick check."""
    try:
        parse(tex)
    except StepsError as error:
        return str(error)
    return None


# -- tokens ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    kind: str  # command, letter, number, open, close, op, space, other
    text: str
    start: int
    end: int


_OPERATOR_CHARS = frozenset("+-=<>^_*/!,|':;&")
_COMMAND = re.compile(r"\\(?:[A-Za-z]+|.)?", re.DOTALL)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SPACE = re.compile(r"\s+")


def tokenize(tex: str) -> list[Token]:
    """``tex`` as tokens: ``\\alpha`` and ``\\,`` are one command each, ``12.5`` one number,
    every letter its own token (``xy`` is x times y), and runs of spaces one token."""
    tokens, i = [], 0
    while i < len(tex):
        c = tex[i]
        if c == "\\":
            match = _COMMAND.match(tex, i)
            kind, end = "command", match.end()
        elif c.isspace():
            kind, end = "space", _SPACE.match(tex, i).end()
        elif c.isdigit():
            kind, end = "number", _NUMBER.match(tex, i).end()
        elif c.isalpha():
            kind, end = "letter", i + 1
        elif c in "{([":
            kind, end = "open", i + 1
        elif c in "})]":
            kind, end = "close", i + 1
        elif c in _OPERATOR_CHARS:
            kind, end = "op", i + 1
        else:
            kind, end = "other", i + 1
        tokens.append(Token(kind, tex[i:end], i, end))
        i = end
    return tokens


# -- the tree -------------------------------------------------------------------------------------

ARGUMENTS = {  # commands that take arguments, and how many
    **dict.fromkeys(("frac", "dfrac", "tfrac", "cfrac", "binom", "dbinom", "tbinom"), 2),
    **dict.fromkeys(
        (
            "sqrt",
            "text",
            "textrm",
            "textbf",
            "textit",
            "mbox",
            "operatorname",
            "mathrm",
            "mathbf",
            "mathit",
            "mathsf",
            "mathtt",
            "mathcal",
            "mathbb",
            "mathfrak",
            "boldsymbol",
            "overline",
            "underline",
            "hat",
            "bar",
            "vec",
            "tilde",
            "dot",
            "ddot",
            "widehat",
            "widetilde",
            "overrightarrow",
        ),
        1,
    ),
}
OPAQUE = frozenset({"text", "textrm", "textbf", "textit", "mbox", "operatorname", "mathrm"})  # words
TALL = frozenset({"frac", "dfrac", "cfrac", "binom", "dbinom", "sum", "prod", "int", "oint"})
OPERATOR_COMMANDS = frozenset(
    {"cdot", "times", "div", "pm", "mp", "ast", "star", "circ", "le", "ge", "leq", "geq", "neq", "approx"}
)
_PLUS_MINUS = frozenset({"+", "-", "\\pm", "\\mp"})


@dataclass
class Node:
    """A token (``kind`` ``leaf``), a group (its ``opener`` and ``closer``: ``{``/``}``,
    ``(``/``)``, ``\\left(``/``\\right)``) or a command with arguments (``head``)."""

    kind: str  # leaf, group, command
    start: int
    end: int
    token: Token | None = None  # leaf
    opener: str = ""  # group
    closer: str = ""
    open_end: int = 0  # where the group's opener ends
    close_start: int = 0  # where its closer starts
    head: Token | None = None  # command
    children: list[Node] = field(default_factory=list)  # a group's nodes; a command's arguments

    @property
    def name(self) -> str:
        """A command's or a leaf command's name without the backslash."""
        token = self.head if self.kind == "command" else self.token
        return token.text[1:] if token is not None and token.kind == "command" else ""

    @property
    def is_operator(self) -> bool:
        if self.kind != "leaf":
            return False
        token = self.token
        return token.kind == "op" or (
            token.kind == "command" and self.name in OPERATOR_COMMANDS | {"pm", "mp"}
        )

    def text(self, tex: str) -> str:
        return tex[self.start : self.end]


def parse(tex: str) -> list[Node]:
    """The top-level nodes of ``tex`` (spaces dropped). Raises ``StepsError`` when braces or
    ``\\left``/``\\right`` do not pair up; unpaired ``(`` ``)`` ``[`` ``]`` are plain tokens
    (``[0, 1)`` is an interval)."""
    tokens = tokenize(tex)
    pairs = _bracket_pairs(tokens)
    nodes, i = _sequence(tex, tokens, pairs, 0, None)
    if i < len(tokens):  # a closer nobody opened
        raise StepsError(f"unbalanced braces: {tokens[i].text!r} at character {tokens[i].start + 1}")
    return nodes


def _bracket_pairs(tokens: list[Token]) -> dict[int, int]:
    """Token index of each ``(`` or ``[`` -> its partner, within one brace level."""
    pairs: dict[int, int] = {}
    stacks: list[list[int]] = [[]]
    for i, token in enumerate(tokens):
        if token.text == "{":
            stacks.append([])
        elif token.text == "}":
            if len(stacks) > 1:
                stacks.pop()
        elif token.text in "([" and token.kind == "open" and not _after_delimiter_command(tokens, i):
            stacks[-1].append(i)
        elif token.text in ")]" and token.kind == "close" and not _after_delimiter_command(tokens, i):
            stack = stacks[-1]
            want = "(" if token.text == ")" else "["
            if stack and tokens[stack[-1]].text == want:
                pairs[stack.pop()] = i
    return pairs


def _after_delimiter_command(tokens: list[Token], i: int) -> bool:
    """Is token ``i`` the delimiter of a ``\\left``, ``\\right``, ``\\big``...?"""
    j = i - 1
    while j >= 0 and tokens[j].kind == "space":
        j -= 1
    return j >= 0 and tokens[j].kind == "command" and tokens[j].text[1:] in _SIZERS


_SIZERS = frozenset({"left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "middle"})


def _sequence(
    tex: str, tokens: list[Token], pairs: dict[int, int], i: int, stop: str | None, until: int | None = None
) -> tuple[list[Node], int]:
    """Nodes from token ``i`` up to the closer ``stop`` (``}``, ``\\right``) or token ``until``."""
    nodes: list[Node] = []
    while i < len(tokens):
        if until is not None and i >= until:
            return nodes, i
        token = tokens[i]
        if token.kind == "space":
            i += 1
            continue
        if token.text == "}" or (token.kind == "command" and token.text == "\\right"):
            if stop == token.text:
                return nodes, i
            what = "a '}'" if token.text == "}" else "a \\right"
            raise StepsError(f"unbalanced braces: {what} at character {token.start + 1} closes nothing")
        node, i = _node(tex, tokens, pairs, i)
        nodes.append(node)
    if stop is not None:
        missing = "'}'" if stop == "}" else "\\right"
        raise StepsError(f"unbalanced braces: a {missing} is missing")
    return nodes, i


def _node(tex: str, tokens: list[Token], pairs: dict[int, int], i: int) -> tuple[Node, int]:
    token = tokens[i]
    if token.text == "{":
        children, j = _sequence(tex, tokens, pairs, i + 1, "}")
        close = tokens[j]
        return Node(
            "group",
            token.start,
            close.end,
            opener="{",
            closer="}",
            open_end=token.end,
            close_start=close.start,
            children=children,
        ), j + 1
    if token.kind == "open" and i in pairs:
        j = pairs[i]
        children, _ = _sequence(tex, tokens, pairs, i + 1, None, until=j)
        close = tokens[j]
        return Node(
            "group",
            token.start,
            close.end,
            opener=token.text,
            closer=close.text,
            open_end=token.end,
            close_start=close.start,
            children=children,
        ), j + 1
    if token.kind == "command" and token.text == "\\left":
        delimiter, j = _delimiter(tokens, i + 1, "\\left")
        children, k = _sequence(tex, tokens, pairs, j, "\\right")
        closing, end = _delimiter(tokens, k + 1, "\\right")
        return Node(
            "group",
            token.start,
            tokens[end - 1].end,
            opener=tex[token.start : delimiter.end],
            closer=tex[tokens[k].start : closing.end],
            open_end=delimiter.end,
            close_start=tokens[k].start,
            children=children,
        ), end
    if token.kind == "command" and token.text[1:] in ARGUMENTS:
        args: list[Node] = []
        j = i + 1
        if token.text == "\\sqrt":  # an optional [n]: the root's degree
            k = _skip_spaces(tokens, j)
            if k < len(tokens) and tokens[k].text == "[" and k in pairs:
                arg, j = _node(tex, tokens, pairs, k)
                args.append(arg)
        for _ in range(ARGUMENTS[token.text[1:]]):
            k = _skip_spaces(tokens, j)
            if k >= len(tokens) or tokens[k].text in ("}", "\\right"):
                raise StepsError(f"{token.text} at character {token.start + 1} is missing an argument")
            arg, j = _node(tex, tokens, pairs, k)
            args.append(arg)
        return Node("command", token.start, args[-1].end, head=token, children=args), j
    return Node("leaf", token.start, token.end, token=token), i + 1


def _skip_spaces(tokens: list[Token], i: int) -> int:
    while i < len(tokens) and tokens[i].kind == "space":
        i += 1
    return i


def _delimiter(tokens: list[Token], i: int, after: str) -> tuple[Token, int]:
    i = _skip_spaces(tokens, i)
    if i >= len(tokens) or tokens[i].kind == "space":
        raise StepsError(f"{after} needs a delimiter such as ( or .")
    return tokens[i], i + 1


# -- atoms: a base with its scripts -------------------------------------------------------------


@dataclass
class Atom:
    base: Node
    scripts: list[tuple[str, Node]] = field(default_factory=list)  # ("^" or "_", argument)

    @property
    def start(self) -> int:
        return self.base.start

    @property
    def end(self) -> int:
        return self.scripts[-1][1].end if self.scripts else self.base.end

    def script(self, mark: str) -> Node | None:
        return next((arg for m, arg in self.scripts if m == mark), None)


def atoms(nodes: list[Node]) -> list[Atom]:
    """``nodes`` read as atoms: each base with the ``^``/``_`` scripts that follow it."""
    out: list[Atom] = []
    i = 0
    while i < len(nodes):
        node = nodes[i]
        mark = node.token.text if node.kind == "leaf" and node.token.text in ("^", "_") else None
        if mark and out and i + 1 < len(nodes) and not out[-1].base.is_operator:
            out[-1].scripts.append((mark, nodes[i + 1]))
            i += 2
            continue
        out.append(Atom(node))
        i += 1
    return out


def _is_atomic(nodes: list[Node]) -> bool:
    """One atom that is not an operator: ``x``, ``2``, ``x^2``, ``\\frac{a}{b}``, ``(a+b)``."""
    found = atoms(nodes)
    return len(found) == 1 and not found[0].base.is_operator


def _plain_base(node: Node) -> bool:
    """Can ``^2`` follow it as it is: a letter, a number, a symbol command, ``(...)``."""
    if node.kind == "leaf":
        return node.token.kind in ("letter", "number") or (
            node.token.kind == "command" and not node.is_operator
        )
    return node.kind == "group" and node.opener != "{"


def _is_power_base(nodes: list[Node]) -> bool:
    """One atom without a superscript whose base can carry one: ``x``, ``a_1``, ``(a+b)``."""
    found = atoms(nodes)
    return len(found) == 1 and found[0].script("^") is None and _plain_base(found[0].base)


def _signs(nodes: list[Node]) -> tuple[bool, bool]:
    """(a binary + or - at the top level, any + or - at the top level - a leading sign too)."""
    binary = anywhere = False
    previous: Node | None = None
    for node in nodes:
        if node.kind == "leaf" and node.token.text in _PLUS_MINUS:
            anywhere = True
            if previous is not None and not previous.is_operator:
                binary = True
        previous = node
    return binary, anywhere


def _tall(nodes: list[Node]) -> bool:
    return any(node.name in TALL or _tall(node.children) for node in nodes)


def _wrap(tex: str, nodes: list[Node]) -> str:
    """``tex`` in parentheses; ``\\left( ... \\right)`` around fractions and sums."""
    return f"\\left( {tex} \\right)" if _tall(nodes) else f"({tex})"


# -- operations -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Operation:
    name: str
    label: str  # how the dialog lists it
    term: str  # what the term field asks for ("" when the operation needs none)


OPERATIONS: dict[str, Operation] = {
    op.name: op
    for op in (
        Operation("add", "Add to both sides", "the term to add, e.g. 3"),
        Operation("subtract", "Subtract from both sides", "the term to subtract, e.g. 2x"),
        Operation("multiply", "Multiply both sides by", "the factor, e.g. 2"),
        Operation("divide", "Divide both sides by", "the divisor, e.g. a"),
        Operation("square", "Square both sides", ""),
        Operation("sqrt", "Square root of both sides", ""),
        Operation("reciprocal", "Reciprocal of both sides", ""),
        Operation("ln", "Natural log of both sides", ""),
        Operation("exp", "Exponential of both sides", ""),
        Operation("substitute", "Substitute", "symbol = value, e.g. L = a+b"),
    )
}


def split_equation(tex: str) -> tuple[str, str]:
    """The two sides of ``LHS = RHS``, split at the one ``=`` outside braces and brackets."""
    nodes = parse(tex)
    equals = [n for n in nodes if n.kind == "leaf" and n.token.text == "="]
    if not equals:
        raise StepsError("the line has no '=' at the top level: operations need an equation LHS = RHS")
    if len(equals) > 1:
        raise StepsError(
            f"the line has {len(equals)} '=' signs at the top level: operations need exactly one"
        )
    lhs, rhs = tex[: equals[0].start].strip(), tex[equals[0].end :].strip()
    if not lhs or not rhs:
        raise StepsError(f"the {'left' if not lhs else 'right'} side of '=' is empty")
    return lhs, rhs


def derive(line: str, operation: str, term: str = "") -> str:
    """The line ``operation`` makes from ``line`` (an equation ``LHS = RHS``)."""
    if operation not in OPERATIONS:
        raise StepsError(f"unknown operation {operation!r}; known: {', '.join(OPERATIONS)}")
    if operation == "substitute":
        return substitute(line, *_substitution(term))
    lhs, rhs = split_equation(line)
    term = term.strip()
    if OPERATIONS[operation].term:
        if not term:
            raise StepsError(f"type {OPERATIONS[operation].term.split(',')[0]}")
        term_nodes = parse(term)
        if any(n.kind == "leaf" and n.token.text == "=" for n in term_nodes):
            raise StepsError("the term cannot contain '='")
    else:
        term_nodes = []
    sides = [(side, parse(side)) for side in (lhs, rhs)]
    return " = ".join(_apply(operation, side, nodes, term, term_nodes) for side, nodes in sides)


def _apply(operation: str, side: str, nodes: list[Node], term: str, term_nodes: list[Node]) -> str:
    binary, _ = _signs(nodes)
    _, term_signed = _signs(term_nodes)
    if operation == "add":
        leading = (
            bool(term_nodes) and term_nodes[0].kind == "leaf" and term_nodes[0].token.text in _PLUS_MINUS
        )
        return f"{side} + {_wrap(term, term_nodes) if leading else term}"
    if operation == "subtract":
        return f"{side} - {_wrap(term, term_nodes) if term_signed else term}"
    if operation == "multiply":
        left = _wrap(side, nodes) if binary else side
        return f"{left} \\cdot {_wrap(term, term_nodes) if term_signed else term}"
    if operation == "divide":
        return f"\\frac{{{side}}}{{{term}}}"
    if operation == "square":
        return f"{side if _is_power_base(nodes) else _wrap(side, nodes)}^2"
    if operation == "sqrt":
        return f"\\sqrt{{{side}}}"
    if operation == "reciprocal":
        return f"\\frac{{1}}{{{side}}}"
    if operation == "ln":
        found = atoms(nodes)
        if (
            len(found) == 1
            and found[0].base.kind == "group"
            and found[0].base.opener != "{"
            and not found[0].scripts
        ):
            return f"\\ln{side}"  # already in brackets: \ln(a+b)
        if _is_power_base(nodes) and found[0].base.kind == "leaf":
            return f"\\ln {side}"
        return f"\\ln{_wrap(side, nodes)}"
    if operation == "exp":
        return f"e^{{{side}}}"
    raise AssertionError(operation)


def _substitution(term: str) -> tuple[str, str]:
    """``symbol = value`` (or ``symbol := value``) as its two halves."""
    match = re.fullmatch(r"\s*(.+?)\s*:?=\s*(.+?)\s*", term or "", re.DOTALL)
    if match is None:
        raise StepsError("type the substitution as symbol = value, e.g. L = a+b")
    return match.group(1), match.group(2)


def substitute(line: str, symbol: str, value: str) -> str:
    """``line`` with every ``symbol`` (a whole token: not the x in ``\\exp``, not inside
    ``\\text{...}``) replaced by ``value``, in parentheses where it needs them."""
    target = _symbol(symbol)
    value_nodes = parse(value)
    if not value_nodes:
        raise StepsError("type the value to put in place of the symbol")
    nodes = parse(line)
    replacements: list[tuple[int, int, str]] = []
    _collect_substitutions(line, nodes, target, value, value_nodes, "top", replacements)
    if not replacements:
        raise StepsError(f"{symbol.strip()!r} does not appear in the line")
    out = line
    for start, end, text in sorted(replacements, reverse=True):
        if re.search(r"\\[A-Za-z]+$", text) and end < len(out) and out[end].isalpha():
            text += " "  # \pi before a letter would read as one command
        out = out[:start] + text + out[end:]
    return out


def _symbol(symbol: str) -> tuple[str, str | None]:
    """(base, subscript or None) of a symbol such as ``x``, ``\\alpha`` or ``x_1``."""
    found = atoms(parse(symbol.strip()))
    bad = StepsError("the symbol must be a letter or a command such as x, \\alpha or x_1")
    if len(found) != 1 or found[0].script("^") is not None:
        raise bad
    base = found[0].base
    if base.kind != "leaf" or base.token.kind not in ("letter", "command") or base.is_operator:
        raise bad
    sub = found[0].script("_")
    return base.token.text, _script_text(symbol.strip(), sub) if sub is not None else None


def _script_text(tex: str, node: Node) -> str:
    if node.kind == "group" and node.opener == "{":
        return tex[node.open_end : node.close_start].strip()
    return node.text(tex)


def _collect_substitutions(
    tex: str,
    nodes: list[Node],
    target: tuple[str, str | None],
    value: str,
    value_nodes: list[Node],
    context: str,  # top: a side of the equation; brace: inside {...}; other: inside a group
    out: list[tuple[int, int, str]],
) -> None:
    sides = _split_at_equals(nodes) if context == "top" else [nodes]
    for side in sides:
        found = atoms(side)
        for index, atom in enumerate(found):
            base = atom.base
            sub = atom.script("_")
            matches = (
                base.kind == "leaf"
                and base.token.text == target[0]
                and (sub is None) == (target[1] is None)
                and (sub is None or _script_text(tex, sub) == target[1])
            )
            if matches:
                end = base.end
                if sub is not None:
                    mark_index = [m for m, _ in atom.scripts].index("_")
                    if mark_index != 0:
                        matches = False  # x^2_1: leave it alone
                    end = sub.end
            if matches:
                alone = len(found) == 1 and context in ("top", "brace")
                powered = atom.script("^") is not None
                previous = found[index - 1].base if index > 0 else None
                following = found[index + 1].base if index + 1 < len(found) else None
                digits_meet = (
                    value[0].isdigit() and previous is not None and _ends_with_number(previous)
                ) or (value[-1].isdigit() and following is not None and _starts_with_number(following))
                if powered and not _is_power_base(value_nodes):
                    text = _wrap(value, value_nodes)
                elif alone:
                    text = value
                elif not _is_atomic(value_nodes) or digits_meet:
                    text = _wrap(value, value_nodes)
                else:
                    text = value
                out.append((base.start, end, text))
            else:
                _descend(tex, base, target, value, value_nodes, out)
            for mark, arg in atom.scripts:
                if matches and mark == "_" and arg is sub:
                    continue
                _script_substitution(tex, arg, target, value, value_nodes, out)


def _descend(tex, node: Node, target, value, value_nodes, out) -> None:
    if node.kind == "group":
        context = "brace" if node.opener == "{" else "other"
        _collect_substitutions(tex, node.children, target, value, value_nodes, context, out)
    elif node.kind == "command" and node.name not in OPAQUE:
        for arg in node.children:
            if arg.kind == "group":
                _descend(tex, arg, target, value, value_nodes, out)
            else:
                _script_substitution(tex, arg, target, value, value_nodes, out)


def _script_substitution(tex, arg: Node, target, value, value_nodes, out) -> None:
    """A script or argument without braces (``e^x``, ``\\frac12``): braces around a longer value."""
    if arg.kind == "leaf":
        if target[1] is None and arg.token.text == target[0]:
            out.append((arg.start, arg.end, value if len(value) == 1 else f"{{{value}}}"))
        return
    _descend(tex, arg, target, value, value_nodes, out)


def _split_at_equals(nodes: list[Node]) -> list[list[Node]]:
    sides: list[list[Node]] = [[]]
    for node in nodes:
        if node.kind == "leaf" and node.token.text == "=":
            sides.append([])
        else:
            sides[-1].append(node)
    return sides


def _ends_with_number(node: Node) -> bool:
    return node.kind == "leaf" and node.token.kind == "number"


def _starts_with_number(node: Node) -> bool:
    return node.kind == "leaf" and node.token.kind == "number"


# -- matching two steps ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Piece:
    key: str  # equal keys match
    start: int
    end: int
    structural: bool  # a bracket or a command head: never stands out on its own


@dataclass(frozen=True)
class NewPiece:
    """A run of new pieces in a step, as the part key ``(tex, occurrence)`` that finds it."""

    tex: str
    occurrence: int
    start: int
    end: int


@dataclass(frozen=True)
class Transition:
    kind: str  # MATCHING or REPLACING
    shared: tuple[str, ...]  # the pieces both steps share, in order (their TeX)
    new: tuple[NewPiece, ...]  # what is new in the second step, ready for part colouring
    gone: tuple[str, ...]  # runs of the first step that are not in the second
    skipped: tuple[tuple[str, str], ...] = ()  # new runs that cannot be parts, and why

    @property
    def label(self) -> str:
        return "matching morph" if self.kind == MATCHING else "replacement morph"


def pieces(tex: str, nodes: list[Node] | None = None) -> tuple[list[Piece], list[tuple[Node, int, int]]]:
    """``tex`` flattened in reading order, and each node with its range of pieces."""
    nodes = parse(tex) if nodes is None else nodes
    out: list[Piece] = []
    ranges: list[tuple[Node, int, int]] = []

    def visit(node: Node, owner: str = "") -> None:
        first = len(out)
        if node.kind == "leaf":
            out.append(Piece(node.token.text, node.start, node.end, False))
        elif node.kind == "group":
            out.append(Piece(owner + node.opener, node.start, node.open_end, True))
            for child in node.children:
                visit(child)
            out.append(Piece(owner + node.closer, node.close_start, node.end, True))
        else:
            head = node.head
            out.append(Piece(head.text, head.start, head.end, True))
            for index, arg in enumerate(node.children):
                visit(arg, f"{head.text}#{index}")
        ranges.append((node, first, len(out)))

    for node in nodes:
        visit(node)
    return out, ranges


def _lcs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    """Index pairs of a longest common subsequence of ``a`` and ``b`` (common ends first)."""
    head = 0
    while head < len(a) and head < len(b) and a[head] == b[head]:
        head += 1
    tail = 0
    while tail < len(a) - head and tail < len(b) - head and a[-1 - tail] == b[-1 - tail]:
        tail += 1
    mid_a, mid_b = a[head : len(a) - tail], b[head : len(b) - tail]
    n, m = len(mid_a), len(mid_b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, below = table[i], table[i + 1]
        for j in range(m - 1, -1, -1):
            row[j] = below[j + 1] + 1 if mid_a[i] == mid_b[j] else max(below[j], row[j + 1])
    pairs = [(k, k) for k in range(head)]
    i = j = 0
    while i < n and j < m:
        if mid_a[i] == mid_b[j]:
            pairs.append((head + i, head + j))
            i, j = i + 1, j + 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    pairs += [(len(a) - tail + k, len(b) - tail + k) for k in range(tail)]
    return pairs


def plan_transition(a: str, b: str) -> Transition:
    """What happens between step ``a`` and step ``b``.

    Pieces are matched along a longest common subsequence of the two flattened steps; the
    pieces of ``b`` outside it are new. A morph keeps what both share and fades the rest:
    ``TransformMatchingTex`` (it matches glyphs by shape, parts by TeX, ADR 0020), or a plain
    replacement ``Transform`` when the steps share nothing. Lines that cannot be read are
    replaced too (LaTeX will say why)."""
    try:
        nodes_a, nodes_b = parse(a), parse(b)
    except StepsError as error:
        return Transition(REPLACING, (), (), (), (("", f"the line cannot be read: {error}"),))
    pieces_a, ranges_a = pieces(a, nodes_a)
    pieces_b, ranges_b = pieces(b, nodes_b)
    pairs = _lcs([p.key for p in pieces_a], [p.key for p in pieces_b])
    kept_a = {i for i, _ in pairs}
    kept_b = {j for _, j in pairs}
    shared = tuple(pieces_b[j].key for _, j in pairs if not pieces_b[j].structural)
    kind = MATCHING if shared else REPLACING
    new_runs = _runs(b, nodes_b, ranges_b, pieces_b, kept_b)
    gone = tuple(a[s:e] for s, e in _runs(a, nodes_a, ranges_a, pieces_a, kept_a))
    new, skipped = [], []
    for start, end in new_runs:
        tex = b[start:end]
        occurrence = parts.count(b, tex, 0, start)
        if parts.find(b, tex, occurrence) != start:  # the key would find another place
            skipped.append((tex, "it overlaps another match of the same text"))
            continue
        new.append(NewPiece(tex, occurrence, start, end))  # parts.resolve decides if it can be marked
    return Transition(kind, shared, tuple(new), gone, tuple(skipped))


def _runs(
    tex: str,
    nodes: list[Node],
    ranges: list[tuple[Node, int, int]],
    flat: list[Piece],
    kept: set[int],
) -> list[tuple[int, int]]:
    """Spans of whole nodes none of whose pieces are kept, neighbours merged into one run."""
    span_of = {id(node): (first, last) for node, first, last in ranges}

    def fresh(node: Node) -> bool:
        first, last = span_of[id(node)]
        return all(i not in kept for i in range(first, last))

    out: list[tuple[int, int]] = []

    def walk(siblings: list[Node]) -> None:
        run: list[Node] = []
        for node in siblings:
            if fresh(node):
                run.append(node)
                continue
            close(run)
            run = []
            if node.kind == "group":
                walk(node.children)
            elif node.kind == "command":
                for arg in node.children:
                    walk([arg])
        close(run)

    def close(run: list[Node]) -> None:
        while run and run[0].kind == "leaf" and run[0].token.text in "^_":
            run = run[1:]
        while run and run[-1].kind == "leaf" and run[-1].token.text in "^_":
            run = run[:-1]
        if len(run) == 1 and run[0].kind == "group" and run[0].opener == "{" and run[0].children:
            run = run[0].children  # an argument {a}: its content stands out, not its braces
        if run:
            out.append((run[0].start, run[-1].end))

    walk(nodes)
    return out


# -- what the generator did ----------------------------------------------------------------------


@dataclass(frozen=True)
class StepsReport:
    layer_ids: tuple[str, ...]
    transitions: tuple[str, ...]  # the morph kind from each step to the next
    highlighted: tuple[tuple[int, str, int], ...] = ()  # (step number, TeX, occurrence)
    skipped: tuple[tuple[int, str, str], ...] = ()  # (step number, TeX, why it is not coloured)
    end: float = 0.0  # when the last morph ends

    def summary(self) -> str:
        counts = Counter(self.transitions)
        parts_text = [f"{len(self.layer_ids)} step{'s' * (len(self.layer_ids) != 1)}"]
        if counts[MATCHING]:
            parts_text.append(f"{counts[MATCHING]} matching morph{'s' * (counts[MATCHING] != 1)}")
        if counts[REPLACING]:
            parts_text.append(f"{counts[REPLACING]} replacement morph{'s' * (counts[REPLACING] != 1)}")
        if self.highlighted:
            n = len(self.highlighted)
            parts_text.append(f"{n} new term{'s' * (n != 1)} coloured")
        if self.skipped:
            parts_text.append(f"{len(self.skipped)} not coloured")
        return "Added " + ", ".join(parts_text)
