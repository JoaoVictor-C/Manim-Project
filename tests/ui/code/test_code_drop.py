"""Code dropped on the editor (P12.7): a preset or code layer dragged from the Code workspace
(``code_drag``) or ``.py`` files from the desktop, dropped on the timeline (at a time), the canvas
(at a point in scene units) or the layers list (where it fits). The window's hooks are recorded;
other drags are refused as before and the layers list still reorders."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.session import code_drag
from manim_studio.ui.timeline.view import RULER_HEIGHT

pytestmark = [
    pytest.mark.ui,
    # PySide flags the drag events' QPoint constructors, the only ones Qt 6 has for them
    pytest.mark.filterwarnings("ignore:Function.*QDrag.*deprecated:DeprecationWarning"),
]

FPS = 10
FRAME = 1 / FPS
SCENE = "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=FPS, duration=4.0),
        layers=[Layer(id="dot", spec=Spec(type="Circle")), Layer(id="box", spec=Spec(type="Square"))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("compose")
    qt_app.processEvents()
    win.calls = []
    monkeypatch.setattr(win, "place_code", lambda code, **kw: win.calls.append(("place", code, kw)))
    monkeypatch.setattr(win, "import_code_files", lambda paths, **kw: win.calls.append(("import", paths, kw)))
    yield win
    win.close()


def preset() -> QMimeData:
    return code_drag.encode("preset", "orbit-id", "Orbit", "scene")


def files(tmp_path, name: str = "orbit.py") -> QMimeData:
    path = tmp_path / name
    path.write_text(SCENE, encoding="utf-8")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def text() -> QMimeData:
    mime = QMimeData()
    mime.setText("just some text")
    return mime


ACTIONS = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
BUTTONS = Qt.MouseButton.LeftButton
NO_KEYS = Qt.KeyboardModifier.NoModifier


def enter(target, pos: QPointF, mime: QMimeData) -> bool:
    event = QDragEnterEvent(pos.toPoint(), ACTIONS, mime, BUTTONS, NO_KEYS)
    QApplication.sendEvent(target, event)
    return event.isAccepted()


def hover(target, pos: QPointF, mime: QMimeData) -> bool:
    event = QDragMoveEvent(pos.toPoint(), ACTIONS, mime, BUTTONS, NO_KEYS)
    QApplication.sendEvent(target, event)
    return event.isAccepted()


def leave(target) -> None:
    QApplication.sendEvent(target, QDragLeaveEvent())


def drop(target, pos: QPointF, mime: QMimeData, qt_app, modifiers=NO_KEYS) -> bool:
    """Enter, move and drop at ``pos``; the hooks run after the drop returns."""
    enter(target, pos, mime)
    hover(target, pos, mime)
    event = QDropEvent(pos, ACTIONS, mime, BUTTONS, modifiers, QEvent.Type.Drop)
    QApplication.sendEvent(target, event)
    qt_app.processEvents()
    return event.isAccepted()


def drop_anyway(widget, pos: QPointF, mime: QMimeData, qt_app) -> None:
    """A drop handed to ``widget.dropEvent`` itself (Qt never delivers one whose entry was
    refused), to show it still hands nothing but code to the window."""
    widget.dropEvent(QDropEvent(pos, ACTIONS, mime, BUTTONS, NO_KEYS, QEvent.Type.Drop))
    qt_app.processEvents()


# -- the timeline ----------------------------------------------------------------------------


def at_time(window, t: float) -> QPointF:
    return QPointF(window.timeline._viewport_x(t), RULER_HEIGHT + 10)


def test_a_preset_dropped_on_the_timeline_is_placed_at_that_time(window, qt_app) -> None:
    view = window.timeline
    assert enter(view.viewport(), at_time(window, 2.0), preset())
    assert view.drop_at == pytest.approx(2.0, abs=FRAME)  # the line shows where it lands
    assert drop(view.viewport(), at_time(window, 2.0), preset(), qt_app)
    assert view.drop_at is None
    [(hook, code, kw)] = window.calls
    assert (hook, code["from"], code["id"], code["kind"]) == ("place", "preset", "orbit-id", "scene")
    assert kw["position"] is None
    assert kw["t"] == pytest.approx(2.0, abs=FRAME)


def test_the_drop_time_is_on_a_frame_and_never_before_zero(window, qt_app) -> None:
    view = window.timeline
    drop(view.viewport(), at_time(window, 1.23), preset(), qt_app)
    t = window.calls[-1][2]["t"]
    assert t == pytest.approx(1.2, abs=FRAME) and round(t * FPS) == pytest.approx(t * FPS)
    drop(view.viewport(), QPointF(view._viewport_x(0.0) - 40, RULER_HEIGHT + 10), preset(), qt_app)
    assert window.calls[-1][2]["t"] == 0.0


def test_py_files_dropped_on_the_timeline_are_imported_at_that_time(window, qt_app, tmp_path) -> None:
    assert drop(window.timeline.viewport(), at_time(window, 3.0), files(tmp_path), qt_app)
    [(hook, paths, kw)] = window.calls
    assert hook == "import" and [p.name for p in paths] == ["orbit.py"]
    assert kw["t"] == pytest.approx(3.0, abs=FRAME) and kw["position"] is None


def refused_by_timeline(window, mime: QMimeData) -> bool:
    """The graphics scene takes every drag's entry and refuses it on the first move (no item
    takes drops): as before P12.7, a drag the timeline refuses is one whose moves it ignores."""
    viewport = window.timeline.viewport()
    enter(viewport, at_time(window, 1.0), mime)
    return not hover(viewport, at_time(window, 1.0), mime) and window.timeline.drop_at is None


def test_the_timeline_refuses_text_and_other_files(window, qt_app, tmp_path) -> None:
    view = window.timeline
    assert refused_by_timeline(window, text())
    assert refused_by_timeline(window, files(tmp_path, "notes.txt"))
    drop(view.viewport(), at_time(window, 1.0), text(), qt_app)
    drop_anyway(view, at_time(window, 1.0), text(), qt_app)
    assert window.calls == [] and view.drop_at is None


def test_the_timeline_line_goes_when_the_drag_leaves(window) -> None:
    view = window.timeline
    enter(view.viewport(), at_time(window, 1.0), preset())
    assert hover(view.viewport(), at_time(window, 1.5), preset())
    assert view.drop_at == pytest.approx(1.5, abs=FRAME)  # it follows the drag
    leave(view.viewport())
    assert view.drop_at is None and window.calls == []


# -- the canvas ------------------------------------------------------------------------------


def centre(canvas) -> QPointF:
    return QPointF(canvas.width() / 2, canvas.height() / 2)


def test_a_preset_dropped_on_the_canvas_centre_is_placed_at_the_origin(window, qt_app) -> None:
    canvas = window.canvas
    assert enter(canvas, centre(canvas), preset())
    assert canvas.drop_point == centre(canvas)  # the cross shows where it lands
    assert drop(canvas, centre(canvas), preset(), qt_app)
    assert canvas.drop_point is None
    [(hook, code, kw)] = window.calls
    assert hook == "place" and code["name"] == "Orbit" and kw["t"] is None
    assert kw["position"] == pytest.approx((0.0, 0.0), abs=1e-6)


def test_a_drop_on_the_canvas_converts_to_scene_units(window, qt_app) -> None:
    canvas = window.canvas
    ppu = canvas.px_per_unit()
    pos = centre(canvas) + QPointF(2 * ppu, -1 * ppu)  # two units right, one up (y is up)
    drop(canvas, pos, preset(), qt_app)
    assert window.calls[-1][2]["position"] == pytest.approx((2.0, 1.0), abs=0.05)


def test_py_files_dropped_on_the_canvas_are_imported_at_that_point(window, qt_app, tmp_path) -> None:
    canvas = window.canvas
    assert drop(canvas, centre(canvas), files(tmp_path), qt_app)
    [(hook, paths, kw)] = window.calls
    assert hook == "import" and [p.name for p in paths] == ["orbit.py"]
    assert kw["t"] is None and kw["position"] == pytest.approx((0.0, 0.0), abs=1e-6)


def test_the_canvas_refuses_text_and_its_cross_goes_on_leave(window, qt_app) -> None:
    canvas = window.canvas
    assert not enter(canvas, centre(canvas), text())
    drop(canvas, centre(canvas), text(), qt_app)
    drop_anyway(canvas, centre(canvas), text(), qt_app)
    assert window.calls == [] and canvas.drop_point is None
    enter(canvas, centre(canvas), preset())
    assert hover(canvas, centre(canvas) + QPointF(10, 10), preset())
    assert canvas.drop_point == centre(canvas) + QPointF(10, 10)
    leave(canvas)
    assert canvas.drop_point is None and window.calls == []


# -- the layers list -------------------------------------------------------------------------


def test_a_preset_dropped_on_the_layers_list_is_placed_where_it_fits(window, qt_app) -> None:
    tree = window.layers.list
    pos = QPointF(20, 5)
    assert enter(tree.viewport(), pos, preset())
    assert tree.code_hover  # the list is outlined
    assert drop(tree.viewport(), pos, preset(), qt_app)
    assert not tree.code_hover
    [(hook, code, kw)] = window.calls
    assert hook == "place" and code["id"] == "orbit-id" and kw == {"t": None, "position": None}
    assert [layer.id for layer in window.document.project.layers] == ["dot", "box"]  # not reordered


def test_py_files_dropped_on_the_layers_list_are_imported(window, qt_app, tmp_path) -> None:
    assert drop(window.layers.list.viewport(), QPointF(20, 5), files(tmp_path), qt_app)
    [(hook, paths, kw)] = window.calls
    assert hook == "import" and [p.name for p in paths] == ["orbit.py"]
    assert kw == {"t": None, "position": None}


def test_the_layers_list_refuses_text_and_its_outline_goes_on_leave(window, qt_app) -> None:
    tree = window.layers.list
    assert not enter(tree.viewport(), QPointF(20, 5), text())
    drop_anyway(tree, QPointF(20, 5), text(), qt_app)
    assert window.calls == []
    assert [layer.id for layer in window.document.project.layers] == ["dot", "box"]
    enter(tree.viewport(), QPointF(20, 5), preset())
    leave(tree.viewport())
    assert not tree.code_hover and window.calls == []


def test_the_layers_list_still_reorders_by_dragging_its_rows(window, qt_app) -> None:
    tree = window.layers.list
    rows = []
    tree.rowDropped.connect(lambda layer_id, row: rows.append((layer_id, row)))
    bottom = tree.topLevelItem(tree.topLevelItemCount() - 1)
    top = tree.topLevelItem(0)
    bottom_id = bottom.data(0, Qt.ItemDataRole.UserRole)
    tree.setCurrentItem(bottom)
    pos = QPointF(tree.visualItemRect(top).center())
    # The tree's own drag carries its rows; it is handed to dropEvent directly, since a made-up
    # event has no source and Qt delivers an internal move only from the tree itself.
    event = QDropEvent(pos, ACTIONS, tree.mimeData([bottom]), BUTTONS, NO_KEYS, QEvent.Type.Drop)
    tree.dropEvent(event)
    qt_app.processEvents()
    assert rows == [(bottom_id, 0)]
    assert window.calls == []


def test_a_damaged_payload_is_refused(window) -> None:
    mime = QMimeData()
    mime.setData(code_drag.MIME, b"{not json")
    assert refused_by_timeline(window, mime)
    assert not enter(window.canvas, centre(window.canvas), mime)
    assert not enter(window.layers.list.viewport(), QPointF(20, 5), mime)
