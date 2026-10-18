"""Check the repository's Markdown: relative links, #anchors and fenced code languages.

For every ``.md`` file given (default: all of them in the repository, outside hidden and
scratch folders):

* a relative link ``[text](path)``, ``[text](path#anchor)`` or ``[text](#anchor)`` - and a
  reference definition ``[name]: path`` - must name a file or folder that exists;
* an ``#anchor`` into a Markdown file must match one of its headings, slugged the way GitHub
  does (lower case, punctuation dropped, spaces to hyphens, ``-1``, ``-2``... for repeats);
* an opening code fence's language, when given, must be one of ``LANGUAGES``.

Links inside code (fenced blocks and `inline code`) are ignored, and so are web links
(``http:``, ``https:``, ``mailto:``). Standard library only.

    python scripts/check_docs.py                 # every Markdown file
    python scripts/check_docs.py README.md docs/guide

Exit status 1 when a problem was found; each is printed as ``path:line: message``.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
# Folders never searched: scratch output, caches, the user's own projects (not in the repository).
SKIP_DIRS = {"media", "out", "projects", "build", "dist", "node_modules", "__pycache__"}
LANGUAGES = {
    "",
    "bash",
    "bat",
    "cmd",
    "console",
    "csv",
    "diff",
    "html",
    "ini",
    "json",
    "latex",
    "markdown",
    "md",
    "mermaid",
    "powershell",
    "ps1",
    "py",
    "pycon",
    "python",
    "sh",
    "shell",
    "srt",
    "tex",
    "text",
    "toml",
    "txt",
    "xml",
    "yaml",
    "yml",
}

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^`\s]*)")
INLINE_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)*?\1")
EXTERNAL = ("http://", "https://", "mailto:", "ftp://")
# Not links but placeholders to fill in: (file, target).
PLACEHOLDERS = {("docs/adr/template.md", "NNNN-....md")}


@dataclass(frozen=True)
class Problem:
    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        try:
            shown = self.path.relative_to(ROOT)
        except ValueError:
            shown = self.path
        return f"{shown.as_posix()}:{self.line}: {self.message}"


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def markdown_files(paths: list[Path] | None = None) -> list[Path]:
    """The Markdown files under ``paths`` (files or folders; default: the repository)."""
    out: set[Path] = set()
    for start in paths or [ROOT]:
        start = start.resolve()
        if start.is_file():
            out.add(start)
            continue
        for path in start.rglob("*.md"):
            parts = path.relative_to(start).parts[:-1]
            if any(part.startswith(".") or part in SKIP_DIRS for part in parts):
                continue
            out.add(path)
    return sorted(out)


def _lines_outside_code(text: str) -> list[tuple[int, str, str | None]]:
    """(line number, line, fence language or None) - the line with inline code removed, or, for
    an opening fence, its language; lines inside fenced blocks are left out."""
    out: list[tuple[int, str, str | None]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        match = FENCE.match(line)
        if fence is None and match:
            fence = match.group(1)
            out.append((number, "", match.group(2)))
            continue
        if fence is not None:
            if (
                match
                and match.group(1)[0] == fence[0]
                and len(match.group(1)) >= len(fence)
                and not match.group(2)
            ):
                fence = None
            continue
        out.append((number, CODE_SPAN.sub("", line), None))
    return out


def slug(heading: str) -> str:
    """GitHub's anchor for a heading's text."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # a link in a heading: its text
    text = re.sub(r"<[^>]+>", "", text).replace("`", "")
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


@cache
def anchors(path: Path) -> frozenset[str]:
    """Every heading anchor of a Markdown file (repeats numbered as GitHub numbers them)."""
    seen: dict[str, int] = {}
    out: set[str] = set()
    for _number, line, language in _lines_outside_code(path.read_text(encoding="utf-8")):
        if language is not None:
            continue
        match = HEADING.match(line)
        if not match:
            continue
        base = slug(match.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.add(base if count == 0 else f"{base}-{count}")
    return frozenset(out)


def _targets(line: str) -> list[str]:
    found = [m.group(1) for m in INLINE_LINK.finditer(line)]
    ref = REFERENCE.match(line)
    if ref:
        found.append(ref.group(1))
    return found


def check_file(path: Path) -> list[Problem]:
    problems: list[Problem] = []
    for number, line, language in _lines_outside_code(path.read_text(encoding="utf-8")):
        if language is not None:
            if language.lower() not in LANGUAGES:
                problems.append(Problem(path, number, f"unknown code fence language {language!r}"))
            continue
        for target in _targets(line):
            if not target or target.startswith(EXTERNAL) or (_rel(path), target) in PLACEHOLDERS:
                continue
            file_part, _, anchor = target.partition("#")
            file_part = unquote(file_part)
            dest = (path.parent / file_part).resolve() if file_part else path
            if not dest.exists():
                problems.append(Problem(path, number, f"broken link: {target}"))
                continue
            into_markdown = anchor and dest.is_file() and dest.suffix.lower() == ".md"
            if into_markdown and unquote(anchor).lower() not in anchors(dest):
                problems.append(Problem(path, number, f"no heading for anchor: {target}"))
    return problems


def check(paths: list[Path] | None = None) -> list[Problem]:
    """Every problem in the Markdown files under ``paths`` (default: the repository)."""
    return [problem for path in markdown_files(paths) for problem in check_file(path)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, help="files or folders (default: the repository)")
    args = parser.parse_args(argv)
    files = markdown_files(args.paths or None)
    problems = [problem for path in files for problem in check_file(path)]
    for problem in problems:
        print(problem)
    print(f"{len(files)} Markdown files checked, {len(problems)} problem(s)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
