"""Portable project bundles (ADR 0077): one ``.msbundle`` file that carries a project and its files.

A project points at files on the disk it was made on: the sounds on the timeline (``AudioClip.path``,
ADR 0034) and the pictures of image and SVG layers (``params.path``, ADR 0027). Code layers, Python objects
and helpers (ADR 0019, 0051, 0058) are inside the project file already, and fonts are named, not files.
``external_references`` lists every file a project needs; it is the only place that knows where they are.

A bundle is a zip file:

* ``manifest.json`` - ``{"format": "manim-studio-bundle", "version": 1, "app_version", "name", "project":
  {"path", "sha256", "size"}, "files": [...], "snapshots": [...]}``; each file has its ``path`` in the bundle
  (``assets/<name>``, or ``null`` when it was missing), ``sha256``, ``size``, the ``original`` path, which
  layers or sounds use it (``used_by``) and ``missing``;
* ``project.json`` - the project with every bundled path rewritten to ``assets/<name>``;
* ``assets/...`` - the files, once each however many layers use them;
* ``snapshots/...`` - when asked for, the project's snapshots (ADR 0068), their paths rewritten the same way.

A missing file does not stop the bundle: the manifest marks it and the project keeps the original path.

Opening a bundle unpacks it into a new folder (``open_bundle``); nothing that exists is overwritten. Every
entry is checked before anything is written - no absolute path, no ``..``, nothing the manifest does not list,
a size cap - and every file's sha256 is checked against the manifest. Trust (ADR 0019) is not part of a
bundle: it is kept on this computer by the hash of the code, a bundle has no way to add to it, and opening
one never reads or writes it, so the code inside is asked about like the code of any other file.

Pure: no Qt, no Manim.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..model import snapshots
from ..model.schema import MEDIA_TYPES, Project

EXTENSION = ".msbundle"
FORMAT = "manim-studio-bundle"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
PROJECT = "project.json"
ASSETS = "assets"
SNAPSHOTS = "snapshots"
MAX_BYTES = 4 * 1024**3  # everything unpacked together
MAX_ENTRIES = 10_000
MAX_JSON = 64 * 1024**2  # the manifest, the project, a snapshot
_CHUNK = 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9._ ()+-]+")


class BundleError(ValueError):
    """The bundle cannot be written or opened; the message is for the user."""


@dataclass(frozen=True)
class Reference:
    """A file the project needs: ``kind`` is ``"audio"`` or the layer's type (``ImageMobject``,
    ``SVGMobject``), ``owner`` the sound's or layer's id, ``label`` how the editor names it."""

    kind: str
    owner: str
    label: str
    path: str


@dataclass
class BundleReport:
    target: Path
    files: list[dict] = field(default_factory=list)  # the manifest's entries
    missing: list[Reference] = field(default_factory=list)
    snapshots: int = 0


@dataclass
class OpenedBundle:
    folder: Path
    project_path: Path
    project: Project
    missing: list[str] = field(default_factory=list)  # original paths the bundle did not carry
    snapshots: int = 0


# -- what a project refers to ----------------------------------------------------------------------


def external_references(project: Project) -> list[Reference]:
    """Every file outside the project file that ``project`` uses, in project order (sounds after layers)."""
    found = []
    for layer in project.layers:
        if layer.spec is not None and layer.spec.type in MEDIA_TYPES:
            path = str(layer.spec.params.get("path") or "")
            if path:
                found.append(Reference(layer.spec.type, layer.id, layer.label, path))
    found += [
        Reference("audio", clip.id, clip.name or clip.id, clip.path) for clip in project.audio if clip.path
    ]
    return found


def with_paths(project: Project, paths: Mapping[str, str]) -> Project:
    """``project`` with every file path that is a key of ``paths`` replaced by its value."""
    layers = []
    for layer in project.layers:
        spec = layer.spec
        old = str(spec.params.get("path") or "") if spec is not None and spec.type in MEDIA_TYPES else ""
        if old in paths:
            spec = spec.model_copy(update={"params": {**spec.params, "path": paths[old]}})
            layer = layer.model_copy(update={"spec": spec})
        layers.append(layer)
    audio = [
        clip.model_copy(update={"path": paths[clip.path]}) if clip.path in paths else clip
        for clip in project.audio
    ]
    return project.model_copy(update={"layers": layers, "audio": audio})


# -- writing ------------------------------------------------------------------------------------


def _source(path: str, base: Path | None) -> Path:
    source = Path(path)
    if not source.is_absolute() and base is not None:
        source = base / source
    return source


def missing_paths(references: Iterable[Reference], project_path: str | Path | None = None) -> set[str]:
    """The paths of ``references`` that are not a file (relative ones read from the project's folder)."""
    base = Path(project_path).parent if project_path is not None else None
    return {ref.path for ref in references if not _source(ref.path, base).is_file()}


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _asset_name(path: str, taken: set[str]) -> str:
    stem, dot, extension = PurePosixPath(path.replace("\\", "/")).name.rpartition(".")
    if not dot:
        stem, extension = extension, ""
    stem = _SAFE.sub("_", stem).strip(" .")[:60] or "file"
    extension = _SAFE.sub("", extension)[:12]
    suffix = f".{extension}" if extension else ""
    name, n = f"{stem}{suffix}", 1
    while name.lower() in taken:
        n += 1
        name = f"{stem}-{n}{suffix}"
    taken.add(name.lower())
    return name


def _copy(zf: zipfile.ZipFile, source: Path, name: str) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with source.open("rb") as read, zf.open(name, "w", force_zip64=True) as write:
        while chunk := read.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
            write.write(chunk)
    return digest.hexdigest(), size


def _write_text(zf: zipfile.ZipFile, name: str, text: str) -> dict:
    data = text.encode("utf-8")
    zf.writestr(name, data)
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def build_bundle(
    project: Project,
    target: str | Path,
    *,
    name: str | None = None,
    project_path: str | Path | None = None,
    include_snapshots: bool = False,
    app_version: str | None = None,
) -> BundleReport:
    """Write ``project`` and the files it uses to the bundle ``target`` (replaced whole, or left as it was).

    ``project_path`` is the project's file: relative media paths are read from its folder and, with
    ``include_snapshots``, its snapshots are bundled too. Missing files are listed in the report and marked
    in the manifest; the bundle is written all the same."""
    if app_version is None:
        from ... import __version__ as app_version
    target = Path(target)
    base = Path(project_path).parent if project_path is not None else None
    taken_snaps = []
    if include_snapshots and project_path is not None:
        for snapshot in snapshots.listing(project_path):
            with contextlib.suppress(snapshots.SnapshotError):  # a damaged one is left out, as the list does
                taken_snaps.append((snapshot, snapshots.load(snapshot)))
    # One entry per file, however many layers, sounds and snapshots use it.
    entries: dict[str, dict] = {}
    names: set[str] = set()
    report = BundleReport(target)
    rewrites: dict[str, str] = {}  # path in a project -> path in the bundle

    def collect(refs: Iterable[Reference], where: str | None) -> None:
        for ref in refs:
            source = _source(ref.path, base)
            key = _key(source)
            entry = entries.get(key)
            if entry is None:
                missing = not source.is_file()
                entry = {
                    "path": None if missing else f"{ASSETS}/{_asset_name(ref.path, names)}",
                    "original": ref.path,
                    "used_by": [],
                    "missing": missing,
                    "_source": source,
                }
                entries[key] = entry
            used = {"kind": ref.kind, "id": ref.owner, "name": ref.label}
            if where is not None:
                used["snapshot"] = where
            entry["used_by"].append(used)
            if entry["missing"]:
                if where is None:
                    report.missing.append(ref)
            else:
                rewrites[ref.path] = entry["path"]

    collect(external_references(project), None)
    for snapshot, snap_project in taken_snaps:
        collect(external_references(snap_project), snapshot.name)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex[:6]}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            files = []
            for entry in entries.values():
                source = entry.pop("_source")
                if not entry["missing"]:
                    try:
                        entry["sha256"], entry["size"] = _copy(zf, source, entry["path"])
                    except OSError as error:
                        raise BundleError(f"cannot read {entry['original']}: {error}") from None
                files.append(entry)
            project_entry = _write_text(
                zf, PROJECT, with_paths(project, rewrites).model_dump_json(by_alias=True, indent=1)
            )
            snap_entries = []
            for snapshot, snap_project in taken_snaps:
                text = with_paths(snap_project, rewrites).model_dump_json(by_alias=True, indent=1)
                snap_entries.append(_write_text(zf, f"{SNAPSHOTS}/{snapshot.id}.json", text))
                meta = snapshot.path.with_name(f"{snapshot.id}{snapshots.META}").read_text(encoding="utf-8")
                snap_entries.append(_write_text(zf, f"{SNAPSHOTS}/{snapshot.id}{snapshots.META}", meta))
            manifest = {
                "format": FORMAT,
                "version": FORMAT_VERSION,
                "app_version": app_version,
                "name": name or (Path(project_path).stem if project_path is not None else "project"),
                "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "project": project_entry,
                "files": files,
                "snapshots": snap_entries,
            }
            zf.writestr(MANIFEST, json.dumps(manifest, indent=1))
        os.replace(temporary, target)
    except OSError as error:
        raise BundleError(f"cannot write {target.name}: {error}") from None
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
    report.files = files
    report.snapshots = len(taken_snaps)
    return report


