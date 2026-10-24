"""Helpers for the Code page tests: its explorer shows the project's layers in the "project" section."""

from __future__ import annotations


def project_ids(code) -> list[str]:
    return [key for section, _source, key in code.explorer.rows() if section == "project"]


def list_texts(code) -> list[str]:
    return code.explorer.texts("project")


def choose(code, row: int) -> None:
    """Click the ``row``-th layer of the project section."""
    code.explorer.select("layer", project_ids(code)[row])
