"""Run on a helper (ADR 0058): what the throwaway process reports for one helper's import."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from manim_studio.processes import helper_check

ROOT = Path(__file__).resolve().parents[2]


def test_a_helper_that_imports_reports_what_it_printed() -> None:
    result = helper_check.check("hc_ok", {"hc_ok": "print('hello')\nX = 1\n"}, {"hc_ok"})
    assert result == {"ok": True, "output": "hello\n"}


def test_an_error_says_where_in_the_helper() -> None:
    result = helper_check.check("hc_bad", {"hc_bad": "X = 1\nY = missing\n"}, {"hc_bad"})
    assert not result["ok"]
    assert (result["type"], result["where"], result["helper_line"]) == ("NameError", "helper:hc_bad", 2)
    assert result["error"].startswith("NameError:") and "line 2" in result["traceback"]


def test_a_syntax_error_points_at_its_line() -> None:
    result = helper_check.check("hc_syntax", {"hc_syntax": "x = 1\ndef f(:\n"}, {"hc_syntax"})
    assert (result["type"], result["where"], result["helper_line"]) == ("SyntaxError", "helper:hc_syntax", 2)


def test_an_error_in_a_helper_it_imports_names_that_helper() -> None:
    sources = {"hc_top": "import hc_low\n", "hc_low": "\n1 / 0\n"}
    result = helper_check.check("hc_top", sources, set(sources))
    assert (result["where"], result["helper_line"], result["type"]) == (
        "helper:hc_low",
        2,
        "ZeroDivisionError",
    )


def test_a_helper_it_imports_that_is_not_trusted_is_said() -> None:
    sources = {"hc_user": "import hc_untrusted\n", "hc_untrusted": "X = 1\n"}
    result = helper_check.check("hc_user", sources, {"hc_user"})
    assert result["type"] == "ImportError" and "not trusted" in result["error"]
    assert (result["where"], result["helper_line"]) == ("helper:hc_user", 1)


def test_the_process_reads_one_job_and_writes_one_result() -> None:
    job = {"name": "hc_proc", "helpers": [["hc_proc", "print('hi')\n"]], "trusted": ["hc_proc"]}
    done = subprocess.run(
        [sys.executable, "-m", "manim_studio.processes.helper_check"],
        input=json.dumps(job) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert done.returncode == 0
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {"ok": True, "output": "hi\n"}
