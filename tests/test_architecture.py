"""The package layout and its layers (ADR 0062): who may import whom, and what must stay where it is.

Read from the source with ``ast`` - nothing is imported, so the test is fast and also sees modules that Qt or
Manim would make slow to load. Three kinds of import are told apart:

* **static** - at module level: the real dependency, the one that decides what can be imported alone;
* **lazy** - inside a function: how this code base breaks a cycle on purpose (``schema`` and ``edits`` reach
  the engine this way); allowed wherever the "never" rules below do not forbid it;
* **typing** - under ``if TYPE_CHECKING``: never runs.

When a rule fails, the import is probably in the wrong place. If the new dependency is right, move the package
in the layer table (``CORE_LAYERS`` / ``UI_LAYERS``) and say why in the change.
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PKG = "manim_studio"

# A package imports (statically) only from a lower rank, or from the same rank when listed in SIBLINGS.
CORE_LAYERS = {
    "model": 0,  # the document and the rules that need nothing else
    "code": 1,  # running and keeping the user's code
    "sound": 1,
    "exchange": 2,  # code in and out
    "editing": 2,
    "assist": 3,  # helping while code is typed
    "engine": 4,  # Manim: adapter, evaluator, export
}
UI_LAYERS = {
    "style": 0,
    "services": 1,  # the editor's side of its helper processes
    "session": 2,  # document, selection, build service, settings
    "deliver": 2,
    "timeline": 3,
    "canvas": 3,
    "playback": 4,
    "panels": 4,
    "code": 4,
    "shell": 4,
    "exchange": 5,
    "pages": 6,
}
# Packages of one rank that really depend on each other, one way (importer, imported).
SIBLINGS = {
    ("core.exchange", "core.code"),
    ("core.editing", "core.code"),
    ("ui.panels", "ui.canvas"),
    ("ui.panels", "ui.timeline"),
    ("ui.playback", "ui.canvas"),
    ("ui.shell", "ui.timeline"),
    ("ui.code", "ui.services"),
}
BASE = {f"{PKG}.logging_config", f"{PKG}.plugins"}  # under everything: no other module at import time
# names that other things were written against: exported scenes, plugins, the command line, subprocesses
STABLE = [
    f"{PKG}",
    f"{PKG}.cli",
    f"{PKG}.__main__",
    f"{PKG}.manim_scene",
    f"{PKG}.plugins",
    f"{PKG}.logging_config",
    f"{PKG}.processes.worker",
    f"{PKG}.processes.preview",
    f"{PKG}.processes.code_runner",
    f"{PKG}.processes.scene_recorder",
    f"{PKG}.processes.helper_check",
]


@dataclass(frozen=True)
class Import:
    importer: str
    target: str
    kind: str  # static | lazy | typing
    line: int


def module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def modules() -> dict[str, Path]:
    return {module_name(p): p for p in sorted(SRC.rglob("*.py"))}


def imports() -> Iterator[Import]:
    known = modules()
    for name, path in known.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            kind, up = "static", node
            while up in parents:
                up = parents[up]
                if isinstance(up, ast.If) and "TYPE_CHECKING" in ast.dump(up.test):
                    kind = "typing"
                    break
                if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "lazy"
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            else:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level else []
                module = ".".join(base + ([node.module] if node.module else []))
                targets = [
                    f"{module}.{a.name}" if f"{module}.{a.name}" in known else module for a in node.names
                ]
            for target in targets:
                if target.split(".")[0] == PKG:
                    yield Import(name, target, kind, node.lineno)


def area(module: str) -> str:
    """``core.model`` for ``manim_studio.core.model.schema``; ``render``, ``cli``... for the rest."""
    parts = module.split(".")[1:]
    if not parts:
        return ""
    return ".".join(parts[:2]) if parts[0] in ("core", "ui") else parts[0]


ALL = list(imports())


def folders(package: str) -> set[str]:
    return {p.name for p in (SRC / PKG / package).iterdir() if p.is_dir() and p.name != "__pycache__"}


def test_the_folders_are_the_layers_that_are_documented() -> None:
    assert folders("core") == set(CORE_LAYERS)
    assert folders("ui") == set(UI_LAYERS)


def test_no_module_is_left_loose_in_core() -> None:
    """Every core module lives in a package named for what it does: a new module goes in one."""
    assert [p.name for p in (SRC / PKG / "core").glob("*.py") if p.name != "__init__.py"] == []


def test_core_and_the_processes_never_touch_qt() -> None:
    qt = ("PySide6", "shiboken6")
    offenders = []
    for name, path in modules().items():
        if name.startswith((f"{PKG}.ui", f"{PKG}.render.qt_paths")):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [f"{name}:{node.lineno} imports {n}" for n in names if n.split(".")[0] in qt]
    assert offenders == []


def test_nothing_below_the_editor_imports_the_editor() -> None:
    """core, render and the processes work without the window: only the window reaches up."""
    never = {
        "core": ("ui", "render", "processes"),
        "render": ("ui", "processes"),
        "processes": ("ui",),
        "data": ("core", "ui", "render", "processes"),
    }
    offenders = [
        f"{i.importer}:{i.line} -> {i.target}"
        for i in ALL
        if i.kind != "typing"
        and area(i.target).split(".")[0] in never.get(area(i.importer).split(".")[0], ())
    ]
    assert offenders == []


def layer_violations(prefix: str, layers: dict[str, int]) -> list[str]:
    bad = []
    for i in ALL:
        a, b = area(i.importer), area(i.target)
        if i.kind != "static" or a == b or not (a.startswith(prefix) and b.startswith(prefix)):
            continue
        ra, rb = layers.get(a.removeprefix(prefix)), layers.get(b.removeprefix(prefix))
        if ra is None or rb is None:  # ui/main_window.py: the top of the window reaches every layer
            continue
        if rb > ra or (rb == ra and (a, b) not in SIBLINGS):
            bad.append(f"{i.importer}:{i.line} imports {i.target} ({a} rank {ra} -> {b} rank {rb})")
    return bad


def test_core_packages_import_only_downwards() -> None:
    assert layer_violations("core.", CORE_LAYERS) == []


def test_ui_packages_import_only_downwards() -> None:
    assert layer_violations("ui.", UI_LAYERS) == []


def test_the_base_modules_need_no_other_module_at_import_time() -> None:
    offenders = [
        f"{i.importer}:{i.line} -> {i.target}"
        for i in ALL
        if i.importer in BASE and i.kind == "static" and i.target not in BASE
    ]
    assert offenders == []


def test_the_names_other_things_were_written_against_still_exist() -> None:
    known = modules()
    assert [name for name in STABLE if name not in known] == []
    assert "def main(" in (SRC / PKG / "cli.py").read_text(encoding="utf-8")  # the ``manim-studio`` script
    scene = (SRC / PKG / "manim_scene.py").read_text(encoding="utf-8")
    assert "class StudioScene" in scene and "def configure(" in scene  # what an exported file imports
    assert "def register(" in (SRC / PKG / "plugins.py").read_text(encoding="utf-8")  # the plugin API


def test_the_process_modules_run_as_scripts() -> None:
    for name in STABLE:
        if ".processes." in name:
            text = (SRC / Path(*name.split("."))).with_suffix(".py").read_text(encoding="utf-8")
            assert '__name__ == "__main__"' in text, name


def test_the_files_that_ship_with_the_package_are_where_the_code_looks() -> None:
    from manim_studio import data as shipped
    from manim_studio.core.assist import manim_names
    from manim_studio.core.editing import library

    folder = SRC / PKG / "data"
    assert folder == shipped.FOLDER
    table = json.loads((folder / "manim_names.json").read_text(encoding="utf-8"))
    assert isinstance(table, dict) and table
    assert len(list((folder / "library").glob("*.json"))) >= 40  # presets, themes and templates
    assert folder / "library" == library.BUILTIN_FOLDER
    assert folder / "manim_names.json" == manim_names.FILE


def test_a_module_name_means_one_file() -> None:
    """A bare ``schema.py`` in a doc or traceback names one file: folders group, they do not disambiguate."""
    seen: dict[str, list[str]] = defaultdict(list)
    for name, path in modules().items():
        if path.name != "__init__.py":
            seen[path.stem].append(name)
    # pairs told apart by their folder: core / ui, camera / process
    twins = {"preview": 2, "scene_import": 2, "audio": 2}
    clashes = {leaf: names for leaf, names in seen.items() if len(names) > twins.get(leaf, 1)}
    assert clashes == {}
