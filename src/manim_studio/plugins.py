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

For an object plugin, set ``point_handle=True`` on a point parameter to expose
it as a draggable geometry handle. Only use this for a point used by the
object's geometry, not for ranges or other two-number settings::

    Param("tip", "point", (1.5, 0.0), "Tip", point_handle=True)

A plugin can also add a *voice provider* for the Narration section of the Audio page
(ADR 0060)::

    from pathlib import Path
    from manim_studio.plugins import Voice, VoiceError, VoiceProvider, register

    def voices() -> list[Voice]:  # may be slow: it runs in a helper process, never in the editor
        return [Voice("anna", "Anna", language="en-US", gender="female")]

    def synthesize(text: str, voice: str, rate: float, out: Path) -> None:
        ...  # write the spoken text to ``out`` (a file ``extension`` long); rate 1.0 is normal speed
        # raise VoiceError("the service is busy", retryable=True) to be tried again

    register(VoiceProvider("anna", "Anna (offline)", voices, synthesize, extension=".wav"))

Plugins are loaded once per process when ``manim_studio.core.engine.adapter`` is
imported, so the editor, its helper processes, the export and exported scenes
all know the same types. Installing or changing a plugin needs a restart.

A plugin may ship a manifest beside it (ADR 0078, ``manim_studio.plugin_manifest``):
``pendulum.plugin.json`` next to ``pendulum.py`` with its name, version, author,
description, the app versions it ``requires`` and the ``permissions`` it declares. It is
read before the plugin's code runs: a plugin whose range excludes this app is not loaded
("incompatible: needs ..."), an unusable manifest marks it broken, and a plugin with a
manifest loads only once the user approved its permissions in Help > Plugins (asked
again when it asks for more). A plugin without a manifest loads as before, marked "no
manifest: unknown permissions". Permissions are disclosed, not enforced: a plugin runs
in-process with the user's full rights.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import re
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import plugin_manifest
from .logging_config import get_logger
from .plugin_manifest import Manifest

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


@dataclass(frozen=True)
class Voice:
    """One voice of a provider: ``id`` is what ``synthesize`` receives."""

    id: str
    name: str
    language: str = ""  # a BCP 47 tag such as "en-US"
    gender: str = ""


