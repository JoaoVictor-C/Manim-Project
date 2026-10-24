"""Plain-language help for the errors of the user's code (P13.1).

``hint(error_type, message, source)`` turns what Python (or Manim) said - ``NameError`` and "name 'x' is not
defined" - into a short, kind explanation with the likeliest fix, written for people who are not
programmers: no blame, and no jargon without a word of explanation. Misspelt names are matched against
what Manim offers (``manim_names``) and what the code itself defines. ``split_legacy`` reads the old
one-string messages (``"NameError: name 'x' is not defined"``) that carry no separate type.
Pure: no Qt, no Manim.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

from . import manim_names

CUTOFF = 0.7  # stricter than the default: a wrong suggestion is worse than none
MAX_TEXT = 300  # a hint is a line or two in the status area, never a page
_TROUBLESHOOTING = "Troubleshooting > missing LaTeX"

_LEGACY = re.compile(r"^\s*((?:[A-Za-z_]\w*\.)*[A-Z]\w*(?:Error|Exception|Exit|Warning|Interrupt)): ?(.*)$")


@dataclass(frozen=True)
class Hint:
    """An explanation (``text``), names that may be what was meant (``suggestions``, likeliest first)
    and, when one line settles it, that line (``fix``, e.g. ``from manim import *``)."""

    text: str
    suggestions: tuple[str, ...] = ()
    fix: str = ""


def split_legacy(message: str) -> tuple[str, str]:
    """``("NameError", "name 'x' is not defined")`` from ``"NameError: name 'x' is not defined"``.

    A message that does not start like ``SomeError: `` comes back as ``("", message)``."""
    first, _, rest = str(message).partition("\n")
    found = _LEGACY.match(first)
    if found is None:
        return "", str(message)
    text = found.group(2)
    return found.group(1).rsplit(".", 1)[-1], text + ("\n" + rest if rest else "")


def hint(error_type: str, message: str, source: str = "") -> Hint | None:
    """The help for one error, or None when there is nothing useful to add."""
    try:
        return _hint(str(error_type or ""), str(message or ""), str(source or ""))
    except Exception:
        return None


def _hint(error_type: str, message: str, source: str) -> Hint | None:
    if not error_type:
        error_type, message = split_legacy(message)
    elif message.startswith(error_type + ":"):
        message = message[len(error_type) + 1 :].lstrip()
    lowered = message.lower()
    if "took longer than" in lowered:
        return _timeout(message)
    if any(word in lowered for word in ("latex", "miktex", "dvisvgm", "tex_file_writing")):
        return _latex(message)
    handler = _HANDLERS.get(error_type)
    if handler is not None:
        found = handler(message, source)
        if found is not None:
            return found
    return _by_message(message)


# -- helpers -----------------------------------------------------------------------------------------


def _make(text: str, suggestions: tuple[str, ...] = (), fix: str = "") -> Hint:
    text = " ".join(text.split())
    if len(text) > MAX_TEXT:
        text = text[: MAX_TEXT - 1].rstrip() + "…"
    return Hint(text, tuple(suggestions), fix)


def _ticks(words: tuple[str, ...] | list[str]) -> str:
    return " or ".join(f"`{w}`" for w in words)


def _did_you_mean(suggestions: list[str]) -> str:
    return f" Did you mean {_ticks(suggestions)}?" if suggestions else ""


_BRITISH = {
    "colour": "color",
    "centre": "center",
    "grey": "gray",
    "behaviour": "behavior",
    "favourite": "favorite",
    "normalise": "normalize",
    "organise": "organize",
    "analyse": "analyze",
}
_BRITISH_RE = re.compile("|".join(_BRITISH), re.IGNORECASE)


def americanise(word: str) -> str:
    """``colour`` -> ``color``, ``fill_colour`` -> ``fill_color``, ``GREY_A`` -> ``GRAY_A``."""

    def swap(found: re.Match[str]) -> str:
        text, repl = found.group(0), _BRITISH[found.group(0).lower()]
        return repl.upper() if text.isupper() else repl.capitalize() if text[0].isupper() else repl

    return _BRITISH_RE.sub(swap, word)


def defined_names(source: str) -> list[str]:
    """Names the code itself creates (variables, functions, classes, imports, parameters)."""
    found: dict[str, None] = {}
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        for pattern in (r"^\s*(?:def|class)\s+([A-Za-z_]\w*)", r"^\s*([A-Za-z_]\w*)\s*=(?!=)"):
            for match in re.finditer(pattern, source, re.MULTILINE):
                found[match.group(1)] = None
        return list(found)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            found[node.id] = None
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found[node.name] = None
            if not isinstance(node, ast.ClassDef):
                args = node.args
                for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                    if arg is not None:
                        found[arg.arg] = None
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    found[(alias.asname or alias.name).split(".")[0]] = None
        elif isinstance(node, ast.ExceptHandler) and node.name:
            found[node.name] = None
    return list(found)


def _builtin_names() -> list[str]:
    return [n for n in dir(builtins) if not n.startswith("_")]


def _imports_manim(source: str) -> bool:
    return re.search(r"^\s*(?:from\s+manim\b|import\s+manim\b)", source, re.MULTILINE) is not None


def _attributes_of(type_name: str) -> list[str]:
    """Public attribute names of a Manim class or a built-in type named in an error message."""
    attributes = list(manim_names.methods(type_name))
    if not attributes:
        python_type = getattr(builtins, type_name, None)
        if isinstance(python_type, type):
            attributes = [a for a in dir(python_type) if not a.startswith("_")]
    return attributes


def _module_attributes(name: str) -> list[str]:
    module = sys.modules.get(name)
    if module is None and name in ("math", "random", "numpy", "itertools", "colorsys"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            return []
    return [a for a in dir(module) if not a.startswith("_")] if module is not None else []


# -- handlers ----------------------------------------------------------------------------------------


def _name_error(message: str, source: str) -> Hint | None:
    found = re.search(r"name '([^']+)' is not defined", message)
    if found is None:
        return None
    name = found.group(1)
    if name == "self":
        return _make(
            "`self` only exists inside a method, for example the lines indented under `def construct(self):`. "  # noqa: E501
            "Check that this line is indented inside it."
        )
    own = defined_names(source)
    in_manim = manim_names.is_known(name)
    if source.strip() and in_manim and not _imports_manim(source):  # no source: nothing to say about it
        return _make(
            f"`{name}` comes from Manim, but this code does not load Manim. Did you forget "
            "`from manim import *` at the top?",
            (name,),
            "from manim import *",
        )
    pool = [*own, *manim_names.names(), *_builtin_names()]
    suggestions = manim_names.close_matches(name, pool, cutoff=CUTOFF)
    spelled = americanise(name)
    if spelled != name and manim_names.is_known(spelled):
        suggestions = [spelled, *[s for s in suggestions if s != spelled]][:3]
    if suggestions:
        return _make(
            f"Python does not know the name `{name}`. It may be a typo.{_did_you_mean(suggestions)}",
            tuple(suggestions),
        )
    return _make(
        f"Python does not know the name `{name}`. A name has to be created before it is used "
        f"(for example `{name} = 1`) and spelled the same way every time, capital letters included."
    )


def _unbound_local(message: str, source: str) -> Hint | None:
    found = re.search(r"variable '([^']+)'", message)
    name = f"`{found.group(1)}`" if found else "A variable"
    return _make(
        f"{name} is used before it has a value. Inside a function, a name that is set anywhere "
        "in it must be set before it is read: give it a value on an earlier line."
    )


def _attribute_error(message: str, source: str) -> Hint | None:
    module = re.search(r"module '([^']+)' has no attribute '([^']+)'", message)
    if module is not None:
        name, attribute = module.groups()
        suggestions = manim_names.close_matches(attribute, _module_attributes(name), cutoff=CUTOFF)
        return _make(
            f"The module `{name}` has nothing called `{attribute}`.{_did_you_mean(suggestions)} "
            "Check the spelling and the capital letters.",
            tuple(suggestions),
        )
    found = re.search(r"'?([\w.]+)'? object has no attribute '([^']+)'", message)
    if found is None:
        return None
    kind, attribute = found.groups()
    if kind == "NoneType":
        return _make(
            f"A value is `None` (meaning nothing) where `.{attribute}` was expected. An earlier step "
            "probably gave nothing back: some functions only do something and return no result."
        )
    pool = _attributes_of(kind)
    suggestions = manim_names.close_matches(attribute, pool, cutoff=CUTOFF)
    spelled = americanise(attribute)
    if spelled != attribute and spelled in pool:
        suggestions = [spelled, *[s for s in suggestions if s != spelled]][:3]
    return _make(
        f"That `{kind}` has no `{attribute}`.{_did_you_mean(suggestions)} Check the spelling"
        + (
            "; Manim writes names in lower case with underscores, in American spelling."
            if manim_names.methods(kind)
            else "."
        ),
        tuple(suggestions),
    )


def _call_names(source: str, keyword: str) -> list[str]:
    """Callables in ``source`` that are called with ``keyword=``, in order."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and any(k.arg == keyword for k in node.keywords):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else ""
            )
            if name:
                found.append(name)
    return found


