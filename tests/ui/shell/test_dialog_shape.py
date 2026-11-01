"""The dialogs added since the first design share one shape (ADR 0084, P17.6): an icon header, one task, a
body no wider than 560 px, the primary action last, rows of the shared list with chips; each fits a 1024 x 640
window and paints in both themes; every one of the new commands is in the command palette."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QPushButton

from manim_studio.core.engine import extract_code
from manim_studio.core.exchange.bundle import Reference
from manim_studio.core.model import snapshots
from manim_studio.core.model.schema import (
    AudioClip,
    Canvas,
    Clip,
    Cue,
    Guide,
    Layer,
    Lifetime,
    Marker,
    Project,
    Spec,
)
from manim_studio.ui.exchange.bundle_dialog import BundleProblemDialog, ExportBundleDialog
from manim_studio.ui.exchange.script_dialog import ScriptDialog
from manim_studio.ui.exchange.snapshots_dialog import SnapshotsDialog
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.shell.beat_sheet_dialog import BeatSheetDialog
from manim_studio.ui.shell.explain_dialog import ExplainDialog
from manim_studio.ui.shell.extract_dialog import DIFFERENT, SAME, UNCHECKED, ExtractCodeDialog
from manim_studio.ui.shell.guides_dialog import GuidesDialog
from manim_studio.ui.shell.palette import collect_items
from manim_studio.ui.shell.plugins_dialog import PluginsDialog
from manim_studio.ui.shell.recipe_dialog import RecipeParametersDialog
from manim_studio.ui.shell.ripple_dialog import RippleDialog
from manim_studio.ui.style import theme
from manim_studio.ui.style.dialog_chrome import DialogFrame
from manim_studio.ui.style.icon_tile import IconTile
from manim_studio.ui.style.list_row import Dot, ListRow, RowList

pytestmark = pytest.mark.ui

MAX_BODY = 560


def project() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=8.0),
        layers=[
            Layer(
                id="a",
                name="Title",
                spec=Spec(type="Square"),
                clips=[Clip(id="in", kind="FadeIn", start=1.0, duration=2.0)],
            ),
            Layer(id="b", name="Disc", spec=Spec(type="Circle"), lifetime=Lifetime(in_=4.0, out=7.0)),
        ],
        markers=[Marker(id="m", t=2.0, name="Second"), Marker(id="n", t=5.0, name="Third")],
        subtitles=[Cue(id="c", start=2.5, end=3.5, text="And now the second beat.")],
        audio=[AudioClip(id="s", path="whoosh.wav", start=2.2, duration=1.0, name="whoosh")],
        guides=[
            Guide(id="g1", axis="x", position=0.0),
            Guide(id="g2", axis="y", position=1.5, name="horizon"),
        ],
    )


class Holder:
    def __init__(self) -> None:
        self.project = project()

    def apply(self, edit, text) -> None:
        self.project = edit.project


@pytest.fixture(autouse=True)
def back_to_ink(qt_app):
    yield
    theme.set_theme(qt_app, "ink")


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(project().model_dump_json(by_alias=True), encoding="utf-8")
    snapshots.save(path, project(), "rough cut")
    return path


def builders(tmp_path, saved):
    holder = Holder()
    current = project()
    refs = [
        Reference("audio", "s", "whoosh", "sounds/whoosh.wav"),
        Reference("ImageMobject", "l", "Logo", "img/logo.png"),
    ]
    code = extract_code.extract_as_code(current, ["a"]).code
    return {
        "beat": lambda: BeatSheetDialog(lambda: current, lambda t: None),
        "explain": lambda: ExplainDialog(lambda: current, lambda: 1.5, lambda t: None, lambda a, b: None),
        "ripple": lambda: RippleDialog(lambda: current, 2.0, holder.apply),
        "guides": lambda: GuidesDialog(lambda: holder.project, holder.apply),
        "snapshots": lambda: SnapshotsDialog(saved, lambda: current, lambda p, t: None),
        "plugins": lambda: PluginsDialog(),
        "recipe": lambda: RecipeParametersDialog("Pop pair", 1.5, 0.4, 2),
        "bundle": lambda: ExportBundleDialog(refs, {"img/logo.png"}, 1),
        "bundle-problem": lambda: BundleProblemDialog("Could not open the bundle", "it was changed"),
        "script": lambda: ScriptDialog(lambda: current, holder.apply),
        "extract": lambda: ExtractCodeDialog(code, 1),
    }


@pytest.mark.parametrize("name", ["ink", "paper"])
def test_every_dialog_has_the_shape_in_both_themes_at_1024_by_640(qt_app, tmp_path, saved, name) -> None:
    theme.set_theme(qt_app, name)
    for label, make in builders(tmp_path, saved).items():
        dialog = make()
        assert isinstance(dialog.frame, DialogFrame), label
        assert isinstance(dialog.frame.tile, IconTile) and dialog.frame.title_label.text(), label
        assert dialog.frame.header.objectName() == "dialogHeader", label
        dialog.show()
        for _ in range(5):
            qt_app.processEvents()
        assert dialog.width() <= MAX_BODY and dialog.height() <= 640, (label, dialog.size())
        assert not dialog.grab().isNull(), label  # every icon it names exists
        # one task: the footer's right-hand side ends with the primary action (or a lone plain Close)
        footer = dialog.frame.footer
        buttons = [footer.itemAt(i).widget() for i in range(footer.count()) if footer.itemAt(i).widget()]
        buttons = [b for b in buttons if isinstance(b, QPushButton)]
        primaries = [b for b in buttons if b.property("role") == "primary"]
        assert len(primaries) <= 1, label
        if primaries:
            assert buttons[-1] is primaries[0], label
        dialog.close()


def test_the_lists_are_rows_with_chips_not_bare_text(qt_app, tmp_path, saved) -> None:
    made = builders(tmp_path, saved)
    for label in ("beat", "explain", "guides", "snapshots", "bundle"):
        dialog = made[label]()
        dialog.show()
        qt_app.processEvents()
        assert isinstance(dialog.list, RowList), label
        assert dialog.list.count() > 0, label
        rows = [dialog.list.itemWidget(dialog.list.item(k)) for k in range(dialog.list.count())]
        assert any(isinstance(r, ListRow) for r in rows), label
        dialog.close()


def test_a_snapshot_row_has_a_picture_age_chips_and_restore(qt_app, tmp_path, saved) -> None:
    restored = []
    dialog = SnapshotsDialog(saved, project, lambda p, t: restored.append(t))
    dialog.show()
    for _ in range(10):
        qt_app.processEvents()
    row = dialog.list.itemWidget(dialog.list.item(0))
    assert row.title_label.text() == "rough cut" and row.mono_label.text() == "just now"
    assert [c.text() for c in row.chips] == ["2 layers", "8 s"]
    assert not dialog.pictures[0][0].pixmap().isNull()
    assert dialog.save_button.property("role") == "primary"
    row.actions.itemAt(0).widget().click()  # Restore, on the row
    assert restored == ["Restore snapshot rough cut"]
    dialog.close()


def test_a_beat_row_has_three_quiet_lines_with_their_dots(qt_app) -> None:
    dialog = BeatSheetDialog(project, lambda t: None)
    dialog.show()
    for _ in range(10):
        qt_app.processEvents()
    second = dialog.list.itemWidget(dialog.list.item(1))
    assert second.title_label.text() == "Second" and second.mono_label.text().startswith("0:02.0 - 0:05.0")
    assert [d.token for d in second.findChildren(Dot)] == ["content", "cue", "sound"]
    assert [line.text() for line in second.lines] == ["Disc", '"And now the second beat."', "whoosh"]
    dialog.close()


def test_an_explain_row_is_a_sentence_with_a_chip_and_a_go_to_button(qt_app) -> None:
    picked = []
    dialog = ExplainDialog(
        project, lambda: 1.5, lambda t: None, lambda layer, clip: picked.append((layer, clip))
    )
    dialog.show()
    qt_app.processEvents()
    clip_item = next(
        dialog.list.item(k) for k in range(dialog.list.count()) if "FadeIn" in dialog.list.item(k).text()
    )
    row = dialog.list.itemWidget(clip_item)
    assert row.title_label.text() == clip_item.text()
    assert [c.text() for c in row.chips] == ["FadeIn"]
    assert dialog.go_buttons and dialog.go_buttons[0].text() == "Go to"
    dialog.go_buttons[0].click()
    assert picked and picked[0][0] == "a"
    assert dialog.previous_button.text() == "Previous moment" and dialog.next_button.text() == "Next moment"
    dialog.close()


def test_the_extract_dialog_previews_the_code_and_never_claims_an_unchecked_match(qt_app) -> None:
    code = extract_code.extract_as_code(project(), ["a"]).code
    dialog = ExtractCodeDialog(code, 1)
    dialog.show()
    qt_app.processEvents()
    assert dialog.preview.toPlainText() == code and dialog.preview.isReadOnly()
    assert dialog.check_chip.text() == UNCHECKED and dialog.check_chip.property("tone") == "neutral"
    assert (
        dialog.lines_chip.text() == f"{len(code.splitlines())} lines"
        and dialog.layers_chip.text() == "1 layer"
    )
    assert dialog.extract_button.property("role") == "primary" and dialog.extract_button.isDefault()
    dialog.set_checked(True)
    assert dialog.check_chip.text() == SAME and dialog.check_chip.property("tone") == "ok"
    dialog.set_checked(False)
    assert dialog.check_chip.text() == DIFFERENT and dialog.check_chip.property("tone") == "warn"
    dialog.close()
    checked = ExtractCodeDialog(code, 2, verify=lambda: True)
    checked.show()
    for _ in range(5):
        qt_app.processEvents()
    assert checked.check_chip.text() == SAME and checked.layers_chip.text() == "2 layers"
    checked.close()


# -- the window: the preview comes first, the palette lists the commands -----------------------------------


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(project().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def test_declining_the_extract_preview_changes_nothing(window, qt_app) -> None:
    shown = []
    window.ask_extract = lambda code, layers: shown.append((code, layers)) or False
    before = window.project
    assert window.extract_selection_as_code(["a"]) is False
    assert shown and shown[0][1] == 1 and "class" in shown[0][0] and window.project == before
    assert window.document.undo_stack.count() == 0
    window.ask_extract = lambda code, layers: True
    assert window.extract_selection_as_code(["a"]) is True


def test_every_new_command_is_in_the_command_palette(window) -> None:
    titles = {item.title for item in collect_items(window) if item.kind == "command"}
    for expected in (
        "Beat Sheet",
        "Ripple Edit",
        "Explain This Moment",
        "Make Sequence from Selection",
        "Plugins",
        "Extract Selection as Code",
        "Snapshots",
        "Layout Guides",
        "Export Bundle",
        "Open Bundle",
        "Import Script",
        "Recipe Parameters",
    ):
        assert expected in titles, expected


def test_the_palette_opens_the_dialogs(window, qt_app, monkeypatch) -> None:
    opened = []
    for cls in (BeatSheetDialog, RippleDialog, ScriptDialog):
        monkeypatch.setattr(cls, "exec", lambda self, cls=cls: opened.append(type(self).__name__) or 0)
    by_title = {i.title: i for i in collect_items(window) if i.kind == "command"}
    by_title["Beat Sheet"].run()
    by_title["Ripple Edit"].run()
    assert opened == ["BeatSheetDialog", "RippleDialog"]
    by_title["Explain This Moment"].run()
    qt_app.processEvents()
    assert window.explain_dialog is not None and window.explain_dialog.isVisible()
    window.explain_dialog.close()
