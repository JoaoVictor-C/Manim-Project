"""The version (P6e): pyproject.toml is the one source, the CLI reports it."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import manim_studio
from manim_studio import cli

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_the_package_version_is_pyprojects() -> None:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert manim_studio.__version__ == declared


def test_version_flag_prints_the_versions_and_exits(capsys) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"])
    assert stop.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith(f"manim-studio {manim_studio.__version__} (Manim 0.22.0, Python 3.")
