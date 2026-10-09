"""The build worker's error messages (ADR 0015) — what the user reads when LaTeX fails."""

from __future__ import annotations

from manim_studio import worker


def test_latex_errors_come_from_the_log_file(tmp_path) -> None:
    log = tmp_path / "x.log"
    log.write_text(
        "This is TeX\n! Undefined control sequence.\nl.7 \notamacro\n! Missing $ inserted.\n",
        encoding="utf-8",
    )
    exc = ValueError(f"latex error converting to dvi. See log output above or the log file: {log}")
    assert worker._summary(exc) == "LaTeX error: Undefined control sequence.; Missing $ inserted."


def test_other_errors_are_summarised(tmp_path) -> None:
    exc = RuntimeError("first line\n\nsecond line\n" + "\n".join(f"more {i}" for i in range(10)))
    message = worker._summary(exc)
    assert message.startswith("RuntimeError: first line\nsecond line")
    assert message.count("\n") == worker.ERROR_LINES - 1


def test_a_missing_log_falls_back_to_the_exception(tmp_path) -> None:
    exc = ValueError(f"latex failed, see the log file: {tmp_path / 'gone.log'}")
    assert worker._summary(exc).startswith("ValueError: latex failed")
    assert worker._latex_errors(tmp_path / "gone.log") == []
