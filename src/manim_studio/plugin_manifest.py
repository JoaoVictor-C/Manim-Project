"""Plugin manifests, compatibility and permission approvals (ADR 0078). Pure: no Qt, no Manim.

A plugin may ship a manifest beside it, read before any of its code runs: ``<stem>.plugin.json`` next to a
plugin file ``<stem>.py``, or ``plugin.json`` inside an entry point's package (``<module>.plugin.json`` beside
an entry point's single-file module)::

    {
      "name": "Pendulum",
      "version": "1.2.0",
      "author": "Ada",
      "description": "A swinging pendulum object.",
      "requires": ">=0.3, <0.5",
      "permissions": ["reads_project", "files"]
    }

``name`` and ``version`` are required; ``requires`` is a comma-separated list of ``>=``, ``<=``, ``>``,
``<``, ``==``, ``!=`` or ``~=`` clauses (``==0.3.*`` matches a prefix) compared with the running app's
version; ``permissions`` come from ``PERMISSIONS``. A plugin without a manifest still loads, marked
"no manifest: unknown permissions".

Permissions are what a plugin *declares*; they are shown and approved, never enforced: a plugin is Python
running inside the app with the user's full rights. An approval is kept per plugin id with the version and
the hash of the permission set approved; a plugin asking for a permission not approved before is asked
about again. The store is a JSON file in the user's data folder (``plugin-approvals.json`` beside the
trusted-code store; override with ``MANIM_STUDIO_PLUGIN_APPROVALS``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_SUFFIX = ".plugin.json"  # beside a plugin file: pendulum.py -> pendulum.plugin.json
PACKAGE_MANIFEST = "plugin.json"  # inside a plugin package (an entry point's)

# The closed list of permissions a manifest may declare, with what each means to the user.
PERMISSIONS: dict[str, str] = {
    "reads_project": "reads the open project",
    "edits_project": "changes the open project",
    "files": "reads or writes files on this computer",
    "network": "connects to the internet",
    "runs_code": "starts programs or runs other code",
    "ui": "adds to the editor's window",
}
# The ones the dialog marks as the riskier kind.
SENSITIVE = frozenset({"edits_project", "files", "network", "runs_code"})

_CLAUSE = re.compile(r"^(>=|<=|==|!=|~=|>|<)?\s*(v?\d+(?:\.\d+)*)(\.\*)?$")
_VERSION = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


class ManifestError(ValueError):
    """A manifest that cannot be used: the plugin is shown as broken and not loaded."""


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    author: str = ""
    description: str = ""
    requires: str = ""  # an app version range; empty: any version
    permissions: tuple[str, ...] = ()  # sorted, no repeats


# -- versions ------------------------------------------------------------------------------------------


def parse_version(text: str) -> tuple[int, ...]:
    """The leading numbers of a version (``"0.3.0rc1"`` -> ``(0, 3, 0)``); raises ValueError if none."""
    match = _VERSION.match(str(text))
    if not match:
        raise ValueError(f"{text!r} is not a version")
    return tuple(int(part) for part in match.group(1).split("."))


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return (a > b) - (a < b)


def parse_requires(text: str) -> list[tuple[str, tuple[int, ...], bool]]:
    """The clauses of a version range as (operator, version, prefix); raises ValueError on a bad one."""
    clauses = []
    for raw in str(text).split(","):
        part = raw.strip()
        if not part:
            if str(text).strip():
                raise ValueError(f"{text!r} has an empty clause")
            continue
        match = _CLAUSE.match(part)
        if not match:
            raise ValueError(f"{part!r} is not a version clause (like >=0.3 or <1.0)")
        op, number, star = match.group(1) or "==", match.group(2), bool(match.group(3))
        if star and op not in ("==", "!="):
            raise ValueError(f"{part!r}: '.*' only goes with == or !=")
        if op == "~=" and len(parse_version(number)) < 2:
            raise ValueError(f"{part!r}: ~= needs at least two numbers")
        clauses.append((op, parse_version(number), star))
    return clauses


def _clause_holds(version: tuple[int, ...], op: str, target: tuple[int, ...], prefix: bool) -> bool:
    if prefix:
        same = (version + (0,) * len(target))[: len(target)] == target
        return same if op == "==" else not same
    c = _cmp(version, target)
    if op == "~=":  # compatible release: ~=0.3.1 is >=0.3.1 and ==0.3.*
        return c >= 0 and version[: len(target) - 1] == target[:-1]
    return {">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "==": c == 0, "!=": c != 0}[op]


def satisfies(version: str, requires: str) -> bool:
    """Whether ``version`` is in the range ``requires`` (empty: any version)."""
    parsed = parse_version(version)
    return all(_clause_holds(parsed, *clause) for clause in parse_requires(requires))


def incompatibility(manifest: Manifest, app_version: str) -> str | None:
    """Why a plugin cannot run on this app version, or None. An app of unknown version runs everything."""
    if not manifest.requires:
        return None
    try:
        parse_version(app_version)
    except ValueError:
        return None
    if satisfies(app_version, manifest.requires):
        return None
    return f"incompatible: needs {manifest.requires} (this is Manim Studio {app_version})"


# -- manifests -----------------------------------------------------------------------------------------


def _text(data: Mapping[str, Any], key: str, required: bool = False) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ManifestError(f"{key!r} must be text")
    if required and not value.strip():
        raise ManifestError(f"{key!r} is missing")
    return value.strip()


def parse_manifest(data: Any) -> Manifest:
    """A manifest from its JSON object; raises ManifestError on a missing field, an unknown permission or a
    bad version or range. Keys it does not know are ignored."""
    if not isinstance(data, Mapping):
        raise ManifestError("a manifest is a JSON object")
    name, version = _text(data, "name", True), _text(data, "version", True)
    try:
        parse_version(version)
    except ValueError as exc:
        raise ManifestError(f"'version': {exc}") from None
    requires = _text(data, "requires")
    try:
        parse_requires(requires)
    except ValueError as exc:
        raise ManifestError(f"'requires': {exc}") from None
    permissions = data.get("permissions", [])
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        raise ManifestError("'permissions' must be a list of names")
    unknown = sorted(set(permissions) - set(PERMISSIONS))
    if unknown:
        raise ManifestError(f"unknown permission {', '.join(unknown)} (known: {', '.join(PERMISSIONS)})")
    return Manifest(
        name=name,
        version=version,
        author=_text(data, "author"),
        description=_text(data, "description"),
        requires=requires,
        permissions=tuple(sorted(set(permissions))),
    )


def read_manifest(path: Path) -> Manifest | None:
    """The manifest at ``path``, None when there is no file; raises ManifestError when it is unusable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ManifestError(f"cannot read {Path(path).name}: {exc}") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ManifestError(f"{Path(path).name} is not valid JSON: {exc}") from None
    return parse_manifest(data)


