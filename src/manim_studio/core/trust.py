"""Which code may run on this computer (ADR 0019).

A project file is data that can be shared; a code layer inside it is a program.
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
from .schema import CODE_TYPES, Project


def default_path() -> Path:
    override = os.environ.get("MANIM_STUDIO_TRUST_FILE")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ManimStudio" / "trusted-code.json"
    return Path.home() / ".local" / "share" / "manim-studio" / "trusted-code.json"


def project_code(project: Project) -> dict[str, str]:
    """layer id -> code, for every code layer of ``project``."""
    return {
        layer.id: str(layer.spec.params.get("code", ""))
        for layer in project.layers
        if layer.spec is not None and layer.spec.type in CODE_TYPES
    }


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

    def untrusted(self, project: Project) -> list[str]:
        """Ids of the code layers whose code may not run."""
        return [layer_id for layer_id, code in project_code(project).items() if not self.is_trusted(code)]
