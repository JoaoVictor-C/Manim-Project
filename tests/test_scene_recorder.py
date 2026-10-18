"""The scene recorder (P10.3, ADR 0053): a Manim scene played once, nothing drawn, recorded as data.

Recorded in this process (``record``), as the import process does it after Manim is imported.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from manim_studio import scene_recorder
from manim_studio.scene_recorder import RecordError, record


def recorded(tmp_path: Path, body: str, scene: str | None = None, header: str = "", **kwargs) -> dict:
    source = "from manim import *\n" + textwrap.dedent(header) + textwrap.dedent(body)
    path = tmp_path / "scene.py"
    path.write_text(source, encoding="utf-8")
    return record(source, str(path), scene, **kwargs)


def scene(construct: str, base: str = "Scene") -> str:
    return f"class Demo({base}):\n    def construct(self):\n" + textwrap.indent(
        textwrap.dedent(construct), " " * 8
    )


def plays(recording: dict) -> list[dict]:
    return [step for step in recording["steps"] if step["type"] == "play"]


def test_a_plain_scene_is_recorded_with_its_times_kinds_and_built_in_objects(tmp_path) -> None:
    rec = recorded(
        tmp_path,
        scene(
            """
            circle = Circle(radius=1.5, color=BLUE)
            square = Square().shift(RIGHT * 3)
            self.play(Create(circle))
            self.play(FadeIn(square, shift=UP), run_time=2)
            self.wait(0.5)
            self.play(circle.animate.shift(LEFT), rate_func=linear)
            self.play(Transform(square, Star().shift(RIGHT * 3)))
            """
        ),
    )
    assert rec["problems"] == [] and rec["scene"] == "Demo"
    assert rec["duration"] == pytest.approx(5.5)
    first, second, move, morph = plays(rec)
    assert (first["t"], first["duration"]) == (0.0, 1.0)
    assert [a["kind"] for a in first["animations"]] == ["Create"]
    assert second["t"] == 1.0 and second["animations"][0]["params"] == {"shift": "UP"}
    assert second["animations"][0]["duration"] == 2.0
    assert move["t"] == 3.5 and move["animations"][0]["kind"] == "keys"
    assert move["animations"][0]["ease"] == {"name": "linear"}
    assert morph["animations"][0]["kind"] == "Transform" and "to" in morph["animations"][0]
    names = {o["name"]: o["class"] for o in rec["objects"].values()}
    assert names == {"circle": "Circle", "square": "Square", None: "Star"}
    types = {c["spec"]["type"] for c in rec["candidates"]}
    assert {"Circle", "Square", "Star"} <= types
    square = next(c for c in rec["candidates"] if c["spec"]["type"] == "Square")
    assert square["base"]["position"] == [3.0, 0.0] and square["spec"]["params"] == {"side_length": 2.0}
    circle = next(c for c in rec["candidates"] if c["spec"]["type"] == "Circle")
    assert circle["spec"]["style"]["stroke"] == "#58C4DD"  # BLUE


def test_groups_are_flattened_with_their_own_start_times(tmp_path) -> None:
    rec = recorded(
        tmp_path,
        scene(
            """
            a, b, c = Square(), Circle(), Triangle()
            self.play(LaggedStart(FadeIn(a), FadeIn(b), lag_ratio=0.5))
            self.play(Succession(Create(c), Indicate(c)))
            """
        ),
    )
    lagged, chain = plays(rec)
    starts = [(x["start"], x["duration"], x["begin"]) for x in lagged["animations"]]
    assert starts == [(0.0, 1.0, 0.0), (0.5, 1.0, 0.0)]  # an AnimationGroup begins them all at once
    assert lagged["duration"] == 1.5
    timings = [(x["start"], x["duration"], x["begin"]) for x in chain["animations"]]
    assert timings == [(0.0, 1.0, 0.0), (1.0, 1.0, 1.0)]  # a Succession begins each in turn
    assert chain["animations"][1]["at_begin"] == chain["animations"][0]["at_finish"]


def test_what_cannot_become_clips_is_reported_with_its_line(tmp_path) -> None:
    rec = recorded(
        tmp_path,
        scene(
            """
            tracker = ValueTracker(0)
            dot = Dot().add_updater(lambda d: d.set_x(tracker.get_value()))
            self.add(dot)
            self.play(tracker.animate.set_value(2))
            self.play(Create(Square(), rate_func=lambda t: t**2))
            self.play(Spin(Square()))
            """
        ),
        header="""
        class Spin(Rotate):
            pass
        """,
    )
    source = (tmp_path / "scene.py").read_text(encoding="utf-8").splitlines()
    updater_line = next(i + 1 for i, text in enumerate(source) if "add_updater" in text)
    whats = " | ".join(p["what"] for p in rec["problems"])
    assert any(p["line"] == updater_line and "updaters" in p["what"] for p in rec["problems"]), whats
    assert "rate function" in whats and "custom animation" in whats
    anims = [a for step in plays(rec) for a in step["animations"]]
    assert any("ValueTracker" in p for a in anims for p in a["problems"])


def test_camera_scenes_are_reported(tmp_path) -> None:
    rec = recorded(tmp_path, scene("self.play(Create(Circle()))", base="MovingCameraScene"))
    assert "MovingCameraScene" in rec["problems"][0]["what"]


def test_eases_are_named_and_overshooting_content_eases_reported(tmp_path) -> None:
    rec = recorded(
        tmp_path,
        scene(
            """
            self.play(FadeIn(Square(), rate_func=there_and_back))
            self.play(Indicate(Circle()))
            self.play(GrowFromCenter(Dot(), rate_func=rate_functions.ease_out_back))
            """
        ),
    )
    fade, indicate, grow = (step["animations"][0] for step in plays(rec))
    assert fade["ease"] == {"name": "there_and_back"} and not fade["problems"]
    assert indicate["ease"] is None  # its own default (there_and_back)
    assert any("past its ends" in p for p in grow["problems"])


def test_sounds_and_subcaptions_are_kept_with_their_times(tmp_path) -> None:
    (tmp_path / "click.wav").write_bytes(b"RIFF")
    rec = recorded(
        tmp_path,
        scene(
            """
            self.wait(1)
            self.add_sound("click.wav", time_offset=0.5)
            self.play(Create(Circle()), subcaption="A circle")
            """
        ),
    )
    sound = next(s for s in rec["steps"] if s["type"] == "sound")
    assert sound["t"] == 1.5 and sound["exists"] and Path(sound["path"]).name == "click.wav"
    caption = next(s for s in rec["steps"] if s["type"] == "subcaption")
    assert (caption["t"], caption["duration"], caption["text"]) == (1.0, 1.0, "A circle")


def test_errors_say_the_line_of_the_users_code(tmp_path) -> None:
    with pytest.raises(RecordError) as info:
        recorded(tmp_path, scene("x = 1\nself.play(Create(missing))"))
    assert info.value.line == 5 and "NameError" in str(info.value)
    with pytest.raises(RecordError) as info:
        recorded(tmp_path, "class A(Scene):\n  def construct(self)\n    pass\n")
    assert info.value.line == 3 and "SyntaxError" in str(info.value)
    two = scene("pass") + "\n\nclass Other(Scene):\n    def construct(self):\n        pass\n"
    with pytest.raises(RecordError, match="choose the scene"):
        recorded(tmp_path, two)
    assert recorded(tmp_path, two, scene="Other")["scene"] == "Other"


def test_manim_is_put_back_after_recording(tmp_path) -> None:
    from manim import Mobject, config
    from manim.animation.animation import Animation

    new, add_updater, height = Animation.__dict__["__new__"], Mobject.add_updater, config.frame_height
    recorded(tmp_path, scene("self.play(Create(Circle()))"), header="config.frame_height = 9.0\n")
    assert Animation.__dict__["__new__"] is new and Mobject.add_updater is add_updater
    assert config.frame_height == height


def test_the_scene_config_gives_the_canvas(tmp_path) -> None:
    rec = recorded(
        tmp_path,
        scene("self.play(Create(Circle()))"),
        header="config.pixel_width = 640\nconfig.pixel_height = 360\nconfig.frame_rate = 15\n"
        "config.background_color = '#102030'\n",
    )
    assert rec["canvas"] == {
        "width_px": 640,
        "height_px": 360,
        "fps": 15,
        "background": "#102030",
        "frame_height": 8.0,
    }


def test_a_file_is_read_and_its_scene_recorded(tmp_path) -> None:
    path = tmp_path / "scene.py"
    path.write_text("from manim import *\n" + scene("self.play(Create(Circle()))"), encoding="utf-8")
    assert scene_recorder.record_file(path)["file"] == str(path.resolve())
    with pytest.raises(RecordError, match="cannot read"):
        scene_recorder.record_file(tmp_path / "missing.py")
