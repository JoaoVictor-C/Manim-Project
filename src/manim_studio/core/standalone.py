"""A Python object as a Manim scene that runs by itself (P13.7, "Copy as Manim code").

The object's text is kept as it is; a scene class is added that calls ``build`` with the values the
object has now, so the result can be rendered with ``manim`` outside the editor.
"""

from __future__ import annotations

import ast
import pprint
from typing import Any

from . import python_object
from .python_export import class_name


def standalone_scene(code: str, values: dict[str, Any] | None = None, name: str = "Object") -> str:
    """``code`` plus ``from manim import *`` and a ``Scene`` showing ``build(p)`` with ``values``."""
    body = code.removeprefix("\ufeff").rstrip() + "\n"
    chosen = python_object.call_values(code, values or {})
    imports = [] if _imports_manim(body) else ["from manim import *\n\n"]
    literal = pprint.pformat(chosen, sort_dicts=False, width=96)
    lines = [
        *imports,
        body,
        "\n\n",
        f"class {class_name(name)}(Scene):\n",
        "    def construct(self):\n",
        f"        p = {literal}\n",
        "        self.add(build(p))\n",
        "        self.wait(1)\n",
    ]
    return "".join(lines)


def _imports_manim(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.ImportFrom) and node.module is not None and node.module.split(".")[0] == "manim"
        for node in ast.walk(tree)
    )
