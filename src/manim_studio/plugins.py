"""Plugins add object types to Manim Studio (ADR 0032). This module is the public API.

A plugin is a Python module - installed with an entry point in the group
``manim_studio.plugins``, or a ``.py`` file in a plugin folder (the folders in
``MANIM_STUDIO_PLUGINS``, default ``~/.manim-studio/plugins``) - that registers
object types when imported::

    import manim as m
    from manim_studio.plugins import ObjectType, Param, register

    def build(params):
        length = params["length"]
        return m.VGroup(m.Line(m.ORIGIN, m.DOWN * length), m.Dot(m.DOWN * length))

    register(ObjectType("Pendulum", build, params=(Param("length", "float", 2.0),), section="Physics"))

``build(params)`` receives the object's params with every default filled in
(points as ``[x, y, 0]``) and returns a VMobject that depends only on them: the
editor builds each type twice on first use and refuses one that differs. The
editor centres the result, applies style and animates it like any object.

A plugin can also add a *simulation*, a layer stepped frame by frame like a
Manim updater (ADR 0033)::

    def start(params):
        return (params["angle"], 0.0)  # the state: any value, copied before each step

    def step(state, dt, params):  # dt = 1 / fps
        ...
        return new_state

    register(Simulation("Swing", start, step, draw, point=bob, params=(...)))

``draw(state, params)`` returns the VMobject for a state, in the layer's own
units (not re-centred); ``point(state, params)`` gives ``(x, y)``, the point a
traced path follows (default: the drawing's centre).

Plugins are loaded once per process when ``manim_studio.core.adapter`` is
imported, so the editor, its helper processes, the export and exported scenes
all know the same types. They are code you installed: they run without a
prompt. Installing or changing a plugin needs a restart.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logging_config import get_logger

log = get_logger(__name__)

ENTRY_POINT_GROUP = "manim_studio.plugins"
DEFAULT_FOLDER = Path.home() / ".manim-studio" / "plugins"


@dataclass(frozen=True)
class ObjectType:
    """An object type a plugin adds: its spec type name, builder and editable params."""

    name: str
    build: Callable[[dict[str, Any]], Any]
    params: tuple = ()  # manim_studio.plugins.Param (the editor's own Param)
    section: str = "Plugins"  # the library menu section
    label: str | None = None  # the library menu entry (default: name)
    slow: bool = False  # builds take long (e.g. LaTeX): the build worker builds them first (ADR 0015)


@dataclass(frozen=True)
class Simulation:
    """A simulated layer type (ADR 0033): a state stepped once per frame and drawn."""

    name: str
    start: Callable[[dict[str, Any]], Any]
    step: Callable[[Any, float, dict[str, Any]], Any]
    draw: Callable[[Any, dict[str, Any]], Any]
    point: Callable[[Any, dict[str, Any]], Any] | None = None  # what a traced path follows
    params: tuple = ()
    section: str = "Plugins"
    label: str | None = None


TYPES: dict[str, ObjectType] = {}  # registered object types by name
SIMULATIONS: dict[str, Simulation] = {}  # registered simulations by name
loaded: dict[str, list[str]] = {}  # plugin -> the types it registered
problems: dict[str, str] = {}  # plugin -> why it was skipped
_current: list[str] = []  # the plugin being loaded (to attribute its types)


def is_plugin_type(name: str) -> bool:
    return name in TYPES or name in SIMULATIONS


def __getattr__(name: str):
    if name == "Param":  # the editor's Param, imported lazily (the adapter loads this module)
        from .core.adapter import Param

        return Param
    raise AttributeError(name)


def register(object_type: ObjectType | Simulation) -> None:
    """Add an object type or a simulation: to the library, Properties and every process."""
    from .core import adapter

    if not object_type.name.isidentifier():
        raise ValueError(f"{object_type.name!r} is not a valid type name")
    taken = object_type.name in adapter.MOBJECT_PARAMS or object_type.name in TYPES | SIMULATIONS
    built_in = adapter.CHILD_ONLY_TYPES | adapter.PYTHON_TYPES | adapter.GROUP_TYPES
    if taken or object_type.name in built_in:
        raise ValueError(f"the type name {object_type.name!r} is already taken")
    if isinstance(object_type, Simulation):
        SIMULATIONS[object_type.name] = object_type
        adapter.MOBJECT_TYPES[object_type.name] = object_type.draw
    else:
        TYPES[object_type.name] = object_type
        adapter.MOBJECT_TYPES[object_type.name] = object_type.build
    adapter.MOBJECT_PARAMS[object_type.name] = tuple(object_type.params)
    adapter.LIBRARY_LABELS[object_type.name] = object_type.label or object_type.name
    for i, (section, names) in enumerate(adapter.LIBRARY):
        if section == object_type.section:
            adapter.LIBRARY[i] = (section, (*names, object_type.name))
            break
    else:
        adapter.LIBRARY.append((object_type.section, (object_type.name,)))
    if _current:
        loaded.setdefault(_current[-1], []).append(object_type.name)


def unregister(name: str) -> None:
    """Remove a registered type (tests)."""
    from .core import adapter

    TYPES.pop(name, None)
    SIMULATIONS.pop(name, None)
    adapter.MOBJECT_TYPES.pop(name, None)
    adapter.MOBJECT_PARAMS.pop(name, None)
    adapter.LIBRARY_LABELS.pop(name, None)
    adapter.LIBRARY[:] = [
        (section, tuple(n for n in names if n != name)) for section, names in adapter.LIBRARY
    ]
    adapter.LIBRARY[:] = [(section, names) for section, names in adapter.LIBRARY if names]
    for types in loaded.values():
        if name in types:
            types.remove(name)
    adapter.forget_plugin_builds()


def folders() -> list[Path]:
    """Where plugin files are looked for (``MANIM_STUDIO_PLUGINS``, os.pathsep-separated)."""
    value = os.environ.get("MANIM_STUDIO_PLUGINS")
    if value is None:
        return [DEFAULT_FOLDER]
    return [Path(part) for part in value.split(os.pathsep) if part]


def load_plugins() -> None:
    """Load every installed plugin once: entry points first, then plugin folders (sorted)."""
    try:
        entry_points = sorted(importlib.metadata.entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name)
    except Exception:  # a broken environment must not stop the editor
        log.exception("cannot list plugin entry points")
        entry_points = []
    for entry in entry_points:
        _load(f"entry point {entry.name}", lambda entry=entry: _run_entry_point(entry))
    for folder in folders():
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.py")):
            _load(str(path), lambda path=path: load_file(path))


def load_file(path: Path) -> None:
    """Import one plugin file as module ``manim_studio_plugin_<stem>``."""
    name = f"manim_studio_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise


def _run_entry_point(entry) -> None:
    target = entry.load()
    if callable(target):  # a function that registers; a module registered when it was imported
        target()


def _load(plugin: str, action: Callable[[], None]) -> None:
    _current.append(plugin)
    try:
        action()
    except Exception as exc:
        for name in loaded.pop(plugin, []):  # a skipped plugin adds nothing, even half-registered
            unregister(name)
        problems[plugin] = f"{type(exc).__name__}: {exc}"
        log.warning("plugin %s skipped: %s\n%s", plugin, exc, traceback.format_exc())
    else:
        loaded.setdefault(plugin, [])
        log.info("plugin %s: %s", plugin, ", ".join(loaded[plugin]) or "no types")
    finally:
        _current.pop()