# -- opening ------------------------------------------------------------------------------------


def safe_entry(name: str) -> bool:
    """A zip entry name that stays inside the folder it is unpacked to: relative, forward slashes, no
    ``..`` or ``.``, no drive, no empty part."""
    if not name or "\\" in name or ":" in name or name.startswith("/") or "\x00" in name:
        return False
    parts = name.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _single(name: str, folder: str) -> bool:
    """``<folder>/<one safe part>``."""
    return safe_entry(name) and name.count("/") == 1 and name.startswith(f"{folder}/")


def _read(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise BundleError(f"{info.filename} is too large")
    with zf.open(info) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit or len(data) != info.file_size:
        raise BundleError(f"{info.filename} is not the size the bundle says")
    return data


def _check(data: bytes, entry: dict) -> None:
    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
        raise BundleError(f"{entry.get('path')} was changed: its sha256 does not match the manifest")


def read_manifest(zf: zipfile.ZipFile) -> dict:
    """The bundle's manifest, checked: its format and version, and the shape of every entry."""
    try:
        info = zf.getinfo(MANIFEST)
    except KeyError:
        raise BundleError("this is not a Manim Studio bundle (it has no manifest)") from None
    try:
        manifest = json.loads(_read(zf, info, MAX_JSON).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise BundleError(f"the manifest cannot be read: {error}") from None
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BundleError("this is not a Manim Studio bundle")
    version = manifest.get("version")
    if not isinstance(version, int) or version < 1:
        raise BundleError("the bundle's manifest has no version")
    if version > FORMAT_VERSION:
        raise BundleError(
            f"the bundle was made by a newer Manim Studio (format {version}); update to open it"
        )
    project = manifest.get("project")
    if not isinstance(project, dict) or project.get("path") != PROJECT:
        raise BundleError("the bundle's manifest names no project")
    files, snaps = manifest.get("files", []), manifest.get("snapshots", [])
    if not isinstance(files, list) or not isinstance(snaps, list):
        raise BundleError("the bundle's manifest is damaged")
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("original", ""), str):
            raise BundleError("the bundle's manifest is damaged")
        if entry.get("missing"):
            continue
        if not isinstance(entry.get("path"), str) or not _single(entry["path"], ASSETS):
            raise BundleError(f"the bundle lists a file outside its assets: {entry.get('path')!r}")
    for entry in snaps:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not _single(path, SNAPSHOTS) or not path.endswith(".json"):
            raise BundleError(f"the bundle lists a snapshot it cannot hold: {path!r}")
    return manifest


def _fresh_folder(parent: Path, stem: str) -> Path:
    stem = _SAFE.sub("_", stem).strip(" .")[:80] or "bundle"
    parent.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        folder = parent / (stem if n == 1 else f"{stem} ({n})")
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue
    raise BundleError(f"no free folder name for {stem!r} in {parent}")


def _stem(bundle: Path) -> str:
    name = bundle.name
    for extension in (EXTENSION, ".zip"):
        if name.lower().endswith(extension):
            return name[: -len(extension)]
    return bundle.stem


def open_bundle(
    bundle: str | Path, parent: str | Path | None = None, *, max_bytes: int = MAX_BYTES
) -> OpenedBundle:
    """Unpack ``bundle`` into a new folder in ``parent`` (default: beside the bundle) and return the project,
    its paths pointing at the unpacked files. Raises ``BundleError`` - and leaves nothing behind - when the
    bundle is not one, is unsafe, too large, or a file does not match its sha256."""
    bundle = Path(bundle)
    try:
        zf = zipfile.ZipFile(bundle)
    except (OSError, zipfile.BadZipFile) as error:
        raise BundleError(f"cannot read {bundle.name}: {error}") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise BundleError("the bundle has too many files")
        seen = set()
        for info in infos:
            if not safe_entry(info.filename) or info.is_dir():
                raise BundleError(f"the bundle holds an unsafe path: {info.filename!r}")
            if info.filename in seen:
                raise BundleError(f"the bundle holds {info.filename!r} twice")
            seen.add(info.filename)
        if sum(info.file_size for info in infos) > max_bytes:
            raise BundleError(f"the bundle unpacks to more than {max_bytes // 1024**2} MB")
        manifest = read_manifest(zf)
        assets = [entry for entry in manifest.get("files", []) if not entry.get("missing")]
        listed = (
            {MANIFEST, PROJECT} | {e["path"] for e in assets} | {e["path"] for e in manifest["snapshots"]}
        )
        unknown = sorted(seen - listed)
        if unknown:
            raise BundleError(f"the bundle holds files its manifest does not list: {', '.join(unknown[:5])}")
        absent = sorted(listed - seen)
        if absent:
            raise BundleError(f"the bundle is missing files its manifest lists: {', '.join(absent[:5])}")
        project_data = _read(zf, zf.getinfo(PROJECT), MAX_JSON)
        _check(project_data, manifest["project"])
        try:
            project = Project.model_validate_json(project_data)
        except ValueError as error:
            raise BundleError(f"the bundle's project cannot be read: {error}") from None
        stem = str(manifest.get("name") or "") or _stem(bundle)
        folder = _fresh_folder(Path(parent) if parent is not None else bundle.parent, stem)
        try:
            return _unpack(zf, manifest, assets, project, folder, folder.name)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)  # the folder is new: nothing of the user's is in it
            raise


