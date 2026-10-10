"""The code runner (P2d.2, ADR 0019): real Manim scenes into the frame cache."""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from manim_studio.code_runner import CodeError, Job, render_code
from manim_studio.core.code_cache import CodeCache

ORBIT = """
class Orbit(Scene):
    def construct(self):
        t = ValueTracker(0)
        dot = Dot(color=YELLOW).add_updater(
            lambda d: d.move_to([2 * np.cos(t.get_value()), 2 * np.sin(t.get_value()), 0])
        )
        self.add(TracedPath(dot.get_center, stroke_color=YELLOW, stroke_width=6), dot)
        self.play(t.animate.set_value(TAU), run_time=1, rate_func=linear)
        self.wait(0.5)
"""


def job(code: str, key: str = "k") -> Job:
    return Job(key=key, code=code, width=160, height=90, fps=10, frame_height=8.0)


def test_a_scene_with_updaters_renders_every_frame_on_a_transparent_background(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    seen = []
    assert render_code(job(ORBIT), cache, progress=seen.append) == 15  # 1 s play + 0.5 s wait at 10 fps
    assert seen == [10]
    clip = cache.open("k")
    assert clip.frame_count == 15
    first, middle, last = clip.crop(0), clip.crop(5), clip.crop(14)
    assert (
        middle.pixels.shape[0] * middle.pixels.shape[1] < 160 * 90
    )  # cropped: the background is transparent
    # The trace grows: the last frame shows a full circle, much wider than the first dot.
    assert last.pixels.shape[1] > 3 * first.pixels.shape[1]


def test_a_still_scene_is_one_frame_and_a_static_wait_is_stored_once(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    code = "class Still(Scene):\n    def construct(self):\n        self.add(Square())\n"
    assert render_code(job(code), cache) == 1
    assert cache.open("k").crop(0) is not None
    waiting = (
        "class Wait(Scene):\n    def construct(self):\n        self.add(Square())\n        self.wait(1)\n"
    )
    assert render_code(job(waiting, key="w"), cache) == 10
    assert len(list((tmp_path / "w").glob("*.z"))) == 1  # Manim repeats one frame; the cache stores it once


@pytest.mark.parametrize(
    ("code", "message", "line"),
    [
        ("class A(Scene):\n    def construct(self)\n        pass\n", "SyntaxError", 2),
        (
            "class A(Scene):\n    def construct(self):\n        self.add(Circle())\n        1 / 0\n",
            "ZeroDivisionError",
            4,
        ),
        ("x = undefined_name\n", "NameError", 1),
        ("x = 1\n", "define exactly one Scene subclass (found: none)", None),
        ("class A(Scene): pass\nclass B(Scene): pass\n", "found: A, B", None),
    ],
)
def test_errors_report_the_line_in_the_users_code(tmp_path, code, message, line) -> None:
    cache = CodeCache(tmp_path)
    with pytest.raises(CodeError, match=re.escape(message)) as caught:
        render_code(job(code), cache)
    assert caught.value.line == line
    assert not cache.has("k") and not any(tmp_path.iterdir())  # nothing half-written


def run_spare(tmp_path, job_line: str) -> tuple[list[dict], int]:
    process = subprocess.Popen(
        [sys.executable, "-m", "manim_studio.code_runner", "--cache-dir", str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    line = process.stdout.readline()
    while not line.startswith("{"):  # anything else on stdout is not the protocol
        line = process.stdout.readline()
    assert json.loads(line) == {"ready": True}  # Manim imported before any job
    out, _ = process.communicate(job_line + "\n", timeout=120)
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")], process.returncode


@pytest.mark.slow
def test_a_warm_spare_takes_one_job_from_stdin(tmp_path) -> None:
    messages, code = run_spare(tmp_path, job(ORBIT, key="orbit").to_json())
    assert code == 0 and messages[-1] == {"done": True, "frames": 15}
    assert {"frame": 10} in messages
    assert CodeCache(tmp_path / "code").open("orbit").frame_count == 15


@pytest.mark.slow
def test_a_failing_job_reports_its_error_and_line(tmp_path) -> None:
    bad = "class A(Scene):\n    def construct(self):\n        raise RuntimeError('boom')\n"
    messages, code = run_spare(tmp_path, job(bad).to_json())
    assert code == 1
    assert messages[-1] == {"error": "RuntimeError: boom", "line": 3}


@pytest.mark.slow
def test_export_renders_code_layers_only_when_trusted(tmp_path, capsys) -> None:
    from manim_studio import cli
    from manim_studio.core.schema import Canvas, Layer, Project, Spec

    project = Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=1.0),
        layers=[Layer(id="orbit", spec=Spec(type="Code", params={"code": ORBIT}))],
    )
    path = tmp_path / "p.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    cache = tmp_path / "cache"
    assert cli.main(["render", str(path), str(tmp_path / "a.mp4"), "--cache-dir", str(cache)]) == 0
    assert "is not rendered (pass --trust-code" in capsys.readouterr().err
    assert not (cache / "code").exists() or not any((cache / "code").iterdir())
    assert (
        cli.main(["render", str(path), str(tmp_path / "b.mp4"), "--cache-dir", str(cache), "--trust-code"])
        == 0
    )
    assert "warning" not in capsys.readouterr().err
    assert len([d for d in (cache / "code").iterdir() if not d.name.startswith(".")]) == 1
