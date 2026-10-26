"""B57 - the Code page's editor: what highlighting and the dirty check cost on a long file.

The editor re-lexes only the lines that change (Qt's block states carry a triple quoted string over
lines) and compares its text with the project's on every keystroke (the dirty marker). With a
2000-line scene (about 140 KB):

1. the pure lexer over the whole text (``code_syntax.scan``);
2. putting the text in the editor (``set_text``: highlight everything, lay out, line numbers);
3. one typed character in the middle (``insertPlainText``, which re-highlights that line and the
   lines after it only while the block state changes), with and without a triple quoted string
   opening above it (the worst case: every line below changes state);
4. what the page adds per keystroke: ``toPlainText`` and the comparison with the project's code;
5. switching to the Code page and back (parking, re-parenting, splitter sizes), 2000 lines open.

Run: ``python benchmarks/bench_code_editor.py``.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for name in ("MANIM_STUDIO_PREVIEW", "MANIM_STUDIO_WORKER", "MANIM_STUDIO_AUDIO", "MANIM_STUDIO_CODE"):
    os.environ.setdefault(name, "0")

from PySide6.QtWidgets import QApplication  # noqa: E402

from manim_studio.core.engine import adapter  # noqa: E402
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec  # noqa: E402
from manim_studio.ui.code.code_editor import CodeEditor  # noqa: E402
from manim_studio.ui.code.code_syntax import scan  # noqa: E402
from manim_studio.ui.main_window import MainWindow  # noqa: E402
from manim_studio.ui.style import theme  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LINES = 2000


def source() -> str:
    head = "class Big(Scene):\n    def construct(self):\n"
    body = [
        f"        c{i} = Circle(radius={i % 7}.5, color=RED).shift(UP * {i % 5})  # circle number {i}\n"
        f'        self.play(Create(c{i}), Write(Text("label {i}", font_size=24)), run_time=0.1)'
        for i in range(LINES // 2)
    ]
    return head + "\n".join(body) + "\n"


def timed(fn, repeat: int = 20) -> tuple[float, float]:
    """Median and worst of ``repeat`` runs, in milliseconds."""
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), max(samples)


def main() -> None:
    app = QApplication(sys.argv)
    theme.apply(app)
    adapter.configure(ROOT / ".cache" / "manim")
    text = source()
    print(f"{text.count(chr(10))} lines, {len(text) / 1024:.0f} KB")

    median, worst = timed(lambda: scan(text), 10)
    print(f"1. lexer over the whole text: {median:.1f} ms (worst {worst:.1f})")

    editor = CodeEditor()
    editor.resize(900, 700)
    editor.show()
    app.processEvents()
    median, worst = timed(lambda: (editor.set_text(text), app.processEvents()), 5)
    print(f"2. set_text (highlight, layout, repaint): {median:.1f} ms (worst {worst:.1f})")

    editor.set_cursor(len(text) // 2)
    median, worst = timed(lambda: (editor.insertPlainText("x"), app.processEvents()))
    print(f"3a. one typed character mid-file: {median:.2f} ms (worst {worst:.2f})")

    editor.set_text(
        text.replace("class Big", 'doc = """open\nclass Big', 1)
    )  # a string opens above everything
    editor.set_cursor(len(text) // 2)
    app.processEvents()
    median, worst = timed(lambda: (editor.insertPlainText("x"), app.processEvents()))
    print(
        f"3b. same, a triple quote open above (all lines below change state back and forth): "
        f"{median:.2f} ms (worst {worst:.2f})"
    )
    editor.set_text(text)
    editor.set_cursor(len(text) // 2)
    editor.insertPlainText('"""')  # opens a string mid-file: lines below flip to string and back
    app.processEvents()
    median, worst = timed(
        lambda: (editor.insertPlainText('"'), editor.textCursor().deletePreviousChar(), app.processEvents()),
        10,
    )
    print(f"3c. typing and deleting a quote after an open string: {median:.2f} ms (worst {worst:.2f})")

    project_text = text
    median, worst = timed(lambda: editor.toPlainText() != project_text, 200)
    print(f"4. toPlainText and compare with the project's code: {median:.3f} ms (worst {worst:.3f})")

    window = MainWindow()
    window.resize(1600, 1000)
    window.show()
    project = Project(
        canvas=Canvas(width_px=320, height_px=180),
        layers=[Layer(id="big", name="Big", spec=Spec(type="Code", params={"code": text}))],
    )
    path = ROOT / ".cache" / "bench_code_editor.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    window.ask_trust = lambda names: "skip"
    window.load(path)
    app.processEvents()
    window.show_page("code")
    app.processEvents()
    page = window.pages.pages["code"]

    def switch() -> None:
        window.show_page("compose")
        window.show_page("code")
        app.processEvents()

    median, worst = timed(switch, 10)
    print(f"5. Compose <-> Code round trip, {LINES} lines open: {median:.1f} ms (worst {worst:.1f})")
    page.editor.set_cursor(len(text) // 2)
    median, worst = timed(lambda: (page.editor.insertPlainText("x"), app.processEvents()))
    print(f"6. a typed character through the page: {median:.2f} ms (worst {worst:.2f})")
    page.editor.textChanged.disconnect(page._on_text_changed)
    median, worst = timed(lambda: (page.editor.insertPlainText("x"), app.processEvents()))
    print(f"6b. the same without the page's dirty check: {median:.2f} ms (worst {worst:.2f})")
    window.close()


if __name__ == "__main__":
    main()