def _unpack(
    zf: zipfile.ZipFile, manifest: dict, assets: list[dict], project: Project, folder: Path, stem: str
) -> OpenedBundle:
    rewrites: dict[str, str] = {}
    for entry in assets:
        info = zf.getinfo(entry["path"])
        target = folder / Path(*entry["path"].split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        with zf.open(info) as read, target.open("xb") as write:
            while chunk := read.read(_CHUNK):
                size += len(chunk)
                if size > info.file_size:
                    raise BundleError(f"{entry['path']} is not the size the bundle says")
                digest.update(chunk)
                write.write(chunk)
        if digest.hexdigest() != entry.get("sha256"):
            raise BundleError(f"{entry['path']} was changed: its sha256 does not match the manifest")
        rewrites[entry["path"]] = str(target)
    project_path = folder / f"{stem}.json"
    _create(
        project_path, with_paths(project, rewrites).model_dump_json(by_alias=True, indent=1).encode("utf-8")
    )
    count = 0
    if manifest["snapshots"]:
        snap_folder = snapshots.folder_for(project_path)
        snap_folder.mkdir()
        for entry in manifest["snapshots"]:
            data = _read(zf, zf.getinfo(entry["path"]), MAX_JSON)
            _check(data, entry)
            name = entry["path"].split("/", 1)[1]
            if not name.endswith(snapshots.META):
                try:
                    snap = Project.model_validate_json(data)
                except ValueError as error:
                    raise BundleError(f"the snapshot {name} cannot be read: {error}") from None
                data = with_paths(snap, rewrites).model_dump_json(by_alias=True, indent=1).encode("utf-8")
                count += 1
            _create(snap_folder / name, data)
    missing = [str(e.get("original", "")) for e in manifest.get("files", []) if e.get("missing")]
    return OpenedBundle(folder, project_path, with_paths(project, rewrites), missing, count)


def _create(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:  # never over a file that is there
        handle.write(data)
