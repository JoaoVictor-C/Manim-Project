"""BuildService rules against a deterministic fake worker (ADR 0015, S2 plan rules 1-7)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from functools import partial

import pytest

pytest.importorskip("PySide6")

from pydantic import ValidationError

from manim_studio.core.editing import edits
from manim_studio.core.engine.warm import warm_key
from manim_studio.core.model.schema import Clip, Layer, Project, Spec
from manim_studio.ui.session.build_service import BuildService
from manim_studio.ui.session.document import Document
from qt_support import FakeWorker
from support import CANVAS

pytestmark = pytest.mark.ui

MATH = Spec(type="MathTex", params={"text": "x^2"})


def text(value: str, **params) -> Spec:
    return Spec(type="MathTex", params={"text": value, **params})


def set_spec(layer_id: str, spec: Spec):
    return partial(edits.update_layer, layer_id=layer_id, spec=spec)


@pytest.fixture
def setup(qt_app):
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="eq", spec=MATH, clips=[Clip(id="w", kind="Write", start=0, duration=0.5)]),
            Layer(id="sq", spec=Spec(type="Square")),
        ],
    )
    doc = Document(project)
    worker = FakeWorker()
    service = BuildService(doc, worker)
    service._warmed.add(warm_key(MATH))  # what the open project already shows is warm
    service.failures = []
    service.failed.connect(lambda text, message: service.failures.append((text, message)))
    return doc, worker, service


def test_edits_that_build_nothing_cold_apply_at_once(setup) -> None:
    doc, worker, service = setup
    assert service.submit(partial(edits.move_clip, layer_id="eq", clip_id="w", start=0.2), "Move")
    assert service.submit(set_spec("eq", text("x^2", font_size=80)), "Size")  # cache-neutral (B19)
    assert service.submit(set_spec("sq", Spec(type="Square", params={"side_length": 3})), "Side")
    assert worker.requests == {}
    assert doc.undo_stack.count() == 3


def test_new_text_waits_for_the_worker_then_commits(setup) -> None:
    doc, worker, service = setup
    assert not service.submit(set_spec("eq", text("y^3")), "Edit text", supersede=("eq", "text"), value="y^3")
    assert doc.project.layer("eq").spec == MATH  # nothing committed yet
    assert service.busy and service.pending_value(("eq", "text")) == (True, "y^3")
    worker.reply(text("y^3"))
    assert doc.project.layer("eq").spec == text("y^3")
    assert doc.undo_stack.count() == 1 and doc.undo_stack.undoText() == "Edit text"
    assert not service.busy and service.pending_value(("eq", "text")) == (False, None)


def test_an_edit_made_while_building_is_kept(setup) -> None:
    """Rule 4: the waiting operation is re-run on the current snapshot, not its own."""
    doc, worker, service = setup
    service.submit(set_spec("eq", text("y^3")), "Edit text")
    service.submit(partial(edits.move_clip, layer_id="eq", clip_id="w", start=0.3), "Move")
    worker.reply(text("y^3"))
    layer = doc.project.layer("eq")
    assert layer.spec == text("y^3") and layer.clips[0].start == 0.3
    assert [doc.undo_stack.text(i) for i in range(doc.undo_stack.count())] == ["Move", "Edit text"]


def test_undo_while_building_is_not_reverted(setup) -> None:
    doc, worker, service = setup
    service.submit(partial(edits.move_clip, layer_id="eq", clip_id="w", start=0.3), "Move")
    service.submit(set_spec("sq", Spec(type="Square", params={"side_length": 1})), "Side")
    service.submit(partial(edits.update_layer, layer_id="eq", name="Title"), "Rename")  # warm: at once
    service.submit(set_spec("eq", text("y^3")), "Edit text")
    doc.undo_stack.undo()  # undo the rename while the text builds
    worker.reply(text("y^3"))
    assert doc.project.layer("eq").name == ""
    assert doc.project.layer("eq").spec == text("y^3")


def test_latest_wins_for_the_same_field(setup) -> None:
    doc, worker, service = setup
    service.submit(set_spec("eq", text("a")), "Edit text", supersede=("eq", "text"), value="a")
    service.submit(set_spec("eq", text("b")), "Edit text", supersede=("eq", "text"), value="b")
    assert service.pending_value(("eq", "text")) == (True, "b")
    worker.reply(text("a"))
    assert doc.project.layer("eq").spec == MATH  # "a" was superseded
    worker.reply(text("b"))
    assert doc.project.layer("eq").spec == text("b")
    assert doc.undo_stack.count() == 1


def test_deleting_the_layer_drops_the_waiting_edit(setup) -> None:
    doc, worker, service = setup
    service.submit(set_spec("eq", text("y^3")), "Edit text")
    service.submit(partial(edits.remove_layer, layer_id="eq"), "Delete layer")
    worker.reply(text("y^3"))
    assert [layer.id for layer in doc.project.layers] == ["sq"]
    assert doc.undo_stack.count() == 1 and not service.busy


def test_one_request_per_cold_key_and_combined_changes_resend_once(setup) -> None:
    """C's duplicate-work case: font then text; only the combined key is built again."""
    doc, worker, service = setup
    doc.replace(Project(canvas=CANVAS, layers=[Layer(id="t", spec=Spec(type="Text", params={"text": "A"}))]))
    service._warmed.add(warm_key(Spec(type="Text", params={"text": "A"})))
    font = Spec(type="Text", params={"text": "A", "font": "Arial"})
    both = Spec(type="Text", params={"text": "B", "font": "Arial"})
    service.submit(set_spec("t", font), "Font", supersede=("t", "font"))
    service.submit(partial(edits.update_layer, layer_id="t", spec=both), "Text", supersede=("t", "text"))
    assert len(worker.requests) == 2
    worker.reply(font)  # the font op re-runs: its spec is warm, so it commits
    assert doc.project.layer("t").spec == font
    worker.reply(both)
    assert doc.project.layer("t").spec == both
    assert worker.requests == {}


