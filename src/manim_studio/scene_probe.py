"""Facts about a scene at the boundaries of its top-level statements (ADR 0061).

The code runner uses a ``ProbeRecorder`` while it renders a code layer. Before each top-level statement of
``construct`` runs it records how many frames have been emitted and a survey of what is alive in the scene:
a digest of everything, a digest of what is *visible*, whether an invisible object's updater can reach a
visible one, and how many updaters are running. ``core.scene_analysis`` reads them (from the cache entry) to
find the points where a long scene can be cut into independent chapters.

Only line events of ``construct``'s own code object are watched (``sys.monitoring``, Python 3.12+), so the
rest of the render pays nothing. Everything here runs in the render process, next to the user's code.
"""

from __future__ import annotations

import ast
import hashlib
import sys
from collections.abc import Callable
from typing import Any

TOOL_NAME = "manim-studio-probe"


def statement_starts(code: str, class_name: str) -> dict[int, int]:
    """First line of each top-level statement of ``class_name.construct`` -> its index (empty if none)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "construct":
                    return {stmt.lineno: i for i, stmt in enumerate(item.body)}
    return {}


def _family(mob) -> list:
    return mob.get_family()


def _drawn(member) -> bool:
    """Does this family member put pixels on the frame?"""
    import manim as m
    from manim.mobject.types.image_mobject import AbstractImageMobject

    if isinstance(member, AbstractImageMobject):
        return True
    if not isinstance(member, m.VMobject) or len(member.points) == 0:
        return False
    fill = getattr(member, "fill_rgbas", None)
    stroke = getattr(member, "stroke_rgbas", None)
    width = getattr(member, "stroke_width", 0)
    filled = fill is not None and len(fill) > 0 and float(fill[:, 3].max()) > 0
    stroked = (
        stroke is not None and len(stroke) > 0 and float(stroke[:, 3].max()) > 0 and float(max(width, 0)) > 0
    )
    return bool(filled or stroked)


def _feed(h, member) -> None:
    """Everything about a family member that can change a pixel."""
    h.update(type(member).__name__.encode())
    for name in ("points", "fill_rgbas", "stroke_rgbas", "background_stroke_rgbas", "pixel_array"):
        value = getattr(member, name, None)
        if value is not None and hasattr(value, "tobytes"):
            h.update(value.tobytes())
    for name in ("stroke_width", "background_stroke_width", "sheen_factor", "z_index", "sheen_direction"):
        value = getattr(member, name, None)
        if value is not None:
            h.update(repr(value.tolist() if hasattr(value, "tolist") else value).encode())


def digest_of(mobjects) -> str:
    h = hashlib.blake2b(digest_size=12)
    for mob in mobjects:
        for member in _family(mob):
            _feed(h, member)
        h.update(b"|")
    return h.hexdigest()


def _referenced(updater) -> list:
    """Mobjects an updater function can see: its closure cells and the module names it uses."""
    import manim as m

    found: list = []
    function = getattr(updater, "__func__", updater)
    values = []
    for cell in getattr(function, "__closure__", None) or ():
        try:
            values.append(cell.cell_contents)
        except ValueError:
            continue
    code = getattr(function, "__code__", None)
    if code is not None:
        glob = getattr(function, "__globals__", {})
        values.extend(glob[name] for name in code.co_names if name in glob)
    for value in values:
        if isinstance(value, m.Mobject):
            found.append(value)
        elif isinstance(value, list | tuple | set):
            found.extend(v for v in value if isinstance(v, m.Mobject))
        elif isinstance(value, dict):
            found.extend(v for v in value.values() if isinstance(v, m.Mobject))
    return found


def local_states(names: dict[str, Any]) -> dict[str, str]:
    """A digest of each local variable of ``construct`` that holds mobjects: how far each has got."""
    import manim as m

    out: dict[str, str] = {}
    for name, value in names.items():
        if name.startswith("__") or name == "self":
            continue
        try:
            if isinstance(value, m.Mobject):
                out[name] = digest_of([value])
            elif isinstance(value, list | tuple) and value and all(isinstance(v, m.Mobject) for v in value):
                out[name] = digest_of(list(value))
        except Exception:  # an odd object: no state recorded, so nothing can lean on it
            continue
    return out


def survey(scene, names: dict[str, Any] | None = None) -> dict[str, Any]:
    """The state of ``scene`` that decides whether a later part of it can start from scratch."""
    top = list(scene.mobjects)
    visible_top = [mob for mob in top if any(_drawn(member) for member in _family(mob))]
    visible_ids = {id(member) for mob in visible_top for member in _family(mob)}
    updaters = len(scene.updaters)
    visible_updaters = 0
    entangled = False
    for mob in top:
        for member in _family(mob):
            updaters += len(member.updaters)
            if id(member) in visible_ids:
                visible_updaters += len(member.updaters)
                continue
            for updater in member.updaters:  # an invisible object that can move a visible one
                for target in _referenced(updater):
                    if any(id(t) in visible_ids for t in _family(target)):
                        entangled = True
    camera = getattr(scene.camera, "frame", None)
    # Manim draws a wait as real frames when anything can change (a time-based updater, on the scene or any
    # mobject in it) and as one frozen frame otherwise, and the two round the duration differently: a chapter
    # must be in the same mode as the whole scene was.
    updating = bool(
        scene.always_update_mobjects
        or scene.updaters
        or any(mob.has_time_based_updater() for mob in scene.get_mobject_family_members())
    )
    return {
        "all": digest_of(top),
        "visible": digest_of(visible_top),
        "objects": len(top),
        "shown": len(visible_top),
        "updaters": updaters,
        "visible_updaters": visible_updaters,
        "scene_updaters": len(scene.updaters),
        "updating": updating,
        "entangled": entangled,
        "camera": digest_of([camera]) if camera is not None else "",
        "names": local_states(names or {}),
    }


class ProbeRecorder:
    """``with ProbeRecorder(scene, starts, frames, sink):`` records a probe before each statement."""

    def __init__(self, scene, starts: dict[int, int], frames: Callable[[], int], sink: list[dict]) -> None:
        self.scene, self.starts, self.frames, self.sink = scene, starts, frames, sink
        self._last = -1
        self._active = False

    def _line(self, code, line: int):
        index = self.starts.get(line)
        if index is None or index <= self._last:  # a loop header comes round again: the same statement
            return None
        self._last = index
        entry = {
            "stmt": index,
            "line": line,
            "frame": self.frames(),
            "t": float(self.scene.renderer.time),
        }
        try:
            entry.update(survey(self.scene, dict(sys._getframe(1).f_locals)))
        except Exception as error:  # a probe never breaks a render: the boundary is just not a cut point
            entry["error"] = f"{type(error).__name__}: {error}"
        self.sink.append(entry)
        return None

    def __enter__(self):
        if not self.starts or not hasattr(sys, "monitoring"):
            return self
        monitoring = sys.monitoring
        tool = monitoring.PROFILER_ID
        try:
            monitoring.use_tool_id(tool, TOOL_NAME)
        except ValueError:  # another profiler holds it: no probes, the render goes on
            return self
        monitoring.register_callback(tool, monitoring.events.LINE, self._line)
        monitoring.set_local_events(tool, self.scene.construct.__func__.__code__, monitoring.events.LINE)
        self._active = True
        return self

    def __exit__(self, *exc) -> None:
        if self._active:
            monitoring = sys.monitoring
            tool = monitoring.PROFILER_ID
            monitoring.set_local_events(tool, self.scene.construct.__func__.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.LINE, None)
            monitoring.free_tool_id(tool)
            self._active = False
