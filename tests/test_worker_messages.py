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


def test_new_python_code_stopped_by_its_time_limit_fails_the_request(monkeypatch) -> None:
    """ADR 0051: the editor's edit bringing an endless loop is dropped, not committed."""
    from manim_studio.core import adapter, python_object

    monkeypatch.setattr(python_object, "_trust_everything", True)
    monkeypatch.setattr(python_object, "TIME_LIMIT", 0.2)
    adapter.forget_python_builds()
    loop = "def build(p):\n    while True:\n        pass\n"
    answer = worker.reply({"id": 3, "spec": {"type": "Python", "params": {"code": loop}}})
    assert answer["id"] == 3 and not answer["ok"]
    assert answer["error"].split(": ", 1)[1].startswith("building took longer than 0.2 s")
    assert answer["error"].split(":")[0] in ("line 2", "line 3")  # the loop or its body
    fine = "def build(p):\n    return Circle()\n"
    assert worker.reply({"id": 4, "spec": {"type": "Python", "params": {"code": fine}}})["ok"]
    broken = "def build(p):\n    return nope\n"  # an error is the editor's placeholder: not a failure
    assert worker.reply({"id": 5, "spec": {"type": "Python", "params": {"code": broken}}})["ok"]
    adapter.forget_python_builds()
