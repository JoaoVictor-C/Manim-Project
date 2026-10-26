"""The preset library (P12.2, ADR 0056): ready-made code to start from - pure, no Qt, no Manim.

A preset is a named piece of code: a Python object (``PARAMS`` + ``build(p)``, ADR 0051), a Manim
scene (a code layer, ADR 0019) or a helper (a module the project's code imports, ADR 0058). Three
origins are listed together:

* **built-in** presets come with the editor (``python_templates``); they are never saved and
  cannot be changed or removed;
* **user** presets are the ones the user saves from the Code page;
* **online** presets were downloaded from a link (``preset_online``); they are code from outside,
  untrusted until the user runs it, and keep the link they came from.

The user's and online presets live in one JSON file (``{"format": 1, "presets": [...]}``) in the
user's data folder (``%LOCALAPPDATA%/ManimStudio/presets.json`` on Windows,
``~/.local/share/manim-studio/presets.json`` elsewhere; override with ``MANIM_STUDIO_PRESETS``).
Opening the library never fails: a file that cannot be read is set aside as ``presets.json.bad``
and the library starts empty, so the user's next save does not lose the old file. Pure.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..code import python_templates
from .code_files import inspect

FORMAT = 1
KINDS = ("object", "scene", "helper")  # a helper: a module the project's code imports (ADR 0058)
SAVED_ORIGINS = ("user", "online")  # what is saved in the file; "builtin" never is


def default_path() -> Path:
    override = os.environ.get("MANIM_STUDIO_PRESETS")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ManimStudio" / "presets.json"
    return Path.home() / ".local" / "share" / "manim-studio" / "presets.json"


@dataclass(frozen=True)
class Preset:
    """One preset. ``id`` is ``builtin:<slug>``, ``user:<slug>`` or ``online:<slug>`` (unique in its
    library, and the same for as long as the preset exists, even when it is renamed)."""

    id: str
    name: str
    kind: str  # "object" | "scene" | "helper"
    code: str
    origin: str  # "builtin" | "user" | "online"
    description: str = ""
    tags: tuple[str, ...] = ()
    source_url: str = ""

    @property
    def builtin(self) -> bool:
        return self.origin == "builtin"


class PresetLibrary:
    """The built-in presets, then the saved ones in the order they were added."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()
        self._builtin = self._builtins()
        self._saved: list[Preset] = self._load()

    # -- reading -----------------------------------------------------------------------------------

    def presets(self) -> list[Preset]:
        """Every preset: the built-in ones first, then the saved ones in insertion order."""
        return [*self._builtin, *self._saved]

    def get(self, preset_id: str) -> Preset | None:
        return next((p for p in self.presets() if p.id == preset_id), None)

    # -- changing ----------------------------------------------------------------------------------

    def add(
        self,
        name: str,
        kind: str,
        code: str,
        origin: str = "user",
        description: str = "",
        tags: tuple[str, ...] | list[str] = (),
        source_url: str = "",
    ) -> Preset:
        """Save a new preset and return it. A name already used (in any letter case, by any preset)
        gets a suffix: ``Name (2)``. Raises ``ValueError`` for an empty name, a kind that is not
        ``object``/``scene``/``helper`` or an origin that is not ``user``/``online``, and ``OSError`` when the
        file cannot be written (the library is then as it was)."""
        if not name.strip():
            raise ValueError("a preset needs a name")
        if kind not in KINDS:
            raise ValueError(f"a preset's kind is 'object', 'scene' or 'helper', not {kind!r}")
        if origin not in SAVED_ORIGINS:
            raise ValueError(f"a saved preset's origin is 'user' or 'online', not {origin!r}")
        before = list(self._saved)
        preset = self._append(name, kind, code, origin, description, tags, source_url)
        self._commit(before)
        return preset

    def remove(self, preset_id: str) -> None:
        """Delete a saved preset. ``ValueError`` for a built-in one, ``KeyError`` for an unknown id."""
        index = self._index(preset_id)
        before = list(self._saved)
        del self._saved[index]
        self._commit(before)

    def rename(self, preset_id: str, new_name: str) -> Preset:
        """Give a saved preset another name (suffixed ``(2)``... when another preset has it)."""
        index = self._index(preset_id)
        if not new_name.strip():
            raise ValueError("a preset needs a name")
        before = list(self._saved)
        others = [p for p in self.presets() if p.id != preset_id]
        renamed = replace(self._saved[index], name=_unique_name(new_name.strip(), others))
        self._saved[index] = renamed
        self._commit(before)
        return renamed

    def set_tags(self, preset_id: str, tags: tuple[str, ...] | list[str]) -> Preset:
        """Give a saved preset these tags (``normalise_tags``: lowercase, trimmed, no commas, no repeats,
        at most 12 of at most 24 characters). ``ValueError`` for a built-in one, ``KeyError`` for an
        unknown id; ``OSError`` when the file cannot be written (the library is then as it was)."""
        index = self._index(preset_id)
        before = list(self._saved)
        tagged = replace(self._saved[index], tags=normalise_tags(tags))
        self._saved[index] = tagged
        self._commit(before)
        return tagged

    # -- finding -----------------------------------------------------------------------------------

    def search(self, query: str) -> list[Preset]:
        """The presets that match every word of ``query`` (case-insensitive), best first.

        A word matches when it is in the preset's name, description, a tag, its kind (``object``,
        ``scene``) or its origin worded for the user: ``builtin``, ``mine`` (saved by the user) or
        ``downloaded`` (from a link). Name matches come first, then tags and origin, then the description;
        equal ones keep the library's order. An empty query gives every preset.
        """
        words = query.lower().split()
        everyone = self.presets()
        if not words:
            return everyone
        ranked: list[tuple[int, int, Preset]] = []
        for index, preset in enumerate(everyone):
            total = 0
            for word in words:
                score = _match_score(word, preset)
                if score == 0:
                    break
                total += score
            else:
                ranked.append((-total, index, preset))
        ranked.sort(key=lambda r: (r[0], r[1]))
        return [preset for _, _, preset in ranked]

    def tags(self) -> list[tuple[str, int]]:
        """Every tag in use with how many presets have it: the most used first, then by name."""
        counts: dict[str, int] = {}
        for preset in self.presets():
            for tag in set(preset.tags):
                counts[tag] = counts.get(tag, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    def import_legacy(self, templates: dict[str, str]) -> int:
        """Move the old ``python_code_templates`` setting (name -> code) in as user presets of kind
        ``object``; one that is already here (same name, or that name with a ``(2)`` suffix, and the
        same code) is not added again, so calling this twice adds nothing the second time.
        Returns how many were added."""
        before = list(self._saved)
        added = 0
        for name, code in templates.items():
            if not isinstance(name, str) or not isinstance(code, str) or not name.strip():
                continue
            if any(_same_template(p, name.strip(), code) for p in self.presets()):
                continue
            self._append(name, "object", code, "user", "", (), "")
            added += 1
        if added:
            self._commit(before)
        return added

    # -- internals ---------------------------------------------------------------------------------

    def _index(self, preset_id: str) -> int:
        if any(p.id == preset_id for p in self._builtin):
            raise ValueError("built-in presets cannot be changed or removed")
        for index, preset in enumerate(self._saved):
            if preset.id == preset_id:
                return index
        raise KeyError(preset_id)

    def _append(
        self, name: str, kind: str, code: str, origin: str, description: str, tags, source_url: str
    ) -> Preset:
        everyone = self.presets()
        preset = Preset(
            id=_unique_id(origin, name, everyone),
            name=_unique_name(name.strip(), everyone),
            kind=kind,
            code=code,
            origin=origin,
            description=description,
            tags=tuple(str(tag) for tag in tags),
            source_url=source_url,
        )
        self._saved.append(preset)
        return preset

    def _commit(self, before: list[Preset]) -> None:
        try:
            self._save()
        except OSError:
            self._saved = before
            raise

    def _builtins(self) -> list[Preset]:
        out: list[Preset] = []
        for name, code in python_templates.TEMPLATES.items():
            out.append(
                Preset(
                    id=_unique_id("builtin", name, out),
                    name=name,
                    kind="object",
                    code=code,
                    origin="builtin",
                    description=inspect(code).summary,
                )
            )
        return out

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": FORMAT,
            "presets": [
                {
                    "id": p.id,
                    "name": p.name,
                    "kind": p.kind,
                    "code": p.code,
                    "origin": p.origin,
                    "description": p.description,
                    "tags": list(p.tags),
                    "source_url": p.source_url,
                }
                for p in self._saved
            ],
        }
        temp = self.path.with_name(f".{self.path.name}.{secrets.token_hex(4)}.tmp")
        try:
            temp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
            os.replace(temp, self.path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise

    def _load(self) -> list[Preset]:
        """The saved presets; never raises. A file that cannot be read is set aside (``.bad``)."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError):
            self._set_aside()
            return []
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):
            self._set_aside()
            return []
        if (
            not isinstance(data, dict)
            or data.get("format") != FORMAT
            or not isinstance(data.get("presets"), list)
        ):
            self._set_aside()
            return []
        out: list[Preset] = []
        for entry in data["presets"]:
            preset = _from_entry(entry, out)
            if preset is not None:
                out.append(preset)
        return out

    def _set_aside(self) -> None:
        """Rename an unreadable library file to ``presets.json.bad`` (``.bad2``...): kept, not used."""
        n = 1
        while True:
            target = self.path.with_name(f"{self.path.name}.bad{'' if n == 1 else n}")
            if not target.exists():
                break
            n += 1
        with contextlib.suppress(OSError):  # cannot be moved: the next save replaces it
            os.replace(self.path, target)


# -- helpers -----------------------------------------------------------------------------------------


MAX_TAGS = 12  # tags on one preset
MAX_TAG_LENGTH = 24  # characters of one tag
ORIGIN_WORDS = {"builtin": "builtin built-in", "user": "mine", "online": "downloaded"}  # as the user says it


def normalise_tags(tags: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Tags as they are kept: lowercase, trimmed, spaces squeezed, a comma separating two tags, empty ones
    and repeats gone (the first stays), each cut to 24 characters, at most 12."""
    out: list[str] = []
    for raw in tags:
        for part in str(raw).split(","):
            tag = " ".join(part.lower().split())[:MAX_TAG_LENGTH].strip()
            if tag and tag not in out:
                out.append(tag)
    return tuple(out[:MAX_TAGS])


def _match_score(word: str, preset: Preset) -> int:
    """How well one lowercase word matches a preset: 0 when it does not."""
    name = preset.name.lower()
    if name.startswith(word):
        return 100
    if word in name:
        return 60
    if any(word in tag.lower() for tag in preset.tags):
        return 40
    if word in ORIGIN_WORDS.get(preset.origin, "") or word == preset.kind:
        return 30
    if word in preset.description.lower():
        return 10
    return 0


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "preset"


def _unique_id(origin: str, name: str, existing: list[Preset]) -> str:
    taken = {p.id for p in existing}
    base = f"{origin}:{_slug(name)}"
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _unique_name(name: str, existing: list[Preset]) -> str:
    taken = {p.name.lower() for p in existing}
    candidate, n = name, 2
    while candidate.lower() in taken:
        candidate = f"{name} ({n})"
        n += 1
    return candidate


def _same_template(preset: Preset, name: str, code: str) -> bool:
    if preset.code != code:
        return False
    if preset.name.lower() == name.lower():
        return True
    return re.fullmatch(re.escape(name) + r" \(\d+\)", preset.name, re.IGNORECASE) is not None


def _from_entry(entry: Any, before: list[Preset]) -> Preset | None:
    """A saved preset read from the file, or None when the entry is not one (wrong types)."""
    if not isinstance(entry, dict):
        return None
    name, code, kind, origin = entry.get("name"), entry.get("code"), entry.get("kind"), entry.get("origin")
    if not isinstance(name, str) or not name.strip() or not isinstance(code, str):
        return None
    if kind not in KINDS or origin not in SAVED_ORIGINS:
        return None
    description, url, tags = entry.get("description", ""), entry.get("source_url", ""), entry.get("tags", [])
    if not isinstance(description, str) or not isinstance(url, str):
        return None
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        return None
    preset_id = entry.get("id")
    taken = {p.id for p in before}
    if not (isinstance(preset_id, str) and preset_id.startswith(f"{origin}:")) or preset_id in taken:
        preset_id = _unique_id(origin, name, before)
    return Preset(preset_id, name, kind, code, origin, description, tuple(tags), url)
