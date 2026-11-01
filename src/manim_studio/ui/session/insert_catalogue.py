"""What can be inserted, sorted the way the insert tools show it (ADR 0087).

The object library (``adapter.LIBRARY``: sections of types, plugins' sections after them) is one flat
catalogue here: each *entry* is something the editor can add, with the category it is shown in (Shapes,
Lines, Text...), and the *insert groups* are the tools of the Stage's tool rail (Shape, Line, Text, Math,
Media, Graph, 3D), each a category with a default variant, a key and keys for a few of its variants. The Add
object popover and the tool rail both read this; it holds no widgets.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.code import python_templates
from ...core.engine import adapter
from ...core.model.schema import CONNECTOR_TYPES, TRACE_TYPES


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    icon: str  # a name in ``icons.NAMES``


CATEGORIES: tuple[Category, ...] = (
    Category("shapes", "Shapes", "shape"),
    Category("lines", "Lines", "line"),
    Category("text", "Text", "text"),
    Category("math", "Math", "maths"),
    Category("media", "Media", "image"),
    Category("graphs", "Graphs", "axes"),
    Category("solids", "3D", "object"),
    Category("simulation", "Simulation", "simulation"),
    Category("code", "Code", "code"),
    Category("plugins", "Plugins", "plugin"),
    Category("scene", "Scene", "camera"),
)
CATEGORY_BY_KEY = {c.key: c for c in CATEGORIES}

# the library's own sections -> category (any other section was added by a plugin)
SECTION_CATEGORY = {
    "Shapes": "shapes",
    "Lines & Arrows": "lines",
    "Curves & Annotations": "lines",
    "Text": "text",
    "Media": "media",
    "Graphing": "graphs",
    "Coordinates": "graphs",
    "3D Solids": "solids",
    "Simulation": "simulation",
    "Python": "code",
}
MATH_TYPES = ("MathTex", "Tex")


@dataclass(frozen=True)
class Entry:
    """One thing the Add object popover offers."""

    key: str  # stable, as remembered in the recent row: ``obj:Circle``, ``py:Right triangle``, ``steps``...
    kind: str  # "object" (a library type), "python" (a template), "steps" (equation steps), "camera"
    label: str
    category: str  # a ``Category.key``
    type_name: str = ""  # the library type, for kind "object"
    code: str = ""  # the template's code, for kind "python"
    section: str = ""  # the library section it came from (the Plugins category groups by it)
    tip: str = ""

    @property
    def search_text(self) -> str:
        return f"{self.label} {self.type_name} {CATEGORY_BY_KEY[self.category].title} {self.section}"


def label_of(type_name: str) -> str:
    return adapter.LIBRARY_LABELS.get(type_name, type_name)


def entries() -> list[Entry]:
    """Every entry, in library order (read afresh: plugins add and remove types while the editor runs)."""
    found: list[Entry] = []
    for section, types in adapter.LIBRARY:
        default = SECTION_CATEGORY.get(section, "plugins")
        for type_name in types:
            category = "math" if type_name in MATH_TYPES else default
            found.append(
                Entry(f"obj:{type_name}", "object", label_of(type_name), category, type_name, section=section)
            )
            if type_name == "MathTex":  # P11: a derivation, one MathTex per step
                found.append(
                    Entry(
                        "steps",
                        "steps",
                        "Equation steps...",
                        "math",
                        section=section,
                        tip="Type the steps of a derivation, one equation per line",
                    )
                )
    for name, code in python_templates.LAYER_TEMPLATES.items():
        found.append(
            Entry(
                f"py:{name}",
                "python",
                name,
                "code",
                code=code,
                section="Python objects",
                tip=f"The editable {name.lower()} Python object",
            )
        )
    found.append(Entry("camera", "camera", "Camera", "scene", tip="The view the video is shot through"))
    return found


def by_key() -> dict[str, Entry]:
    return {entry.key: entry for entry in entries()}


# -- the tool rail's insert groups -----------------------------------------------------------------


@dataclass(frozen=True)
class InsertGroup:
    key: str  # also the Stage tool's name
    title: str
    icon: str  # a name in ``icons.NAMES`` (the group's icon in the collapsed rail and the menus)
    keys: str  # the tool's key
    category: str  # the entries its flyout lists
    default: str  # the variant before one is chosen


INSERT_GROUPS: tuple[InsertGroup, ...] = (
    InsertGroup("shape", "Shape", "shape", "R", "shapes", "Circle"),
    InsertGroup("line", "Line", "line", "L", "lines", "Line"),
    InsertGroup("text", "Text", "text", "T", "text", "Text"),
    InsertGroup("math", "Math", "maths", "E", "math", "MathTex"),
    InsertGroup("media", "Media", "image", "I", "media", "ImageMobject"),
    InsertGroup("graph", "Graph", "axes", "X", "graphs", "Axes"),
    InsertGroup("solid", "3D", "object", "D", "solids", "Cube"),
)
GROUP_BY_KEY = {g.key: g for g in INSERT_GROUPS}
# the keys of some variants (the group's key arms the last one used); none is a plain letter another
# command has: G (Game view), M (marker), F (frame) and A (Animate's graph) are taken
VARIANT_KEYS = {
    "Circle": "O",
    "Rectangle": "Shift+R",
    "Arrow": "Shift+L",
    "DecimalNumber": "Shift+T",
    "Tex": "Shift+E",
    "SVGMobject": "Shift+I",
    "NumberLine": "Shift+X",
    "Sphere": "Shift+D",
}
# what a click on the Stage cannot place alone: it needs a selected object
NEEDS_SELECTION = frozenset(TRACE_TYPES) | frozenset(CONNECTOR_TYPES)


def variants(group_key: str) -> list[Entry]:
    """The library types a group's flyout offers, in library order (not the ones that need a selection)."""
    group = GROUP_BY_KEY[group_key]
    return [
        e
        for e in entries()
        if e.kind == "object" and e.category == group.category and e.type_name not in NEEDS_SELECTION
    ]


def variant_or_default(group_key: str, type_name: str | None) -> str:
    """``type_name`` when it is still one of the group's variants (a plugin may have been removed), else the
    group's default."""
    group = GROUP_BY_KEY[group_key]
    return type_name if type_name in {e.type_name for e in variants(group_key)} else group.default
