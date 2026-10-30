"""Preferences (P6d.1, ADR 0044): how the editor was left, in one ini file.

The file is ``MANIM_STUDIO_SETTINGS`` or, by default, ``manim-studio.ini`` in the user's
configuration folder (the registry is never used). It holds the recent files, the
window's geometry and state, each page's splitter sizes, the view toggles (snap to
objects, half-resolution playback, render ahead), each project's canvas view and the
last page shown.

The recent-file rules (``push_recent``, ``existing``) are plain functions over lists of
paths; ``Preferences`` wraps ``QSettings`` around them. Tests point the environment
variable at a fresh file each, so windows in tests start at the defaults.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, QStandardPaths

from ..canvas.viewport import View
from .editor_settings import EditorSettings, from_json, to_json

MAX_RECENT = 10
FILE_NAME = "manim-studio.ini"
LAYOUT_VERSION = (
    2  # 2: Lumen (ADR 0063) rearranged every page, so splitter sizes saved before it no longer fit
)


def _key(path: str | Path) -> str:
    """Two spellings of one file give one key (case counts only where the system's does)."""
    return os.path.normcase(str(Path(path).resolve()))


def _canvas_view_key(path: str | Path) -> str:
    """A stable settings key that does not expose a project's path in the INI key names."""
    return hashlib.sha256(_key(path).encode("utf-8")).hexdigest()


def push_recent(items: list[str], path: str | Path, limit: int = MAX_RECENT) -> list[str]:
    """``items`` with ``path`` first and no earlier copy of it, at most ``limit`` long."""
    first = str(Path(path).resolve())
    rest = [item for item in items if _key(item) != _key(first)]
    return [first, *rest][:limit]


def existing(items: list[str]) -> list[str]:
    """The items that are files that still exist, in order."""
    return [item for item in items if Path(item).is_file()]


def default_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(base or Path.home()) / FILE_NAME


class Preferences:
    """Typed access to the settings file; every setter writes it at once."""

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            env = os.environ.get("MANIM_STUDIO_SETTINGS")
            path = Path(env) if env else default_path()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        self._forget_old_layouts()

    def _forget_old_layouts(self) -> None:
        """Splitter sizes and the dock state saved by an older arrangement of the pages would be applied to
        the new one (panels in odd places, a collapsed stage): drop them once, when the layout changed."""
        if int(self._settings.value("layout_version", 0)) >= LAYOUT_VERSION:
            return
        self._settings.remove("pages")
        self._settings.remove("window/state")
        self._settings.setValue("layout_version", LAYOUT_VERSION)
        self._settings.sync()

    # -- recent files ---------------------------------------------------------------------

    def _recent_raw(self) -> list[str]:
        count = self._settings.beginReadArray("recent")
        items = []
        for i in range(count):
            self._settings.setArrayIndex(i)
            items.append(str(self._settings.value("path", "")))
        self._settings.endArray()
        return [item for item in items if item]

    def _write_recent(self, items: list[str]) -> None:
        self._settings.remove("recent")
        self._settings.beginWriteArray("recent", len(items))
        for i, item in enumerate(items):
            self._settings.setArrayIndex(i)
            self._settings.setValue("path", item)
        self._settings.endArray()
        self._settings.sync()

    def recent(self) -> list[Path]:
        """The recent files, newest first; the ones that no longer exist are left out."""
        return [Path(item) for item in existing(self._recent_raw())]

    def add_recent(self, path: Path | str) -> None:
        self._write_recent(push_recent(existing(self._recent_raw()), path))

    def clear_recent(self) -> None:
        self._write_recent([])

    def python_code_templates(self) -> dict[str, str]:
        """User-imported code templates for the Code page's New Python object menu."""
        raw = self._settings.value("python_code_templates", "{}")
        try:
            value = json.loads(str(raw))
        except (TypeError, ValueError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {name: code for name, code in value.items() if isinstance(name, str) and isinstance(code, str)}

    def set_python_code_templates(self, templates: dict[str, str]) -> None:
        self._settings.setValue("python_code_templates", json.dumps(templates, ensure_ascii=False))
        self._settings.sync()

    # -- window and pages -----------------------------------------------------------------

    def window(self) -> tuple[QByteArray | None, QByteArray | None]:
        """The saved geometry and state, each None if never saved."""
        return self._bytes("window/geometry"), self._bytes("window/state")

    def save_window(self, geometry: QByteArray, state: QByteArray) -> None:
        self._settings.setValue("window/geometry", geometry)
        self._settings.setValue("window/state", state)
        self._settings.sync()

    def page_sizes(self, name: str) -> list[QByteArray | None]:
        """A page's splitter states in their order (None: none saved for that splitter)."""
        self._settings.beginGroup(f"pages/{name}")
        keys = sorted(int(k) for k in self._settings.childKeys() if k.isdigit())
        states = [self._bytes(str(k)) for k in keys]
        self._settings.endGroup()
        count = (keys[-1] + 1) if keys else 0
        by_index = dict(zip(keys, states, strict=True))
        return [by_index.get(i) for i in range(count)]

    def set_page_sizes(self, name: str, states: list[QByteArray | None]) -> None:
        self._settings.remove(f"pages/{name}")
        for i, state in enumerate(states):
            if state is not None:
                self._settings.setValue(f"pages/{name}/{i}", state)
        self._settings.sync()

    def last_page(self) -> str | None:
        value = self._settings.value("last_page", "")
        return str(value) or None

    def set_last_page(self, name: str) -> None:
        self._settings.setValue("last_page", name)
        self._settings.sync()

    # -- view toggles ---------------------------------------------------------------------

    def toggle(self, name: str, default: bool) -> bool:
        return bool(self._settings.value(f"view/{name}", default, type=bool))

    def set_toggle(self, name: str, value: bool) -> None:
        self._settings.setValue(f"view/{name}", bool(value))
        self._settings.sync()

    def canvas_view(self, path: str | Path) -> View | None:
        """The last canvas framing for a project file, if it was saved and is valid."""
        raw = self._settings.value(f"canvas_views/{_canvas_view_key(path)}", "")
        try:
            data = json.loads(str(raw))
            if not isinstance(data, dict):
                return None
            fit, scale, centre = data["fit"], data["scale"], data["centre"]
            if (
                type(fit) is not bool
                or isinstance(scale, bool)
                or not isinstance(scale, (int, float))
                or not math.isfinite(scale)
                or scale <= 0
                or not isinstance(centre, list)
                or len(centre) != 2
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in centre)
                or any(not math.isfinite(value) for value in centre)
            ):
                return None
            return View(fit, float(scale), (float(centre[0]), float(centre[1])))
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    def set_canvas_view(self, path: str | Path, view: View) -> None:
        """Remember a project's zoom and centre without adding editor state to its project file."""
        data = {"fit": view.fit, "scale": view.scale, "centre": list(view.centre)}
        self._settings.setValue(f"canvas_views/{_canvas_view_key(path)}", json.dumps(data))
        self._settings.sync()

    # -- appearance (Lumen, ADR 0063) -------------------------------------------------------------

    APPEARANCES = ("ink", "paper", "system")

    def appearance(self) -> str:
        """``ink`` (dark, the default), ``paper`` (light) or ``system`` (follow the operating system)."""
        value = str(self._settings.value("appearance", "ink"))
        return value if value in self.APPEARANCES else "ink"

    def set_appearance(self, name: str) -> None:
        self._settings.setValue("appearance", name if name in self.APPEARANCES else "ink")
        self._settings.sync()

    # -- remembered options (a dialog's last choices) --------------------------------------------

    def option(self, name: str, default):
        """The last value saved under ``name`` (``options/<name>``), as the type of ``default``."""
        value = self._settings.value(f"options/{name}", default, type=type(default))
        return default if value is None else value

    def set_option(self, name: str, value) -> None:
        self._settings.setValue(f"options/{name}", value)
        self._settings.sync()

    # -- the code editor's settings (P12) ----------------------------------------------------------

    def editor_settings(self) -> EditorSettings:
        """How the code editor behaves, as last saved (the defaults for anything missing or unreadable)."""
        return from_json(str(self._settings.value("editor_settings", "")))

    def set_editor_settings(self, settings: EditorSettings) -> None:
        self._settings.setValue("editor_settings", to_json(settings))
        self._settings.sync()

    def _bytes(self, key: str) -> QByteArray | None:
        value = self._settings.value(key)
        if value is None:
            return None
        data = QByteArray(value) if not isinstance(value, QByteArray) else value
        return data if not data.isEmpty() else None
