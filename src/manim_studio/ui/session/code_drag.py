"""What is dragged from the Code workspace to the timeline, the canvas and the layers list (P12.7).

One MIME type carries a small JSON payload that names a preset or a code layer; the drop target does
not read it, it hands it to ``MainWindow.place_code`` together with where it was dropped. ``.py`` files
dragged from the desktop arrive as URLs and go to ``MainWindow.import_code_files``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMimeData, QUrl

MIME = "application/x-manim-studio-code"
SOURCES = ("preset", "layer")
KINDS = ("object", "scene")


def encode(source: str, item_id: str, name: str, kind: str) -> QMimeData:
    """Drag data for a preset (``source="preset"``) or a code layer / Python object already in the
    project (``source="layer"``); ``kind`` is ``"object"`` or ``"scene"``."""
    payload = {"from": source, "id": item_id, "name": name, "kind": kind}
    mime = QMimeData()
    mime.setData(MIME, json.dumps(payload).encode("utf-8"))
    mime.setText(name)
    return mime


def decode(mime: QMimeData) -> dict[str, Any] | None:
    """The payload of a Code workspace drag, or None when ``mime`` is something else (or damaged)."""
    if not mime.hasFormat(MIME):
        return None
    try:
        payload = json.loads(bytes(mime.data(MIME)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("from") not in SOURCES or payload.get("kind") not in KINDS:
        return None
    if not isinstance(payload.get("id"), str) or not isinstance(payload.get("name"), str):
        return None
    return payload


def python_files(mime: QMimeData) -> list[Path]:
    """The ``.py`` files among the local files in ``mime`` (dragged from the desktop)."""
    if not mime.hasUrls():
        return []
    urls: list[QUrl] = mime.urls()
    paths = (Path(url.toLocalFile()) for url in urls if url.isLocalFile())
    return [path for path in paths if path.suffix.lower() == ".py" and path.is_file()]


def accepts(mime: QMimeData) -> bool:
    """Can a drop target take this drag?"""
    return decode(mime) is not None or bool(python_files(mime))
