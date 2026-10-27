"""The real editor with its real helpers: when it is killed or closed, none of them is left.

A helper is a Python process with Manim loaded; one that outlived the editor would sit in memory (and, if
it was rendering code that loops for ever, on a core) until the computer is restarted."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from manim_studio import lifeline

pytestmark = pytest.mark.slow  # starts the editor and its helpers: Manim is imported in each, ~20 s

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "euler.json"
ENDLESS = "\n".join(
    [
        "from manim import *",
        "",
        "",
        "class Loop(Scene):",
        "    def construct(self):",
        "        while True:",
        "            pass",
        "",
    ]
)


def wait_until(condition, timeout: float = 90.0, step: float = 0.25) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(step)
    return condition()


def test_killing_the_editor_leaves_no_helper_behind(tmp_path) -> None:
    """The editor is run as a program (without a screen) and killed the hard way."""
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "MANIM_STUDIO_SETTINGS": str(tmp_path / "settings.ini"),
        "MANIM_STUDIO_LOG_DIR": tempfile.mkdtemp(prefix="manim-studio-lifetime-logs-"),
        "MANIM_STUDIO_RECOVERY": tempfile.mkdtemp(prefix="manim-studio-lifetime-recovery-"),
        "MANIM_STUDIO_WORKER": "1",
        "MANIM_STUDIO_PREVIEW": "1",
        "MANIM_STUDIO_CODE": "0",
        "MANIM_STUDIO_AUDIO": "0",
        "MANIM_STUDIO_MOTION": "0",
    }
    editor = subprocess.Popen(
        [sys.executable, "-m", "manim_studio", "edit", str(EXAMPLE)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=ROOT,
    )
    try:
        assert wait_until(lambda: len(lifeline.descendants(editor.pid)) >= 2), "the editor started no helper"
        time.sleep(8)  # the build worker and the frame renderer are up, and the editor is idle
        helpers = lifeline.descendants(editor.pid)
        assert len(helpers) >= 2
        editor.kill()  # no chance to clean up
        editor.wait(timeout=30)
        assert wait_until(lambda: not any(lifeline.process_alive(p) for p in helpers), timeout=30), (
            "helpers outlived the editor: " + ", ".join(str(p) for p in helpers if lifeline.process_alive(p))
        )
    finally:
        lifeline.kill_tree(editor.pid)


def test_killing_the_editor_ends_a_code_render_stuck_in_an_endless_loop(tmp_path) -> None:
    """The case that matters: the user's code never returns, so the helper running it never looks at its input
    (a closed pipe tells it nothing); only the operating system ending it, or the helper's own watch, can."""
    from manim_studio.core.code.trust import TrustStore
    from manim_studio.core.model.schema import Canvas, Layer, Project, Spec

    project = Project(
        canvas=Canvas(width_px=64, height_px=36, fps=10, duration=1.0),
        layers=[Layer(id="loop", spec=Spec(type="Code", params={"code": ENDLESS}))],
    )
    path = tmp_path / "loop.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    trust = tmp_path / "trusted.json"
    TrustStore(trust).trust([ENDLESS])
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "MANIM_STUDIO_SETTINGS": str(tmp_path / "settings.ini"),
        "MANIM_STUDIO_LOG_DIR": tempfile.mkdtemp(prefix="manim-studio-lifetime-logs-"),
        "MANIM_STUDIO_RECOVERY": tempfile.mkdtemp(prefix="manim-studio-lifetime-recovery-"),
        "MANIM_STUDIO_TRUST_FILE": str(trust),
        "MANIM_STUDIO_CACHE": str(tmp_path / "cache"),
        "MANIM_STUDIO_WORKER": "0",
        "MANIM_STUDIO_PREVIEW": "0",
        "MANIM_STUDIO_CODE": "1",
        "MANIM_STUDIO_AUDIO": "0",
        "MANIM_STUDIO_MOTION": "0",
    }
    editor = subprocess.Popen(
        [sys.executable, "-m", "manim_studio", "edit", str(path)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=ROOT,
    )
    try:
        assert wait_until(lambda: len(lifeline.descendants(editor.pid)) >= 2), "no render process was started"
        time.sleep(12)  # Manim is imported, the job taken, the loop running
        helpers = lifeline.descendants(editor.pid)
        assert helpers and all(lifeline.process_alive(p) for p in helpers)
        editor.kill()
        editor.wait(timeout=30)
        assert wait_until(lambda: not any(lifeline.process_alive(p) for p in helpers), timeout=30), (
            "a render process outlived the editor: "
            + ", ".join(str(p) for p in helpers if lifeline.process_alive(p))
        )
    finally:
        lifeline.kill_tree(editor.pid)
        for pid in lifeline.descendants(editor.pid):
            lifeline.kill_tree(pid)


@pytest.mark.ui
def test_closing_the_window_ends_every_helper_quickly(qt_app, monkeypatch) -> None:
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    monkeypatch.setenv("MANIM_STUDIO_PREVIEW", "1")
    from manim_studio.ui.main_window import MainWindow

    before = set(lifeline.descendants(os.getpid()))
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.load(EXAMPLE)
    end = time.monotonic() + 90
    while not (window.builds.client.ready and window.render_ahead.client.ready) and time.monotonic() < end:
        qt_app.processEvents()
        time.sleep(0.05)
    helpers = set(lifeline.descendants(os.getpid())) - before
    assert len(helpers) >= 2, "no helper was started"
    started = time.monotonic()
    window.document.undo_stack.setClean()
    window.close()
    took = time.monotonic() - started
    assert wait_until(lambda: not any(lifeline.process_alive(p) for p in helpers), timeout=15), (
        "helpers outlived the window: " + ", ".join(str(p) for p in helpers if lifeline.process_alive(p))
    )
    assert took < 5, f"closing took {took:.1f} s"
