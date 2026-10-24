"""Write ``src/manim_studio/core/manim_names.json``: what the installed Manim offers (P13.0).

The code assistance (did-you-mean in error hints, completion) needs the names Manim makes available
to a scene - what ``from manim import *`` gives - without importing Manim in the editor. This script
imports the installed Manim once and writes them down:

    python scripts/gen_manim_names.py            # rewrite the file
    python scripts/gen_manim_names.py --check    # exit 1 when the file is out of date

The file is ``{"manim_version", "names", "methods", "kwargs", "bases"}``:

* ``names``: the public names of ``from manim import *``, sorted (modules left out);
* ``methods``: for Mobject, VMobject, Scene, Animation and every public Mobject / Animation / Scene
  class among the names: the public methods and attributes the class *adds* to its parent in this
  table (``bases`` names the parent), so the file stays small; ``core/manim_names.py`` puts the
  chain back together;
* ``kwargs``: the parameter names of every public class (its ``__init__``) and function, ``self`` and
  ``*args`` / ``**kwargs`` left out; a class that passes ``**kwargs`` on also lists its parents'
  explicit ones;
* ``bases``: class -> its nearest parent that has an entry in ``methods``.

The output is sorted and idempotent: running it twice writes the same bytes.
"""

from __future__ import annotations

import argparse
import inspect
import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUTPUT = ROOT / "src" / "manim_studio" / "core" / "manim_names.json"

MAX_BYTES = 600_000  # the shipped file stays small


def _star_names() -> dict[str, object]:
    """What ``from manim import *`` binds, minus modules and private names."""
    namespace: dict[str, object] = {}
    exec("from manim import *", namespace)
    namespace.pop("__builtins__", None)
    return {
        key: value
        for key, value in namespace.items()
        if not key.startswith("_") and not isinstance(value, types.ModuleType)
    }


def _public(attributes) -> set[str]:
    return {a for a in attributes if not a.startswith("_")}


def _instance_attributes(factory) -> set[str]:
    """Public attributes a fresh instance carries (set in ``__init__``, so not in ``dir(cls)``)."""
    try:
        return _public(vars(factory()))
    except Exception:
        return set()


def _parameters(function) -> list[str]:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return []
    return [
        p.name
        for p in signature.parameters.values()
        if p.name != "self" and not p.name.startswith("_") and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]


def _takes_kwargs(function) -> bool:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return False
    return any(p.kind is p.VAR_KEYWORD for p in signature.parameters.values())


def _class_kwargs(cls: type) -> list[str]:
    """The explicit parameters of ``cls(...)``, following ``**kwargs`` up the parents' ``__init__``."""
    found: set[str] = set()
    for klass in cls.__mro__:
        init = klass.__dict__.get("__init__")
        if init is None or klass is object:
            continue
        found.update(_parameters(init))
        if not _takes_kwargs(init):
            break
    return sorted(found)


def build() -> dict:
    """The table for the installed Manim."""
    import manim as m

    logging.disable(logging.CRITICAL)  # Scene() and friends may log while being probed
    try:
        space = _star_names()
        roots = (m.Mobject, m.Animation, m.Scene)
        classes = {
            key: value
            for key, value in space.items()
            if inspect.isclass(value) and key[:1].isupper() and issubclass(value, roots)
        }
        extra = {
            "Mobject": _instance_attributes(m.Mobject),
            "VMobject": _instance_attributes(m.VMobject),
            "Scene": _instance_attributes(m.Scene),
            "Animation": _instance_attributes(lambda: m.Animation(m.Mobject())),
        }
        full = {key: _public(dir(cls)) | extra.get(key, set()) for key, cls in classes.items()}
        methods: dict[str, list[str]] = {}
        bases: dict[str, str] = {}
        for key, cls in classes.items():
            parent = next((b.__name__ for b in cls.__mro__[1:] if classes.get(b.__name__) is b), None)
            inherited = set() if parent is None else full[parent]
            methods[key] = sorted(full[key] - inherited)
            if parent is not None:
                bases[key] = parent
        kwargs: dict[str, list[str]] = {}
        for key, value in space.items():
            if inspect.isclass(value):
                parameters = _class_kwargs(value)
            elif callable(value):
                parameters = _parameters(value)
            else:
                continue
            if parameters:
                kwargs[key] = parameters
        return {
            "manim_version": m.__version__,
            "names": sorted(space),
            "methods": dict(sorted(methods.items())),
            "kwargs": dict(sorted(kwargs.items())),
            "bases": dict(sorted(bases.items())),
        }
    finally:
        logging.disable(logging.NOTSET)


def render(table: dict | None = None) -> str:
    """The file's text for ``table`` (default: built from the installed Manim): one entry per line."""
    import json

    table = build() if table is None else table

    def dump(value) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)

    lines = ["{", f'"manim_version":{dump(table["manim_version"])},', f'"names":{dump(table["names"])},']
    sections = ("methods", "kwargs", "bases")
    for index, section in enumerate(sections):
        entries = [f"{dump(key)}:{dump(value)}" for key, value in table[section].items()]
        lines.append(f'"{section}":{{')
        lines.append(",\n".join(entries))
        lines.append("}" + ("," if index < len(sections) - 1 else ""))
    lines.append("}")
    return "\n".join(lines) + "\n"


def write(path: Path = OUTPUT) -> bool:
    """Write the file; False when it was already up to date."""
    text = render()
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise SystemExit(f"manim_names.json would be {len(text)} bytes (limit {MAX_BYTES}): trim the table")
    if path.exists() and path.read_bytes() == text.encode("utf-8"):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the file is out of date")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if args.check:
        current = args.output.read_bytes() if args.output.exists() else b""
        if current != render().encode("utf-8"):
            print(f"{args.output} is out of date: run python scripts/gen_manim_names.py")
            return 1
        return 0
    changed = write(args.output)
    print(f"{'wrote' if changed else 'unchanged'}: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
