"""Logging setup shared by the CLI and the editor.

* Console: warnings by default, ``-v`` for info, ``-vv`` for debug.
* File: always debug, rotated, in the per-user log directory
  (``%LOCALAPPDATA%/ManimStudio/logs`` on Windows, ``~/.local/state/manim-studio/logs``
  elsewhere; override with ``MANIM_STUDIO_LOG_DIR``).
* Manim's own logger is capped at WARNING: it logs every LaTeX compile at INFO.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "manim_studio"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def log_dir() -> Path:
    override = os.environ.get("MANIM_STUDIO_LOG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ManimStudio" / "logs"
    return Path.home() / ".local" / "state" / "manim-studio" / "logs"


def setup_logging(verbosity: int = 0, to_file: bool = True) -> Path | None:
    """Configure the ``manim_studio`` logger; returns the log file path, if any."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setLevel({0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG))
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(console)

    path = None
    if to_file:
        directory = log_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "manim-studio.log"
            handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter(_FORMAT))
            logger.addHandler(handler)
        except OSError as exc:  # logging must never stop the app
            logger.warning("file logging disabled: %s", exc)
            path = None

    logging.getLogger("manim").setLevel(logging.WARNING)
    return path


def get_logger(name: str) -> logging.Logger:
    """Module logger under the ``manim_studio`` namespace (pass ``__name__``)."""
    return logging.getLogger(name if name.startswith(LOGGER_NAME) else f"{LOGGER_NAME}.{name}")
