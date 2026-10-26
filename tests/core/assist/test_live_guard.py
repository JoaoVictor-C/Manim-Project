"""When Live mode may run what is being typed (P13.7)."""

from __future__ import annotations

import pytest

from manim_studio.core.assist import live_guard as lg

GOOD = "PARAMS = {'r': (1.0, 0.5, 3.0)}\n\ndef build(p):\n    return Circle(radius=p['r'])\n"


def test_plain_object_code_may_run() -> None:
    assert lg.live_problem(GOOD) is None and lg.risky_reason(GOOD) is None


def test_text_that_does_not_parse_waits_quietly() -> None:
    reason = lg.live_problem("def build(p):\n    return Circle(\n")
    assert reason == "does not parse yet" and lg.is_quiet(reason)


def test_unreadable_params_wait_quietly() -> None:
    reason = lg.live_problem("PARAMS = {'a': 1 + x}\n\ndef build(p):\n    return Circle()\n")
    assert reason == "PARAMS cannot be read yet" and lg.is_quiet(reason)


@pytest.mark.parametrize(
    ("line", "name"),
    [
        ("import os", "os"),
        ("import os.path", "os"),
        ("from subprocess import run", "subprocess"),
        ("import socket", "socket"),
        ("data = open('x').read()", "open"),
        ("exec('1')", "exec"),
        ("eval('1')", "eval"),
        ("__import__('os')", "__import__"),
        ("from pathlib import Path", "pathlib"),
        ("import importlib", "importlib"),
        ("import urllib.request", "urllib"),
    ],
)
def test_files_processes_and_the_network_are_for_run_not_for_a_pause(line: str, name: str) -> None:
    source = GOOD + "\n" + line + "\n"
    reason = lg.live_problem(source)
    assert reason == f"uses {name}" and not lg.is_quiet(reason)


def test_a_attribute_chain_on_a_risky_name_is_caught() -> None:
    assert lg.risky_reason("def build(p):\n    return os.getcwd()\n") == "uses os"


def test_safe_imports_and_names_pass() -> None:
    source = "import math\nimport numpy as np\nfrom manim import *\nimport itertools\n" + GOOD
    assert lg.live_problem(source) is None


def test_a_byte_order_mark_does_not_matter() -> None:
    assert lg.live_problem("\ufeff" + GOOD) is None
    assert lg.live_problem("\ufeff" + GOOD + "import os\n") == "uses os"


def test_risky_uses_lists_every_risky_name_once_in_order() -> None:
    from manim_studio.core.assist.live_guard import risky_uses

    source = "import os, sys\nfrom subprocess import run\nx = open('a')\nos.remove(x)\n"
    assert risky_uses(source) == ["os", "sys", "subprocess", "open"]
    assert risky_uses("Circle()") == [] and risky_uses("def (") == []
