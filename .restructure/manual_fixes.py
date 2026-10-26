"""The few edits no import rewrite can make: places that depend on where a file lives.

Run from the repository root, after codemod.py apply. Each edit asserts what it replaces, so a tree that is
not the expected one fails loudly instead of being half-fixed.
"""

from pathlib import Path

ROOT = Path.cwd()


def sub(path: str, old: str, new: str, count: int = 1) -> None:
    p = ROOT / path
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    assert text.count(old) == count, f"{path}: expected {count} of {old!r}, found {text.count(old)}"
    text = text.replace(old, new)
    p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


# the files that ship with the package are found through one place: manim_studio.data
sub(
    "src/manim_studio/core/editing/library.py",
    'BUILTIN_FOLDER = Path(__file__).resolve().parent.parent / "library"',
    'BUILTIN_FOLDER = data.FOLDER / "library"',
)
sub(
    "src/manim_studio/core/assist/manim_names.py",
    'FILE = Path(__file__).with_name("manim_names.json")',
    'FILE = data.FOLDER / "manim_names.json"',
)
sub(
    "scripts/gen_manim_names.py",
    'OUTPUT = ROOT / "src" / "manim_studio" / "core" / "manim_names.json"',
    'OUTPUT = ROOT / "src" / "manim_studio" / "data" / "manim_names.json"',
)

# the theme test scans the whole ui package, not just the folder theme.py moved to; and says so if it does not
sub(
    "tests/ui/style/test_theme.py",
    "UI = Path(theme.__file__).resolve().parent\n",
    "UI = Path(theme.__file__).resolve().parents[1]  # the whole ui package, not just ui/style\n",
)
sub(
    "tests/ui/style/test_theme.py",
    '    offenders = []\n    for path in UI.rglob("*.py"):\n        if path.name == "theme.py":\n            continue\n',
    '    offenders = []\n    scanned = 0\n    for path in UI.rglob("*.py"):\n        if path.name == "theme.py":\n            continue\n        scanned += 1\n',
)
sub(
    "tests/ui/style/test_theme.py",
    "    assert offenders == []\n\n\ndef test_document_colours_are_not_themed",
    '    assert scanned > 60, f"only {scanned} files scanned: is UI the whole ui package?"\n'
    "    assert offenders == []\n\n\ndef test_document_colours_are_not_themed",
)

# ... and they import it (isort puts the line in order later)
sub("src/manim_studio/core/editing/library.py", "from . import edits\n", "from ... import data\nfrom . import edits\n")
sub(
    "src/manim_studio/core/assist/manim_names.py",
    "from pathlib import Path\n\nFILE =",
    "\nfrom ... import data\n\nFILE =",
)