def _type_error(message: str, source: str) -> Hint | None:
    keyword = re.search(r"unexpected keyword argument '([^']+)'", message)
    if keyword is not None:
        return _bad_keyword(message, source, keyword.group(1))
    missing = re.search(
        r"([\w.]+)\(\) missing \d+ required (?:positional|keyword-only) arguments?: (.+)", message
    )
    if missing is not None:
        function = missing.group(1).removesuffix(".__init__")
        names = re.findall(r"'([^']+)'", missing.group(2))
        what = ", ".join(f"`{n}`" for n in names) or "a value"
        return _make(f"`{function}(...)` needs {what} and none was given. Add it between the brackets.")
    count = re.search(r"([\w.]+)\(\) takes (\d+) positional arguments? but (\d+) (?:were|was) given", message)
    if count is not None:
        function, takes, given = count.groups()
        return _make(
            f"`{function}(...)` takes {takes} value(s) but {given} were given. Remove the extra one, "
            "or check that the commas and brackets are where you meant."
        )
    multiple = re.search(r"got multiple values for argument '([^']+)'", message)
    if multiple is not None:
        return _make(f"`{multiple.group(1)}` was given twice in the same call. Keep only one of them.")
    if "object is not callable" in message:
        kind = re.search(r"'(\w+)' object", message)
        return _make(
            f"Brackets were put after a value of type `{kind.group(1) if kind else '?'}`, which is not a function. "  # noqa: E501
            "Often a variable has the same name as a function, or a `*` is missing between a number and "
            "a bracket."
        )
    if "not subscriptable" in message:
        return _make(
            "Square brackets `[...]` were used on something that is not a list or a table. "
            "Check that the value before the bracket is the one you meant."
        )
    if "can only concatenate" in message or "unsupported operand" in message:
        return _make(
            "Two values of different kinds were combined, such as text and a number. "
            'Turn the number into text with `str(...)`, or build the text with an f-string: f"x = {x}".'
        )
    if "not iterable" in message or "has no len()" in message:
        return _make(
            "A single value was used where a list was expected (something to go through one item at a time). "
            "Put it in a list, like `[value]`, or check the name."
        )
    if "cannot be interpreted as an integer" in message:
        return _make(
            "A whole number is needed here, but a decimal one was given. Use `int(...)` to round it down."
        )
    if "not supported between" in message:
        return _make("Two values of different kinds cannot be compared (for example a number and text).")
    if "indices must be integers" in message:
        return _make("A list item is picked with a whole number (`items[0]`), not with text or a decimal.")
    return None