def test_two_edits_waiting_for_the_same_key_share_one_request(setup) -> None:
    doc, worker, service = setup
    service.submit(partial(edits.add_layer, spec=text("z")), "Add equation")
    service.submit(set_spec("eq", text("z")), "Edit text")
    assert len(worker.requests) == 1
    worker.reply(text("z"))
    assert doc.project.layers[-1].spec == text("z") and doc.project.layer("eq").spec == text("z")


def test_adding_a_cold_text_layer_waits(setup) -> None:
    """C's REDUCTION-BREAK: structural edits are gated by the specs they build too."""
    doc, worker, service = setup
    assert not service.submit(partial(edits.add_layer, spec=text("\\int_0^1")), "Add equation")
    assert len(doc.project.layers) == 2
    worker.reply(text("\\int_0^1"))
    assert doc.project.layers[-1].id == "mathtex-1"


def test_a_failed_build_commits_nothing(setup) -> None:
    doc, worker, service = setup
    service.submit(
        set_spec("eq", text("\\notamacro")), "Edit text", supersede=("eq", "text"), value="\\notamacro"
    )
    worker.reply(text("\\notamacro"), ok=False, error="LaTeX error: Undefined control sequence.")
    assert doc.project.layer("eq").spec == MATH
    assert doc.undo_stack.count() == 0
    assert service.failures == [("Edit text", "LaTeX error: Undefined control sequence.")]
    assert service.pending_value(("eq", "text")) == (False, None)


def test_commits_wait_for_the_end_of_a_drag(setup) -> None:
    doc, worker, service = setup
    service.submit(set_spec("eq", text("y^3")), "Edit text")
    doc.begin_preview()
    doc.preview(edits.move_clip(doc.project, "eq", "w", 0.4))
    worker.reply(text("y^3"))
    assert doc.project.layer("eq").spec == MATH  # not during the drag
    doc.commit_preview("Move clip")
    assert doc.project.layer("eq").spec == text("y^3")
    assert [doc.undo_stack.text(i) for i in range(doc.undo_stack.count())] == ["Move clip", "Edit text"]


def test_invalid_operations_raise_at_submit(setup) -> None:
    _doc, _worker, service = setup
    with pytest.raises(ValidationError):
        service.submit(partial(edits.add_clip, layer_id="eq", kind="FadeIn", start=0.1, duration=0.2), "Add")
    with pytest.raises(edits.EditError):
        service.submit(partial(edits.remove_layer, layer_id="nope"), "Delete")
    assert not service.busy


def test_without_a_worker_everything_applies_synchronously(qt_app) -> None:
    doc = Document(Project(canvas=CANVAS, layers=[Layer(id="eq", spec=MATH)]))
    service = BuildService(doc, FakeWorker(available=False))
    assert service.submit(set_spec("eq", text("q")), "Edit text")
    assert doc.project.layer("eq").spec == text("q")


def test_prewarm_requests_cold_defaults_once(setup) -> None:
    _doc, worker, service = setup
    service.prewarm([MATH, text("a"), text("a"), Spec(type="Circle")])
    assert len(worker.requests) == 1
    worker.reply(text("a"))
    assert service.is_warm(text("a"))


def test_opening_another_project_drops_waiting_edits(setup) -> None:
    doc, worker, service = setup
    service.submit(set_spec("eq", text("y^3")), "Edit text")
    other = Project(canvas=CANVAS, layers=[Layer(id="eq", spec=MATH)])
    doc.replace(other)
    worker.reply(text("y^3"))
    assert doc.project is other and not service.busy
