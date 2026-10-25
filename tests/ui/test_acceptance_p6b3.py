"""P6b.3 acceptance: the Code page end to end, with the real code runner (ADR 0019, 0041).

On the Code page a new code layer gets a scene with a typo. Run (Ctrl+Enter) applies and trusts
it as one undo step; the renderer reports a NameError at line 4, shown under the editor; clicking
it puts the cursor on that line; the line is fixed, Run again, and the frame - a green square -
appears on the shared canvas, composited by the editor.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from manim_studio.core.code_frame import CodeFrame
from manim_studio.ui.main_window import MainWindow
from ui.code_page_helpers import list_texts
from ui.test_acceptance_v1 import menu_action, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # starts real processes

BROKEN = """class Block(Scene):
    def construct(self):
        block = Square(side_length=4, color=GREEN, fill_opacity=1)
        self.add(Squre(side_length=4, color=GREEN, fill_opacity=1))
        self.play(block.animate.rotate(PI / 8), run_time=0.5)
"""
FIXED_LINE = "        self.add(block)"


@pytest.fixture
def window(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("MANIM_STUDIO_CODE", "1")
    monkeypatch.setenv("MANIM_STUDIO_TRUST_FILE", str(tmp_path / "trusted.json"))
    win = MainWindow()
    win.resize(1500, 850)
    win.show()
    yield win
    win.close()


def centre_is_green(window) -> bool:
    """Is the square's green near the middle of the canvas (off its centre, where the selection's mark is)?"""
    image = window.canvas.grab().toImage()
    pixel = image.pixelColor(image.width() // 2 + 40, image.height() // 2 + 40)
    return pixel.green() > 120 and pixel.green() > pixel.red() + 30 and pixel.green() > pixel.blue() + 30


def test_write_run_see_the_error_at_its_line_fix_it_and_see_the_frame(window, qt_app) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    window.show_page("code")
    code = window.pages.pages["code"]
    assert len(list_texts(code)) == 0 and not code.editor.isEnabled()

    # 1. a new code layer: the starter scene runs (library code is trusted) and renders
    code.new_actions["layer"].trigger()
    wait_until(qt_app, lambda: code.layer_id is not None)
    layer_id = code.layer_id
    assert code.editor.text().startswith("class Orbit(Scene)") and window.selection.layer_id == layer_id
    wait_until(qt_app, lambda: code.state_label.text().startswith("Ready"), timeout=180)

    # 2. a scene with a typo on line 4: typed in, nothing runs until Run
    steps = window.document.undo_stack.count()
    code.editor.replace_text(BROKEN)
    assert code.is_dirty() and code.dirty_label.isVisible() and window.document.undo_stack.count() == steps
    assert window.code.status(layer_id).state == "ready"  # still the starter's render
    QTest.keyClick(code.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert not code.is_dirty() and window.document.undo_stack.count() == steps + 1
    assert window.project.layer(layer_id).spec.params["code"] == BROKEN
    assert window.trust.is_trusted(BROKEN)

    # 3. the error arrives under the editor, with its line
    wait_until(qt_app, lambda: code.state_label.text() == "Error", timeout=180)
    assert code.error_label.plain.startswith("line 4: NameError") and "Squre" in code.error_label.plain
    assert code.editor.error_line == 4
    assert "!" in list_texts(code)[0]  # the list marks the failed layer

    # 4. clicking the error moves the cursor to the line
    code.editor.go_to_line(1)
    QTest.mouseClick(code.error_label, Qt.MouseButton.LeftButton)
    assert code.editor.current_line() == 4
    assert code.editor.textCursor().block().text().strip().startswith("self.add(Squre")

    # 5. fix that line and run again
    cursor = code.editor.textCursor()
    cursor.select(QTextCursor.SelectionType.LineUnderCursor)
    cursor.insertText(FIXED_LINE)
    code.editor.setTextCursor(cursor)
    assert code.is_dirty() and code.state_label.text().startswith("Error (from the last run)")
    assert code.editor.error_line is None  # lines of edited text are not tinted
    QTest.keyClick(code.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert window.document.undo_stack.count() == steps + 2
    wait_until(qt_app, lambda: code.state_label.text().startswith("Ready"), timeout=180)
    assert not code.error_label.isVisible() and code.editor.error_line is None

    # 6. the shared canvas shows the green square the code draws
    window.seek(0.0)
    wait_until(qt_app, lambda: isinstance(dict(window.evaluator.frame_layers(0.0))[layer_id], CodeFrame))
    qt_app.processEvents()
    assert centre_is_green(window)

    # 7. the page keeps working with the rest of the editor: undo the fix
    window.document.undo_stack.undo()
    assert code.editor.text() == BROKEN and not code.is_dirty()
