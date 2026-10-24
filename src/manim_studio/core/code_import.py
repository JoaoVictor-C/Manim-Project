"""What importing a code file can become, and the choice the import window hands back (P12.4).

A file is *inspected* (syntax only, ``code_files.inspect``) and the window offers what it can become:
a **Python object** (``PARAMS`` + ``build(p)``), a **scene** (a code layer holding one Manim scene), or
just a **preset** in the library. The one the file looks like is preselected; the others are offered
only when they are possible, and the reason is given when they are not. Pure: no Qt, nothing runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import code_files, scene_import

OBJECT, SCENE, PRESET = "object", "scene", "preset"
AS_LABELS = {OBJECT: "Python object", SCENE: "Manim scene (code layer)", PRESET: "Preset only"}


@dataclass(frozen=True)
class ImportItem:
    """One thing to import: its text and where it came from (a path, a URL or a label)."""

    source: str
    origin: str  # shown to the user: a file name or URL
    filename: str = ""  # names it when nothing better is found

    @property
    def inspection(self) -> code_files.Inspection:
        return code_files.inspect(self.source, self.filename or self.origin)


@dataclass(frozen=True)
class ImportChoice:
    """What the user decided for one item."""

    item: ImportItem
    name: str
    as_: str  # OBJECT, SCENE or PRESET
    scenes: tuple[str, ...] = ()  # SCENE (and PRESET of a scene): which scene classes, one layer each
    appear: float | None = None  # seconds; None: when it fits / the playhead
    position: tuple[float, float] | None = None  # scene units; None: where it fits
    trust: bool = False  # run it without asking
    also_preset: bool = False  # keep a copy in the library as well


def possible(inspection: code_files.Inspection) -> dict[str, str | None]:
    """For each ``as_``: None when it is possible, else why not."""
    can_object = inspection.kind == "object"
    can_scene = bool(inspection.scenes)
    if inspection.kind == "unknown":
        why = inspection.problem or "the file has neither a build(p) function nor a Manim Scene class"
        return {OBJECT: why, SCENE: why, PRESET: why}
    return {
        OBJECT: None
        if can_object
        else "it has no build(p) function (a Python object needs PARAMS and build)",
        SCENE: None if can_scene else "it has no Manim Scene class",
        PRESET: None,
    }


def detected(inspection: code_files.Inspection) -> str | None:
    """What the file looks like: ``OBJECT`` or ``SCENE``; None when it is neither."""
    return {"object": OBJECT, "scene": SCENE}.get(inspection.kind)


def preset_kind(inspection: code_files.Inspection) -> str:
    """The library kind of a preset made from this file."""
    return "scene" if inspection.scenes else "object"


def code_for(item: ImportItem, scene: str | None = None) -> str:
    """The text a layer or preset from ``item`` holds: without a byte-order mark, with plain newlines
    (the editor shows them so; CRLF text would look edited at once) and, for a scene, with only that
    scene class kept (a code layer holds exactly one scene, ADR 0019). Raises ``ValueError`` with the
    reason when a scene cannot be separated."""
    text = item.source.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if scene is None:
        return text
    return scene_import.scene_code(text, scene)


def validate(choice: ImportChoice) -> str | None:
    """Why ``choice`` cannot be carried out (None: it can)."""
    inspection = choice.item.inspection
    if not choice.name.strip():
        return "Give it a name"
    reason = possible(inspection)[choice.as_]
    if reason is not None:
        return reason
    if choice.as_ == SCENE or (choice.as_ == PRESET and inspection.scenes):
        scenes = choice.scenes or inspection.scenes[:1]
        for scene in scenes:
            if scene not in inspection.scenes:
                return f"the file has no scene {scene!r}"
            try:
                code_for(choice.item, scene)
            except ValueError as error:
                return str(error)
    return None


def layers_of(choice: ImportChoice) -> list[tuple[str, str, str]]:
    """The layers an ``OBJECT`` or ``SCENE`` choice makes, as (name, spec type, code): one for an
    object, one per chosen scene (named after it, or after the choice when it is the only one)."""
    inspection = choice.item.inspection
    if choice.as_ == OBJECT:
        return [(choice.name, "Python", code_for(choice.item))]
    scenes = choice.scenes or inspection.scenes[:1]
    out = []
    for scene in scenes:
        name = choice.name if len(scenes) == 1 else f"{choice.name} - {scene}"
        out.append((name, "Code", code_for(choice.item, scene)))
    return out


def presets_of(choice: ImportChoice) -> list[tuple[str, str, str]]:
    """The library entries a choice adds, as (name, kind, code): for ``PRESET`` always, for the others
    when ``also_preset`` is set."""
    if choice.as_ != PRESET and not choice.also_preset:
        return []
    inspection = choice.item.inspection
    if inspection.scenes:
        scenes = choice.scenes or inspection.scenes[:1]
        return [
            (
                choice.name if len(scenes) == 1 else f"{choice.name} - {scene}",
                "scene",
                code_for(choice.item, scene),
            )
            for scene in scenes
        ]
    return [(choice.name, "object", code_for(choice.item))]
