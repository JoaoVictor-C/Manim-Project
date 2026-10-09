"""Logging setup (ADR 0011)."""

from __future__ import annotations

import logging

import pytest

from manim_studio.logging_config import LOGGER_NAME, get_logger, log_dir, setup_logging


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger(LOGGER_NAME)
    saved = (list(root.handlers), root.level, root.propagate, logging.getLogger("manim").level)
    yield
    for handler in root.handlers:
        if handler not in saved[0]:
            handler.close()
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    root.propagate = saved[2]
    logging.getLogger("manim").setLevel(saved[3])


def _console_level() -> int:
    handlers = logging.getLogger(LOGGER_NAME).handlers
    return next(h.level for h in handlers if not isinstance(h, logging.FileHandler))


def test_log_dir_honours_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MANIM_STUDIO_LOG_DIR", str(tmp_path / "logs"))
    assert log_dir() == tmp_path / "logs"


def test_file_receives_debug_messages(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MANIM_STUDIO_LOG_DIR", str(tmp_path))
    path = setup_logging(verbosity=0)
    get_logger("tests").debug("hello from the test")
    for handler in logging.getLogger(LOGGER_NAME).handlers:
        handler.flush()
    assert path == tmp_path / "manim-studio.log"
    assert "hello from the test" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("verbosity", "level"), [(0, logging.WARNING), (1, logging.INFO), (2, logging.DEBUG)]
)
def test_console_level_follows_verbosity(monkeypatch, tmp_path, verbosity: int, level: int) -> None:
    monkeypatch.setenv("MANIM_STUDIO_LOG_DIR", str(tmp_path))
    setup_logging(verbosity)
    assert _console_level() == level


def test_manim_logger_is_capped() -> None:
    setup_logging(to_file=False)
    assert logging.getLogger("manim").level == logging.WARNING


def test_repeated_setup_does_not_duplicate_handlers(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MANIM_STUDIO_LOG_DIR", str(tmp_path))
    setup_logging()
    setup_logging()
    assert len(logging.getLogger(LOGGER_NAME).handlers) == 2


def test_unwritable_log_dir_does_not_raise(monkeypatch, tmp_path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("MANIM_STUDIO_LOG_DIR", str(blocker / "logs"))
    assert setup_logging() is None
    get_logger("tests").warning("still works")


def test_get_logger_namespaces() -> None:
    assert get_logger("x").name == "manim_studio.x"
    assert get_logger("manim_studio.core").name == "manim_studio.core"
