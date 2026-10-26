"""The No time limit switch (ADR 0059): a Python object's build is stopped by its limit, unless lifted."""

from __future__ import annotations

import pytest

from manim_studio.core import limits, python_object

BUSY = "import time\nt = time.perf_counter()\nwhile time.perf_counter() - t < 0.05:\n    pass\n"


def run_busy(seconds: float) -> None:
    code = compile(BUSY, python_object.FILENAME, "exec")  # traced like the user's code
    with python_object.time_limit(seconds):
        exec(code, {})


def test_the_limits_are_on_by_default() -> None:
    assert limits.unlimited() is False
    assert limits.RENDER_LIMIT > limits.BUILD_LIMIT > 0


def test_a_run_over_its_limit_is_stopped() -> None:
    with pytest.raises(python_object.TimeLimit):
        run_busy(0.01)


def test_no_time_limit_lets_it_finish() -> None:
    limits.set_unlimited(True)
    run_busy(0.01)  # no TimeLimit
    limits.set_unlimited(False)
    with pytest.raises(python_object.TimeLimit):
        run_busy(0.01)