def _bad_keyword(message: str, source: str, keyword: str) -> Hint:
    owner = re.match(r"([\w.]+)\(\)", message)
    callee = owner.group(1) if owner else ""
    callee = callee.removesuffix(".__init__")
    called = next((c for c in _call_names(source, keyword) if manim_names.kwargs(c)), "")
    pool = list(manim_names.kwargs(called or callee)) or [k for k in manim_names.kwargs(callee)]
    spelled = americanise(keyword)
    suggestions = manim_names.close_matches(keyword, pool, cutoff=CUTOFF)
    target = called or callee
    target_text = f"`{target}`" if target else "this call"
    if spelled != keyword:
        extra = [s for s in suggestions if s != spelled][:2]
        return _make(
            f"{'Manim spells' if manim_names.kwargs(target) else 'The usual spelling is'} `{spelled}` "
            f"(American spelling), not `{keyword}`. Change the name in the call to {target_text}.",
            (spelled, *extra),
        )
    if suggestions:
        return _make(
            f"{target_text.capitalize()} has no option called `{keyword}`.{_did_you_mean(suggestions)}",
            tuple(suggestions),
        )
    return _make(
        f"{target_text.capitalize()} has no option called `{keyword}`. Check the spelling, or remove it "
        "if it was not needed."
    )


_CLOSERS = {"(": ")", "[": "]", "{": "}"}


