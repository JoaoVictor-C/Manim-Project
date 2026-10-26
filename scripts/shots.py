"""Screenshots of every page, offscreen, for comparing the interface with its mock-ups (P17).

The window is built with every user folder redirected to a temporary folder and no preview process, so the
output depends on the code and the project only. Fonts are the bundled ones.

    python scripts/shots.py OUT_DIR                            # Ink, euler.json, 1600 x 900
    python scripts/shots.py OUT_DIR --theme paper --size 1440x900
    python scripts/shots.py OUT_DIR --project examples/showcase.json --pages compose code
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PAGES = ("compose", "animate", "code", "audio", "deliver")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--theme", choices=("ink", "paper"), default="ink")
    parser.add_argument("--size", default="1600x900")
    parser.add_argument("--project", type=Path, default=ROOT / "examples" / "euler.json")
    parser.add_argument("--pages", nargs="*", default=list(PAGES))
    parser.add_argument("--welcome", action="store_true", help="also grab the welcome page (no project)")
    args = parser.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="shots-"))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["MANIM_STUDIO_SETTINGS"] = str(work / "settings.ini")
    os.environ.setdefault("MANIM_STUDIO_PREVIEW", "0")
    os.environ.setdefault("MANIM_STUDIO_CODE", "0")
    os.environ.setdefault("MANIM_STUDIO_AUDIO", "0")
    os.environ.setdefault("MANIM_STUDIO_RECOVERY", str(work / "recovery"))
    os.environ.setdefault("MANIM_STUDIO_PRESETS", str(work / "presets.json"))

    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    from manim_studio.ui.main_window import MainWindow
    from manim_studio.ui.style import theme

    theme.apply(app, theme.THEMES[args.theme])
    width, height = (int(x) for x in args.size.lower().split("x"))
    args.out.mkdir(parents=True, exist_ok=True)
    window = MainWindow()
    window.resize(width, height)
    window.show()

    def settle(rounds: int = 40) -> None:
        for _ in range(rounds):
            app.processEvents()

    settle()
    if args.welcome:
        window.grab().save(str(args.out / f"welcome-{args.theme}.png"))
    window.load(args.project)
    settle()
    for page in args.pages:
        window.show_page(page)
        settle()
        target = args.out / f"{page}-{args.theme}.png"
        window.grab().save(str(target))
        print(target)
    window.document.undo_stack.setClean()
    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
