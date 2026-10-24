"""Which code may run on this computer (ADR 0019).

A project file is data that can be shared; a code layer or a Python object (ADR 0051)
inside it is a program.
Opening a project must never run its code silently, so code runs only when its
hash (``code_cache.code_hash``) is in the user's trusted store. Code the user
applies in the editor is trusted; code that arrives in an opened file is asked
about once.

The store is a small JSON file in the user's data folder
(``%LOCALAPPDATA%/ManimStudio/trusted-code.json`` on Windows,
``~/.local/share/manim-studio/trusted-code.json`` elsewhere; override with
``MANIM_STUDIO_TRUST_FILE``). Pure: no Qt, no Manim.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path

from .code_cache import code_hash
from .schema import CODE_TYPES, PYTHON_TYPES, Project


def default_path() -> Path:
    override = os.environ.get("MANIM_STUDIO_TRUST_FILE")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ManimStudio" / "trusted-code.json"
    return Path.home() / ".local" / "share" / "manim-studio" / "trusted-code.json"


HELPER_KEY = "helper:"  # project_code's key for a helper: "helper:<name>" (ADR 0058)


def project_code(project: Project) -> dict[str, str]:
    """layer id -> code, for every code layer and Python object (ADR 0051) of ``project``, then
    ``helper:<name>`` -> code for every helper (ADR 0058): each is trusted by its own hash."""
    out = {
        layer.id: str(layer.spec.params.get("code", ""))
        for layer in project.layers
        if layer.spec is not None and layer.spec.type in CODE_TYPES | PYTHON_TYPES
    }
    out.update({f"{HELPER_KEY}{helper.name}": helper.code for helper in project.helpers})
    return out


def code_of(project: Project, key: str) -> str:
    """The code a ``project_code`` key names (a layer id or ``helper:<name>``); raises KeyError."""
    if key.startswith(HELPER_KEY):
        return project.helper(key.removeprefix(HELPER_KEY)).code
    return str(project.layer(key).spec.params.get("code", ""))


def label(project: Project, key: str) -> str:
    """How a ``project_code`` key is named to the user: a layer's label, or "helper <name>"."""
    if key.startswith(HELPER_KEY):
        return f"helper {key.removeprefix(HELPER_KEY)}"
    return project.layer(key).name or key


class TrustStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._hashes = set(data.get("trusted", []))
        except (OSError, ValueError):
            self._hashes = set()

    def is_trusted(self, code: str) -> bool:
        return code_hash(code) in self._hashes

    def trust(self, codes: Iterable[str]) -> None:
        """Remember ``codes`` as safe to run (and save the store)."""
        before = len(self._hashes)
        self._hashes.update(code_hash(code) for code in codes)
        if len(self._hashes) != before:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"trusted": sorted(self._hashes)}
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            os.replace(temp, self.path)

    def carry(self, rewritten: Iterable[tuple[str, str]]) -> None:
        """Trust each rewritten text whose text before was trusted (``Edit.rewritten``: renaming a
        helper rewrote the imports of the code that uses it, ADR 0058)."""
        self.trust([after for before, after in rewritten if self.is_trusted(before)])

    def untrusted(self, project: Project) -> list[str]:
        """Ids of the code layers and Python objects whose code may not run, then ``helper:<name>``
        for each such helper (ADR 0058)."""
        return [layer_id for layer_id, code in project_code(project).items() if not self.is_trusted(code)]