def _syntax_error(message: str, source: str) -> Hint | None:
    lowered = message.lower()
    if "unterminated triple-quoted" in lowered:
        return _make(
            "A text block opened with \"\"\" (or ''') is never closed. Add the same three quotes where it should end."  # noqa: E501
        )
    if "unterminated string" in lowered:
        return _make(
            "A piece of text starts with a quote but never ends. Add the closing quote on the same line."
        )
    never = re.search(r"'([(\[{])' was never closed", message)
    if never is not None:
        opener = never.group(1)
        return _make(
            f"A `{opener}` was opened but never closed. Add the matching `{_CLOSERS[opener]}` - "
            "the line shown may be a little after the real mistake."
        )
    if "unmatched" in lowered:
        return _make(
            "A closing bracket has no opening one before it. Remove it, or add the missing opening bracket."
        )
    if "does not match opening" in lowered:
        return _make(
            "A closing bracket does not match the one that was opened (for example `(` closed by `]`). Fix the pair."  # noqa: E501
        )
    if "expected an indented block" in lowered:
        return _make(
            "After a line that ends with `:` the next line must be pushed to the right (4 spaces). "
            "Indent it, or put `pass` if the block should stay empty."
        )
    if "unexpected indent" in lowered:
        return _make(
            "This line is pushed further right than the lines around it. Line it up with the previous line."
        )
    if "unindent does not match" in lowered:
        return _make(
            "The start of this line lines up with no earlier line. Use the same number of spaces as the block it belongs to."  # noqa: E501
        )
    if "tabs and spaces" in lowered:
        return _make("Tabs and spaces are mixed at the start of lines. Use spaces only (4 per level).")
    if "expected ':'" in lowered:
        return _make(
            "A line starting with `if`, `for`, `while`, `def`, `class` or `else` must end with a `:`. Add it at the end."  # noqa: E501
        )
    if "forgot a comma" in lowered:
        return _make(
            "Two values are next to each other. Put a comma between them (or check a missing operator like `+`)."  # noqa: E501
        )
    if "missing parentheses in call to 'print'" in lowered:
        return _make("In Python 3 `print` needs brackets: print('text').")
    if "maybe you meant '=='" in lowered or "cannot assign to" in lowered:
        return _make(
            "A single `=` stores a value in a name (`x = 3`); to compare two values use `==`. "
            "The left side of `=` has to be a name."
        )
    if "'return' outside function" in lowered:
        return _make("`return` only works inside a function (`def ...:`). Remove it or move it into one.")
    if "without a default follows" in lowered:
        return _make(
            "In a `def`, options that have a default value (`x=1`) must come after those without one."
        )
    if "f-string" in lowered:
        return _make(
            'An f-string (text starting with f") needs every `{` closed by a `}`; write `{{` for a literal brace.'  # noqa: E501
        )
    if "invalid syntax" in lowered:
        return _make(
            "Python cannot read this line. Usual causes: a missing bracket, quote, comma or `:` on this "
            "line or the one before, or a symbol that should not be there."
        )
    return None


def _import_error(message: str, source: str) -> Hint | None:
    lowered = message.lower()
    if "not trusted" in lowered:
        return _make(
            "This helper has not been approved to run on this computer yet. Trust it first, then run again."
        )
    missing = re.search(r"No module named '([^']+)'", message)
    if missing is not None:
        name = missing.group(1)
        return _make(
            f"`{name}` is not installed here, and Studio can only use what comes with it (Manim, numpy, math...). "  # noqa: E501
            "If it is your own code, add it to the project as a helper."
        )
    cannot = re.search(r"cannot import name '([^']+)' from '([^']+)'", message)
    if cannot is not None:
        name, module = cannot.groups()
        pool = list(manim_names.names()) if module == "manim" else _module_attributes(module.split(".")[0])
        suggestions = manim_names.close_matches(name, pool, cutoff=CUTOFF)
        return _make(
            f"`{module}` has nothing called `{name}`.{_did_you_mean(suggestions)} Check the spelling.",
            tuple(suggestions),
        )
    return None


def _zero_division(message: str, source: str) -> Hint:
    return _make(
        "Something was divided by zero, which has no answer. Check the value after the `/`: "
        "it may be 0 for some parameter values (a slider at its minimum, for example)."
    )


def _value_error(message: str, source: str) -> Hint | None:
    lowered = message.lower()
    if "math domain error" in lowered:
        return _make(
            "A math function got a number it cannot handle, such as the square root or the logarithm of "
            "a negative number (or of 0). Check the value that goes into it."
        )
    if "too many values to unpack" in lowered or "not enough values to unpack" in lowered:
        expected = re.search(r"expected (\d+)", message)
        return _make(
            "A list was split into a different number of names than it has items"
            + (f" (the line expects {expected.group(1)})" if expected else "")
            + ". Make the names on the left match the number of items on the right."
        )
    if "could not convert string to float" in lowered or "invalid literal for int()" in lowered:
        text = re.search(r": '(.*)'$", message.splitlines()[0] if message else "")
        shown = f" ('{text.group(1)[:20]}')" if text else ""
        return _make(
            f"A piece of text{shown} was turned into a number, but it is not one. Check what is typed."
        )
    if "substring not found" in lowered:
        return _make(
            "The text being looked for is not inside the other text. Check the spelling, or test with `in` first."  # noqa: E501
        )
    return None


