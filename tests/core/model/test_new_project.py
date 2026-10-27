"""What a new project is made of: file names, locations, the canvas the settings describe."""

from __future__ import annotations

import pytest

from manim_studio.core.model import new_project as rules
from manim_studio.core.model.new_project import NewProjectSettings


@pytest.mark.parametrize("name", ["", "   ", "a/b", "a:b", 'say "hi"', "what?", "con", "NUL", "end."])
def test_a_name_that_cannot_be_a_file_name_is_refused_with_a_reason(name) -> None:
    assert rules.name_problem(name)


@pytest.mark.parametrize("name", ["Untitled", "Euler 2", "Derivative - part 1", "café"])
def test_an_ordinary_name_is_fine(name) -> None:
    assert rules.name_problem(name) == ""


def test_an_existing_project_blocks_the_name_and_a_free_name_skips_it(tmp_path) -> None:
    assert rules.location_problem(tmp_path, "Intro") == ""
    (tmp_path / "Intro.json").write_text("{}")
    assert "already exists" in rules.location_problem(tmp_path, "Intro")
    assert rules.free_name(tmp_path, "Intro") == "Intro 2"
    (tmp_path / "Intro 2.json").write_text("{}")
    assert rules.free_name(tmp_path, "Intro") == "Intro 3"
    assert rules.free_name(tmp_path / "missing") == "Untitled"  # a folder that will be made


def test_a_folder_that_is_a_file_or_empty_is_refused(tmp_path) -> None:
    (tmp_path / "plain").write_text("x")
    assert rules.location_problem(tmp_path / "plain", "A")
    assert rules.location_problem("  ", "A")
    assert rules.location_problem(tmp_path / "not-yet", "A") == ""  # it is created with the project


def test_the_settings_make_the_blank_project_they_describe(tmp_path) -> None:
    settings = NewProjectSettings(
        name=" Intro ",
        folder=tmp_path,
        morph_matching="classic",
        width_px=1080,
        height_px=1920,
        fps=60,
        duration=12.5,
        background="#10142a",
    )
    assert settings.path == tmp_path / "Intro.json"
    project = settings.blank_project()
    canvas = project.canvas
    assert (canvas.width_px, canvas.height_px, canvas.fps, canvas.duration) == (1080, 1920, 60, 12.5)
    assert canvas.background == "#10142a" and project.morph_matching == "classic" and not project.layers
    assert NewProjectSettings().path is None  # untitled: no folder, no file


def test_the_length_is_kept_within_the_limits() -> None:
    assert NewProjectSettings(duration=0.0).canvas().duration == rules.MIN_SECONDS
    assert NewProjectSettings(duration=9999).canvas().duration == rules.MAX_SECONDS


def test_the_default_size_is_the_long_standing_canvas() -> None:
    _, width, height = rules.SIZES[0]
    assert (width, height) == (1280, 720) and (
        NewProjectSettings().width_px,
        NewProjectSettings().height_px,
    ) == (
        width,
        height,
    )
    assert 30 in rules.FRAME_RATES and rules.BACKGROUNDS[0][1] == "#000000"
