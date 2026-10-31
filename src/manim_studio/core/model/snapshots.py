"""Named project snapshots (ADR 0068): milestones such as "rough cut" or "final narration".

A snapshot is a copy of the whole project kept beside its file, apart from undo: undo ends with the session, a
snapshot stays until the user deletes it. For ``scene.json`` they live in ``scene.snapshots/``, two files
each, written to a temporary name and moved into place (the project first, the sidecar last, as recovery
copies are, [0038](../../../docs/adr/0038-clipboard-and-recovery.md)):

* ``<id>.json`` - the project, a normal project file;
* ``<id>.meta.json`` - ``{"name": ..., "saved_at": ..., "layers": n, "duration": s}``.

A snapshot without its sidecar is not listed; a sidecar without its project is dropped. ``compare`` says what
differs between two projects in the words of the editor: layers added, removed, changed in what they are, in
their timing or in their keys, and the canvas, sound, subtitles and markers. No Qt, no Manim.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .schema import Layer, Project

SUFFIX = ".snapshots"
META = ".meta.json"
MAX_NAME = 80


@dataclass(frozen=True)
class Snapshot:
    id: str
    name: str
    saved_at: float
    layers: int
    duration: float
    path: Path  # the project file


class SnapshotError(ValueError):
    """The snapshot cannot be made or read; the message is for the user."""


def folder_for(project_path: str | Path) -> Path:
    """Where the snapshots of ``project_path`` live (``scene.json`` -> ``scene.snapshots``)."""
    path = Path(project_path)
    return path.with_name(path.stem + SUFFIX)


def clean_name(name: str) -> str:
    text = re.sub(r"\s+", " ", name).strip()[:MAX_NAME]
    if not text:
        raise SnapshotError("give the snapshot a name")
    return text


def save(project_path: str | Path, project: Project, name: str, now: float | None = None) -> Snapshot:
    """Keep ``project`` as a snapshot called ``name`` (names need not be unique: ``id`` is)."""
    name = clean_name(name)
    folder = folder_for(project_path)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.time() if now is None else now
    snapshot_id = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(stamp))}-{uuid.uuid4().hex[:6]}"
    meta = {
        "name": name,
        "saved_at": stamp,
        "layers": len(project.layers),
        "duration": project.canvas.duration,
    }
    _write(folder / f"{snapshot_id}.json", project.model_dump_json(by_alias=True, indent=1))
    _write(folder / f"{snapshot_id}{META}", json.dumps(meta))
    return Snapshot(
        snapshot_id, name, stamp, meta["layers"], meta["duration"], folder / f"{snapshot_id}.json"
    )


def listing(project_path: str | Path) -> list[Snapshot]:
    """The snapshots of a project, newest first; unreadable or half-written ones are left out."""
    folder = folder_for(project_path)
    found = []
    for sidecar in folder.glob(f"*{META}") if folder.is_dir() else ():
        snapshot_id = sidecar.name.removesuffix(META)
        project_file = folder / f"{snapshot_id}.json"
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            if not project_file.is_file():
                continue
            found.append(
                Snapshot(
                    snapshot_id,
                    str(meta["name"]),
                    float(meta["saved_at"]),
                    int(meta["layers"]),
                    float(meta["duration"]),
                    project_file,
                )
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(found, key=lambda s: s.saved_at, reverse=True)


def load(snapshot: Snapshot) -> Project:
    try:
        return Project.model_validate_json(snapshot.path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SnapshotError(f"cannot read the snapshot {snapshot.name!r}: {error}") from None


def rename(snapshot: Snapshot, name: str) -> Snapshot:
    name = clean_name(name)
    sidecar = snapshot.path.with_name(f"{snapshot.id}{META}")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["name"] = name
    _write(sidecar, json.dumps(meta))
    return Snapshot(snapshot.id, name, snapshot.saved_at, snapshot.layers, snapshot.duration, snapshot.path)


def delete(snapshot: Snapshot) -> None:
    """Remove a snapshot (the sidecar first, so it is never listed half-gone)."""
    snapshot.path.with_name(f"{snapshot.id}{META}").unlink(missing_ok=True)
    snapshot.path.unlink(missing_ok=True)


def _write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:6]}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


# -- comparing -----------------------------------------------------------------------------------


@dataclass
class Difference:
    """What differs between an older project and a newer one."""

    added: list[str] = field(default_factory=list)  # layer names
    removed: list[str] = field(default_factory=list)
    changed: dict[str, list[str]] = field(default_factory=dict)  # layer name -> what changed
    scene: list[str] = field(default_factory=list)  # canvas, sound, subtitles, markers, camera

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.scene)

    def lines(self) -> list[str]:
        out = [f"+ {name}" for name in self.added] + [f"- {name}" for name in self.removed]
        out += [f"~ {name}: {', '.join(what)}" for name, what in self.changed.items()]
        out += [f"* {line}" for line in self.scene]
        return out or ["No differences."]


def compare(old: Project, new: Project) -> Difference:
    """What changed going from ``old`` to ``new``."""
    diff = Difference()
    before = {layer.id: layer for layer in old.layers}
    after = {layer.id: layer for layer in new.layers}
    diff.added = [_label(after[i]) for i in after if i not in before]
    diff.removed = [_label(before[i]) for i in before if i not in after]
    for layer_id in after.keys() & before.keys():
        what = _layer_changes(before[layer_id], after[layer_id])
        if what:
            diff.changed[_label(after[layer_id])] = what
    for label, a, b in (
        ("canvas", old.canvas, new.canvas),
        ("camera", old.camera, new.camera),
        ("subtitle style", old.subtitle_style, new.subtitle_style),
    ):
        if a != b:
            diff.scene.append(f"{label} changed" + _canvas_detail(a, b))
    for label, a, b in (
        ("sounds", old.audio, new.audio),
        ("subtitles", old.subtitles, new.subtitles),
        ("markers", old.markers, new.markers),
    ):
        if a != b:
            diff.scene.append(f"{label}: {len(a)} -> {len(b)}" if len(a) != len(b) else f"{label} changed")
    return diff


def _label(layer: Layer) -> str:
    kind = layer.spec.type if layer.spec is not None else "part"
    return f"{layer.name or layer.id} ({kind})"


def _layer_changes(a: Layer, b: Layer) -> list[str]:
    what = []
    if a.spec != b.spec or a.style != b.style:
        what.append("what it is")
    if a.lifetime != b.lifetime or a.clips != b.clips:
        what.append("timing")
    if a.base != b.base or a.tracks != b.tracks:
        what.append("position and keys")
    if a.parent_id != b.parent_id or a.part != b.part:
        what.append("grouping")
    if a.visible != b.visible:
        what.append("visibility")
    if a.name != b.name:
        what.append("name")
    return what


def _canvas_detail(a, b) -> str:
    changes = [
        f"{key} {getattr(a, key)} -> {getattr(b, key)}"
        for key in ("width_px", "height_px", "fps", "duration", "background")
        if getattr(a, key, None) != getattr(b, key, None)
    ]
    return f" ({', '.join(changes)})" if changes else ""