class VoiceError(Exception):
    """A provider could not speak a text. ``retryable`` errors (a busy or flaky service) are tried
    again with a pause; the others are reported as they are."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class VoiceProvider:
    """A speech engine (ADR 0060). ``voices()`` and ``synthesize()`` run only in the voice helper
    process (``manim_studio.processes.voice``), with a time limit, never in the editor."""

    name: str  # lower case letters, digits, "-" and "_": it is saved in projects
    label: str  # shown in the voice list
    voices: Callable[[], list[Voice]]
    synthesize: Callable[[str, str, float, Path], None]  # (text, voice id, speed, file to write)
    online: bool = False  # the text leaves the computer
    supports_rate: bool = True  # False: the speed is ignored (and the editor says so)
    extension: str = ".wav"  # of the files it writes
    license_note: str = ""  # one line on where the voice may be used
    check: Callable[[], str | None] | None = None  # why it cannot run here (an install hint), else None


TYPES: dict[str, ObjectType] = {}  # registered object types by name
SIMULATIONS: dict[str, Simulation] = {}  # registered simulations by name
VOICES: dict[str, VoiceProvider] = {}  # registered voice providers by name (ADR 0060)
loaded: dict[str, list[str]] = {}  # plugin -> the types it registered
problems: dict[str, str] = {}  # plugin -> why it was skipped
manifests: dict[str, Manifest | None] = {}  # plugin -> its manifest (None: none, unknown permissions)
pending: dict[str, Manifest] = {}  # plugin -> its manifest, not loaded until the user approves it
approved: dict[str, Manifest] = {}  # plugin -> approved in this session: loads after a restart
approvals: dict[str, dict] = {}  # plugin -> the approval stored for it (ADR 0078), read at load time
_current: list[str] = []  # the plugin being loaded (to attribute its types)
_loaded_once = False


def is_plugin_type(name: str) -> bool:
    return name in TYPES or name in SIMULATIONS


def __getattr__(name: str):
    if name == "Param":  # the editor's Param, imported lazily (the adapter loads this module)
        from .core.engine.adapter import Param

        return Param
    raise AttributeError(name)


def register(object_type: ObjectType | Simulation | VoiceProvider) -> None:
    """Add an object type, a simulation or a voice provider: to the library, Properties and every
    process (a voice provider, to the Narration section)."""
    if isinstance(object_type, VoiceProvider):
        _register_voice(object_type)
        return
    from .core.engine import adapter

    if not object_type.name.isidentifier():
        raise ValueError(f"{object_type.name!r} is not a valid type name")
    taken = object_type.name in adapter.MOBJECT_PARAMS or object_type.name in TYPES | SIMULATIONS
    built_in = adapter.CHILD_ONLY_TYPES | adapter.PYTHON_TYPES | adapter.GROUP_TYPES | adapter.SHAPE_TYPES
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


def _register_voice(provider: VoiceProvider) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", provider.name):
        raise ValueError(f"{provider.name!r} is not a valid voice provider name")
    if provider.name in VOICES:
        raise ValueError(f"the voice provider name {provider.name!r} is already taken")
    VOICES[provider.name] = provider
    if _current:
        loaded.setdefault(_current[-1], []).append(f"voice:{provider.name}")


def unregister(name: str) -> None:
    """Remove a registered type or voice provider (tests)."""
    if name.startswith("voice:") or name in VOICES:
        key = name.removeprefix("voice:")
        VOICES.pop(key, None)
        for types in loaded.values():
            if f"voice:{key}" in types:
                types.remove(f"voice:{key}")
        return
    from .core.engine import adapter

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


def ensure_loaded() -> None:
    """Load the plugins if this process has not (a helper process that never imported the adapter)."""
    if not _loaded_once:
        load_plugins()


def voice_providers() -> dict[str, VoiceProvider]:
    """Every voice provider: the built-in ones, then those plugins added."""
    ensure_loaded()
    return dict(VOICES)


def _register_builtin_voices() -> None:
    from .core.voice import builtin_edge, builtin_sapi  # tiny: their engines load when they speak

    for provider in (builtin_sapi.PROVIDER, builtin_edge.PROVIDER):
        if provider.name not in VOICES:
            VOICES[provider.name] = provider


def load_plugins() -> None:
    """Load every installed plugin once: entry points first, then plugin folders (sorted)."""
    global _loaded_once
    _loaded_once = True
    _register_builtin_voices()
    try:
        entry_points = sorted(importlib.metadata.entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name)
    except Exception:  # a broken environment must not stop the editor
        log.exception("cannot list plugin entry points")
        entry_points = []
    approvals.clear()
    approvals.update(plugin_manifest.load_approvals())
    for entry in entry_points:
        plugin = f"entry point {entry.name}"
        if _admit(plugin, lambda entry=entry: _entry_point_manifest(entry)):
            _load(plugin, lambda entry=entry: _run_entry_point(entry))
    for folder in folders():
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.py")):
            if _admit(str(path), lambda path=path: plugin_manifest.manifest_path_for_file(path)):
                _load(str(path), lambda path=path: load_file(path))


def app_version() -> str:
    from . import __version__  # the package is imported by then; read late so tests can change it

    return __version__


def _admit(plugin: str, where: Callable[[], Path | None]) -> bool:
    """Read ``plugin``'s manifest (before any of its code runs) and say whether it may load: it has no
    manifest (marked), or its manifest is valid, fits this app version and its permissions were approved."""
    manifests.pop(plugin, None)
    pending.pop(plugin, None)
    try:
        path = where()
        manifest = plugin_manifest.read_manifest(path) if path is not None else None
    except plugin_manifest.ManifestError as exc:
        problems[plugin] = f"broken manifest: {exc}"
        log.warning("plugin %s skipped: broken manifest: %s", plugin, exc)
        return False
    manifests[plugin] = manifest
    if manifest is None:
        return True
    reason = plugin_manifest.incompatibility(manifest, app_version())
    if reason:
        problems[plugin] = reason
        log.warning("plugin %s skipped: %s", plugin, reason)
        return False
    if not plugin_manifest.is_approved(approvals.get(plugin), manifest):
        pending[plugin] = manifest
        log.info(
            "plugin %s waits for approval of %s", plugin, ", ".join(manifest.permissions) or "no permissions"
        )
        return False
    return True


def approve(plugin: str) -> Manifest:
    """The user approved a pending plugin's permissions: store it (it loads at the next start)."""
    manifest = pending.pop(plugin)
    approvals.clear()
    approvals.update(plugin_manifest.load_approvals())  # another window may have approved one meanwhile
    approvals[plugin] = plugin_manifest.approval_record(manifest)
    plugin_manifest.save_approvals(approvals)
    approved[plugin] = manifest
    return manifest


def _entry_point_manifest(entry) -> Path | None:
    """``plugin.json`` in an entry point's top-level package, or ``<module>.plugin.json`` beside a single
    module, found without importing it."""
    module = getattr(entry, "module", None)
    if not module:
        return None
    try:
        spec = importlib.util.find_spec(module.split(".")[0])
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None
    if spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))) / plugin_manifest.PACKAGE_MANIFEST
    if spec.origin and spec.origin.endswith(".py"):
        return plugin_manifest.manifest_path_for_file(Path(spec.origin))
    return None


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
