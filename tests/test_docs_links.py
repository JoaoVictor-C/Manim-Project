"""The documentation's links resolve (scripts/check_docs.py): relative paths, #anchors, fence languages."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts" / "check_docs.py")
check_docs = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("check_docs", check_docs)  # dataclasses look their module up by name
_spec.loader.exec_module(check_docs)


def test_every_markdown_file_in_the_repository_has_working_links() -> None:
    problems = check_docs.check()
    assert not problems, "\n".join(str(p) for p in problems)


def test_the_user_guide_and_the_front_door_are_checked() -> None:
    files = {p.relative_to(ROOT).as_posix() for p in check_docs.markdown_files()}
    assert {"README.md", "CONTRIBUTING.md", "docs/README.md", "docs/guide/index.md"} <= files
    assert not any(f.startswith((".venv/", "projects/", "media/", "out/")) for f in files)


@pytest.mark.parametrize(
    ("heading", "anchor"),
    [
        ("Phase 0 — core ✅ (2026-10-09)", "phase-0--core--2026-10-09"),
        ("1. Set up", "1-set-up"),
        ("`manim-studio render`", "manim-studio-render"),
        ("Where files live", "where-files-live"),
        ("Colour a part [link](x.md)", "colour-a-part-link"),
    ],
)
def test_anchors_are_slugged_as_github_does(heading: str, anchor: str) -> None:
    assert check_docs.slug(heading) == anchor


def test_broken_links_bad_anchors_and_unknown_fences_are_found(tmp_path: Path) -> None:
    (tmp_path / "other.md").write_text("# Real heading\n\n## Twice\n\n## Twice\n", encoding="utf-8")
    page = tmp_path / "page.md"
    page.write_text(
        "[ok](other.md#real-heading) [ok](other.md#twice-1) [web](https://example.com)\n"
        "[missing](nowhere.md) [bad](other.md#nope) `[code](ignored.md)`\n"
        "```pythn\n[inside](ignored.md)\n```\n"
        "[ref]: gone/\n",
        encoding="utf-8",
    )
    messages = [(p.line, p.message) for p in check_docs.check_file(page)]
    assert messages == [
        (2, "broken link: nowhere.md"),
        (2, "no heading for anchor: other.md#nope"),
        (3, "unknown code fence language 'pythn'"),
        (6, "broken link: gone/"),
    ]
