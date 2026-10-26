"""What exporting code writes (P12.4): the files, how they look, and an index others can import.

An *entry* is a code layer, a Python object or a preset the user ticked. ``prepare`` turns the entries
into ``(stem, text)`` pairs for ``code_files.export_files`` - names made valid and unique, line endings
and an optional first-line comment as the user chose - and ``manifest`` writes the index file that
``preset_online`` reads, so a folder can be put on the internet and imported again by its link.
Pure: no Qt.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import code_files

HEADER = "# {name} - exported from Manim Studio\n"
MANIFEST_NAME = "index"


@dataclass(frozen=True)
class ExportEntry:
    key: str  # a layer id or a preset id
    name: str
    kind: str  # "object" or "scene"
    source: str
    group: str = "project"  # "project" (a layer) or "preset"
    description: str = ""


@dataclass(frozen=True)
class ExportOptions:
    newline: str = "\n"  # "\n" or "\r\n"
    header: bool = False  # a first-line comment naming the entry
    manifest: bool = False  # also write index.json, to share the folder


def prepare(entries: list[ExportEntry], options: ExportOptions | None = None) -> list[tuple[str, str]]:
    """``(stem, text)`` for each entry, the stems valid on Windows and different from each other."""
    options = options or ExportOptions()
    out, taken = [], []
    for entry in entries:
        filename = code_files.free_name(
            code_files.safe_stem(entry.name, entry.key) + code_files.EXTENSION, taken
        )
        taken.append(filename)
        out.append((os.path.splitext(filename)[0], _text(entry, options)))
    return out


def _text(entry: ExportEntry, options: ExportOptions) -> str:
    text = entry.source.replace("\r\n", "\n").replace("\r", "\n")
    if options.header and not text.startswith("# " + entry.name):
        text = HEADER.format(name=entry.name) + text
    if options.newline == "\r\n":
        text = text.replace("\n", "\r\n")
    return text


def manifest(entries: list[ExportEntry], title: str = "") -> str:
    """The index of an export, in the format ``preset_online.resolve`` reads (format 1)."""
    names = [stem + code_files.EXTENSION for stem, _ in prepare(entries)]
    presets = []
    for entry, filename in zip(entries, names, strict=True):
        item = {"name": entry.name, "file": filename, "kind": entry.kind}
        description = entry.description or code_files.inspect(entry.source, filename).summary
        if description:
            item["description"] = description
        presets.append(item)
    data: dict = {"format": 1}
    if title:
        data["name"] = title
    data["presets"] = presets
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
