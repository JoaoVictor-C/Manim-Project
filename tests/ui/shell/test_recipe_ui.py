"""Recipes in the editor (ADR 0080): Animate > Make Recipe from Sequence..., Apply Recipe on the selected
layers at the playhead and Recipe Parameters..., each one undo step; the parameters dialog."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import menu_action
from manim_studio.core.editing import library
from manim_studio.core.editing.sequences import Members, make_sequence
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.shell.recipe_dialog import RecipeParametersDialog
from manim_studio.ui.style import icons

pytestmark = pytest.mark.ui


def project() -> Project:
    plain = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=10.0),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square"),
                clips=[Clip(id="f", kind="FadeIn", start=1.0, duration=1.0)],
                tracks={"scale": [Keyframe(t=1.0, value=1.0), Keyframe(t=2.0, value=1.5)]},
            ),
            Layer(
                id="b", spec=Spec(type="Circle"), clips=[Clip(id="w", kind="Create", start=1.5, duration=1.0)]
            ),
            Layer(id="c", spec=Spec(type="Square")),
            Layer(id="d", spec=Spec(type="Circle")),
        ],
    )
    members = Members(clips=(("a", "f"), ("b", "w")), keys=(("a", "scale", 1.0), ("a", "scale", 2.0)))
    return make_sequence(plain, "Pair", members).project


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_LIBRARY", str(tmp_path / "library"))
    path = tmp_path / "scene.json"
    path.write_text(project().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    win.ask_recipe_name = lambda suggested: "Pop pair"
    yield win
    win.close()


def clips(window, layer_id: str) -> list[tuple[str, float, float]]:
    return [(c.kind, round(c.start, 6), round(c.duration, 6)) for c in window.project.layer(layer_id).clips]


def test_the_menu_has_the_recipe_actions(window) -> None:
    assert (
        menu_action(window.menuBar(), "Animate", "Make Recipe from Sequence...") is window.make_recipe_action
    )
    assert menu_action(window.menuBar(), "Animate", "Recipe Parameters...") is window.recipe_parameters_action
    assert not window.apply_recipe_menu.isEnabled()  # no recipe yet


def test_make_a_recipe_then_apply_it_to_other_layers_and_undo(window, tmp_path) -> None:
    window.selection.set("a", "f")
    window.make_recipe_action.trigger()
    assert (tmp_path / "library" / "recipe-Pop pair.json").is_file()
    assert [r.name for r in window.library.recipes] == ["Pop pair"]
    assert window.apply_recipe_menu.isEnabled()
    assert "Saved the recipe Pop pair" in window.statusBar().currentMessage()

    window.selection.set_layers(["c", "d"])
    window.seek(3.0)
    steps = window.document.undo_stack.count()
    menu_action(window.menuBar(), "Animate", "Apply Recipe", "Pop pair").trigger()
    assert clips(window, "c") == [("FadeIn", 3.0, 1.0)]
    assert clips(window, "d") == [("Create", 3.5, 1.0)]
    assert window.project.sequences[-1].recipe == "Pop pair"
    assert window.document.undo_stack.count() == steps + 1
    assert window.document.undo_stack.undoText() == "Apply recipe Pop pair"

    window.selection.set("d", window.project.layer("d").clips[0].id)
    asked = []
    window.ask_recipe_parameters = lambda name, length, stagger, layers: (
        asked.append((name, length, stagger, layers)) or (3.0, 1.0)
    )
    window.recipe_parameters_action.trigger()
    assert asked == [("Pop pair", 1.5, 0.5, 2)]
    assert clips(window, "c") == [("FadeIn", 3.0, 2.0)]
    assert clips(window, "d") == [("Create", 4.0, 2.0)]
    assert window.document.undo_stack.undoText() == "Recipe parameters"

    window.document.undo_stack.undo()
    window.document.undo_stack.undo()
    assert clips(window, "c") == [] and clips(window, "d") == []
    assert [s.name for s in window.project.sequences] == ["Pair"]


def test_refusals_go_to_the_status_bar(window) -> None:
    window.selection.set("a", "f")
    window.make_recipe_action.trigger()
    window.selection.set("c")
    steps = window.document.undo_stack.count()
    window.apply_recipe(window.library.recipes[0])
    assert "animates 2 layers: select 2" in window.statusBar().currentMessage()
    assert window.document.undo_stack.count() == steps
    window.selection.set("c")
    window.make_recipe_action.trigger()
    assert window.statusBar().currentMessage() == "Make recipe: select a clip or key of a sequence"
    window.recipe_parameters_action.trigger()
    assert "select a clip or key of a sequence" in window.statusBar().currentMessage()


def test_a_recipe_saved_before_is_listed_when_the_window_opens(qt_app, tmp_path, monkeypatch) -> None:
    folder = tmp_path / "library"
    monkeypatch.setenv("MANIM_STUDIO_LIBRARY", str(folder))
    plain = project()
    from manim_studio.core.editing.recipes import make_recipe

    library.save_item(make_recipe(plain, plain.sequences[0].id, "Saved one"), folder)
    win = MainWindow()
    try:
        assert [a.text() for a in win.apply_recipe_menu.actions()] == ["Saved one"]
    finally:
        win.close()


def test_the_parameters_dialog_shows_and_answers(qt_app) -> None:
    assert "animate" in icons.NAMES  # the dialog's header icon
    dialog = RecipeParametersDialog("Pop pair", 1.5, None, 2)
    dialog.show()
    qt_app.processEvents()
    assert dialog.keep.isChecked() and not dialog.stagger.isEnabled()
    assert dialog.answer() == (1.5, None)
    dialog.keep.setChecked(False)
    dialog.stagger.setValue(0.4)
    dialog.length.setValue(3.0)
    assert dialog.answer() == (3.0, 0.4)
    dialog.close()