def manifest_path_for_file(plugin_file: Path) -> Path:
    """Where a plugin file's manifest is: ``pendulum.py`` -> ``pendulum.plugin.json``."""
    return Path(plugin_file).with_name(Path(plugin_file).stem + MANIFEST_SUFFIX)


# -- permissions and approvals ------------------------------------------------------------------------


def permission_hash(permissions: Iterable[str]) -> str:
    """One hash for a permission set (order and repeats do not matter)."""
    return hashlib.sha256(",".join(sorted(set(permissions))).encode("utf-8")).hexdigest()


def approval_record(manifest: Manifest) -> dict[str, Any]:
    """What is stored when the user approves ``manifest``."""
    return {
        "name": manifest.name,
        "version": manifest.version,
        "permissions": list(manifest.permissions),
        "hash": permission_hash(manifest.permissions),
    }


def _approved_permissions(record: Any) -> set[str] | None:
    """The permissions a stored record approved, None when it is missing or does not hold together."""
    if not isinstance(record, Mapping):
        return None
    permissions = record.get("permissions")
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        return None
    if record.get("hash") != permission_hash(permissions):
        return None
    return set(permissions)


def new_permissions(record: Any, manifest: Manifest) -> tuple[str, ...]:
    """The permissions ``manifest`` asks for that ``record`` did not approve (all of them without one)."""
    approved = _approved_permissions(record)
    if approved is None:
        return manifest.permissions
    return tuple(p for p in manifest.permissions if p not in approved)


def is_approved(record: Any, manifest: Manifest) -> bool:
    """Whether a stored approval covers ``manifest``: one exists and the plugin asks for nothing more. A new
    version asking for the same or fewer permissions keeps its approval."""
    return _approved_permissions(record) is not None and not new_permissions(record, manifest)


def default_approvals_path() -> Path:
    override = os.environ.get("MANIM_STUDIO_PLUGIN_APPROVALS")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ManimStudio" / "plugin-approvals.json"
    return Path.home() / ".local" / "share" / "manim-studio" / "plugin-approvals.json"


def load_approvals(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """plugin id -> approval record; an unreadable store approves nothing."""
    path = Path(path) if path is not None else default_approvals_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    approvals = data.get("approved") if isinstance(data, dict) else None
    if not isinstance(approvals, dict):
        return {}
    return {str(k): v for k, v in approvals.items() if isinstance(v, dict)}


def save_approvals(approvals: Mapping[str, dict[str, Any]], path: Path | None = None) -> None:
    """Write the store at once (through a temporary file, so it is never half written)."""
    path = Path(path) if path is not None else default_approvals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"approved": dict(approvals)}, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)
