"""Release check (P6e): build the package and prove the built wheel works on its own.

1. ``uv build`` the wheel and sdist into a work folder;
2. a fresh Python 3.13 venv there (an ASCII path: the system temp folder by default),
   with only the wheel installed;
3. ``manim-studio --version`` reports pyproject's version;
4. ``manim-studio render`` of a committed example writes every frame;
5. the editor opens offscreen from the installed package - every user folder
   redirected into the work folder - with its five pages and the built-in presets.

Nothing is uploaded or published. Run from the repository root:

    .venv/Scripts/python scripts/release_check.py [--work DIR] [--example examples/euler.json] [--clean]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GUI_CHECK = """
import json, os, sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from manim_studio.ui import theme
from manim_studio.ui.main_window import MainWindow
app = QApplication([])
theme.apply(app)
window = MainWindow()
window.resize(1280, 800)
window.show()
window.load(Path(sys.argv[1]))
app.processEvents()
result = {
    "pages": list(window.pages.pages),
    "presets": len(window.library.presets),
    "themes": len(window.library.themes),
    "templates": len(window.library.templates),
    "layers": len(window.project.layers),
}
window.document.undo_stack.setClean()
window.close()
print(json.dumps(result))
"""

FRAME_COUNT = """
import av, sys
with av.open(sys.argv[1]) as video:
    print(sum(1 for _ in video.decode(video=0)))
"""


def run(args: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> str:
    started = time.perf_counter()
    done = subprocess.run(
        args, capture_output=True, text=True, env=env, cwd=cwd, encoding="utf-8", errors="replace"
    )
    took = time.perf_counter() - started
    if done.returncode != 0:
        print(done.stdout[-2000:], done.stderr[-4000:], sep="\n")
        raise SystemExit(f"FAILED ({done.returncode}): {' '.join(args)}")
    shown = " ".join(
        Path(a).name if i == 0 else a.splitlines()[0][:40] for i, a in enumerate(map(str, args[:3]))
    )
    print(f"  ok in {took:5.1f} s: {shown} ...")
    return done.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--work", type=Path, help="work folder (default: a new one in the system temp folder)"
    )
    parser.add_argument("--example", type=Path, default=Path("examples/euler.json"))
    parser.add_argument("--clean", action="store_true", help="delete the work folder at the end")
    options = parser.parse_args(argv)

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    work = options.work or Path(tempfile.mkdtemp(prefix="ms-release-"))
    work.mkdir(parents=True, exist_ok=True)
    print(f"release check of manim-studio {version} in {work}")

    print("1. build")
    run(["uv", "build", "--out-dir", str(work / "dist")], cwd=ROOT)
    wheel = next((work / "dist").glob(f"manim_studio-{version}-*.whl"))

    print("2. a fresh venv with only the wheel")
    venv = work / "venv"
    run(["uv", "venv", "--python", "3.13", str(venv)])
    python = venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"
    tool = venv / "Scripts" / "manim-studio.exe" if sys.platform == "win32" else venv / "bin" / "manim-studio"
    run(["uv", "pip", "install", "--python", str(python), str(wheel)])

    print("3. --version")
    reported = run([str(tool), "--version"]).strip()
    if not reported.startswith(f"manim-studio {version} "):
        raise SystemExit(f"FAILED: --version said {reported!r}")

    print("4. render a committed example")
    example = work / options.example.name
    example.write_text(
        subprocess.run(
            ["git", "show", f"HEAD:{options.example.as_posix()}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout,
        encoding="utf-8",
    )
    canvas = json.loads(example.read_text(encoding="utf-8"))["canvas"]
    expected = round(canvas.get("duration", 0) * canvas.get("fps", 30))
    video = work / "example.mp4"
    run([str(tool), "render", str(example), str(video)], cwd=work)
    frames = int(run([str(python), "-c", FRAME_COUNT, str(video)]).strip())
    if expected and frames != expected:
        raise SystemExit(f"FAILED: {frames} frames, expected {expected}")
    print(f"     {frames} frames")

    print("5. the editor, offscreen, from the installed package")
    env = {
        **__import__("os").environ,
        "QT_QPA_PLATFORM": "offscreen",
        "MANIM_STUDIO_PREVIEW": "0",
        "MANIM_STUDIO_AUDIO": "0",
        "MANIM_STUDIO_SETTINGS": str(work / "settings.ini"),
        "MANIM_STUDIO_LIBRARY": str(work / "library"),
        "MANIM_STUDIO_RECOVERY": str(work / "recovery"),
        "MANIM_STUDIO_PLUGINS": str(work / "plugins"),
    }
    env.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if sys.platform == "win32" else "")
    gui = json.loads(
        run([str(python), "-c", GUI_CHECK, str(example)], env=env, cwd=work).strip().splitlines()[-1]
    )
    print(f"     {gui}")
    if gui["pages"] != ["compose", "animate", "code", "audio", "deliver"] or gui["presets"] < 32:
        raise SystemExit(f"FAILED: the editor opened with {gui}")

    print(f"all checks passed: {wheel.name}")
    if options.clean:
        shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