def _index_error(message: str, source: str) -> Hint:
    if "pop from empty" in message:
        return _make("An item was taken from a list that is empty. Check that something was added first.")
    return _make(
        "An item number was asked for that the list does not have. Counting starts at 0, so a list of 3 items "  # noqa: E501
        "has items 0, 1 and 2. Check the number or the length of the list."
    )


def _params_keys(source: str) -> list[str] | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        named = isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PARAMS" for t in node.targets
        )
        if named and isinstance(node.value, ast.Dict):
            keys = node.value.keys
            return [k.value for k in keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    return None


def _key_error(message: str, source: str) -> Hint:
    first = message.splitlines()[0] if message else ""
    try:
        key = ast.literal_eval(first)
    except (ValueError, SyntaxError):
        key = first
    keys = _params_keys(source)
    if keys is not None and isinstance(key, str) and key not in keys:
        suggestions = manim_names.close_matches(key, keys, cutoff=CUTOFF)
        have = ", ".join(keys[:8]) or "nothing"
        return _make(
            f"There is no parameter called `{key}`; PARAMS has {have}.{_did_you_mean(suggestions)}",
            tuple(suggestions),
        )
    return _make(
        f"There is no entry called `{key}` in that table (a dictionary). Check the spelling, "
        f"or use .get('{key}') to get nothing instead of an error when it is missing."
        if isinstance(key, str)
        else f"There is no entry `{key}` in that table (a dictionary). Check the key."
    )


def _recursion(message: str, source: str) -> Hint:
    return _make(
        "A function keeps calling itself and never stops. Give it a case where it returns without calling "
        "itself again, or use a loop instead."
    )


def _file_error(message: str, source: str) -> Hint:
    return _make(
        "That file was not found. Check the name and the folder: a plain name is looked for next to the "
        "project, not next to Studio."
    )


def _timeout(message: str) -> Hint:
    return _make(
        "It ran for too long and was stopped. An endless loop is the usual cause (a `while` whose condition "
        "never becomes false); otherwise there may be simply too much to draw - try fewer objects or a shorter scene."  # noqa: E501
    )


def _latex(message: str) -> Hint:
    lowered = message.lower()
    missing = (
        any(
            word in lowered
            for word in (
                "not installed",
                "not found",
                "no such file",
                "not recognized",
                "could not be started",
            )
        )
        and "compilation error" not in lowered
    )
    if missing:
        return _make(
            "Formulas (MathTex and Tex) need LaTeX, which is not set up on this computer. "
            f"See {_TROUBLESHOOTING} in the user guide to install it."
        )
    return _make(
        "LaTeX could not read the formula. Check that every `{` has its `}` and that special symbols are "
        f"written with a backslash. If it worked before, LaTeX may be missing: see {_TROUBLESHOOTING}."
    )


def _by_message(message: str) -> Hint | None:
    lowered = message.lower()
    if "define exactly one scene subclass" in lowered:
        return _make(
            "The code needs exactly one class that extends `Scene` (class MyScene(Scene):) with its animation "  # noqa: E501
            "inside `def construct(self):`."
        )
    if "build(p) must return" in lowered:
        return _make("build(p) must give back the shape: return a shape, a text or a VGroup of them.")
    if "code not trusted" in lowered or "not trusted" in lowered:
        return _make(
            "This code has not been approved to run on this computer yet. Trust it first, then run again."
        )
    return None


_HANDLERS: dict[str, Callable[[str, str], Hint | None]] = {
    "NameError": _name_error,
    "UnboundLocalError": _unbound_local,
    "AttributeError": _attribute_error,
    "TypeError": _type_error,
    "SyntaxError": _syntax_error,
    "IndentationError": _syntax_error,
    "TabError": _syntax_error,
    "ModuleNotFoundError": _import_error,
    "ImportError": _import_error,
    "ZeroDivisionError": _zero_division,
    "ValueError": _value_error,
    "IndexError": _index_error,
    "KeyError": _key_error,
    "RecursionError": _recursion,
    "FileNotFoundError": _file_error,
}
