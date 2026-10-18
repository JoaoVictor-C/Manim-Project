"""A long scene must not make every edit quadratic (P7.2, B64/B66).

The views rebuilt per layer with ``Project.layer`` / ``children`` / ``morph_sources`` - each a scan
of every layer - so a 295-layer scene took 150 ms per timeline sync. These tests count the scans
instead of timing them: the work one rebuild asks of the project must not grow with the layers.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core import edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Canvas, Clip, Layer, PartKey, Project, Spec
from manim_studio.ui.build_service import BuildService
from manim_studio.ui.document import Document
from manim_studio.ui.layers_panel import LayersPanel
from manim_studio.ui.timeline.view import TimelineView
from qt_support import FakeWorker

pytestmark = pytest.mark.ui

SCANS = ("layer", "children", "descendants", "ancestors", "root_of", "morph_sources", "lifetime", "roots")


def long_project(slides: int) -> Project:
    """``slides`` groups of a formula with two parts, a square that morphs into a circle, and an
    axes with a graph: nine layers each, with clips, like a real explainer."""
    layers: list[Layer] = []
    for n in range(slides):
        t = 10.0 * n
        layers += [
            Layer(
                id=f"eq{n}",
                spec=Spec(type="MathTex", params={"text": "a+b=c"}),
                clips=[Clip(id=f"w{n}", kind="Write", start=t, duration=1.0)],
            ),
            Layer(id=f"pa{n}", parent_id=f"eq{n}", part=PartKey(tex="a", occurrence=0)),
            Layer(id=f"pb{n}", parent_id=f"eq{n}", part=PartKey(tex="b", occurrence=0)),
            Layer(
                id=f"sq{n}",
                spec=Spec(type="Square"),
                clips=[
                    Clip(id=f"f{n}", kind="FadeIn", start=t + 1, duration=1.0),
                    Clip(id=f"m{n}", kind="Transform", start=t + 3, duration=1.0, to_layer=f"ci{n}"),
                ],
            ),
            Layer(id=f"ci{n}", spec=Spec(type="Circle")),
            Layer(
                id=f"ax{n}",
                spec=Spec(type="Axes", params={}),
                clips=[Clip(id=f"c{n}", kind="Create", start=t + 5, duration=1.0)],
            ),
            Layer(id=f"gr{n}", parent_id=f"ax{n}", spec=Spec(type="Graph", params={"expression": "sin(x)"})),
            Layer(id=f"tx{n}", spec=Spec(type="Text", params={"text": f"slide {n}"})),
            Layer(id=f"dt{n}", spec=Spec(type="Dot")),
        ]
    return Project(canvas=Canvas(duration=10.0 * slides + 5, fps=30), layers=layers)


@pytest.fixture
def scans(monkeypatch):
    """Counts the Project methods that scan the layer list."""
    calls = {name: 0 for name in SCANS}

    def spy(name: str):
        original = getattr(Project, name)

        def counted(self, *args, **kwargs):
            calls[name] += 1
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Project, name, counted)

    for name in SCANS:
        spy(name)

    def reset() -> None:
        for name in calls:
            calls[name] = 0

    return calls, reset


def total(calls: dict[str, int]) -> int:
    return sum(calls.values())


def timeline_for(project: Project) -> TimelineView:
    view = TimelineView()
    view.resize(900, 500)
    view.set_document(Document(project))
    return view


def test_a_timeline_sync_asks_the_project_a_constant_number_of_times(qt_app, scans) -> None:
    calls, reset = scans
    small, big = timeline_for(long_project(5)), timeline_for(long_project(40))
    reset()
    small.sync()
    few = total(calls)
    reset()
    big.sync()
    many = total(calls)
    assert len(big.rows()) == len(big.project.layers)
    assert many == few, f"sync scanned the project {few} times at 45 layers but {many} at 360"
    assert many <= 5


def test_a_sync_with_every_row_expanded_stays_constant_in_scans(qt_app, scans) -> None:
    """Property sub-rows (P7.3) add rows per layer, never a scan per layer."""
    calls, reset = scans
    small, big = timeline_for(long_project(5)), timeline_for(long_project(40))
    for view in (small, big):
        for layer in view.project.layers:
            view.set_expanded(layer.id, True)
    counts = []
    for view in (small, big):  # a new snapshot: the rows and their property rows laid out again
        edit = edits.set_canvas(view.project, duration=view.project.canvas.duration + 1)
        reset()
        view.document.apply(edit, "Scene length")  # the timeline syncs on the new snapshot
        counts.append(total(calls))
    few, many = counts
    assert len(big.layout().subs[0]) == 4
    assert many == few and many <= 10, counts
    reset()
    big.show()
    big.header.grab()
    big.header.grab()
    assert total(calls) == 0
    big.close()


def test_the_timeline_rows_and_header_use_the_same_snapshot_index(qt_app, scans) -> None:
    """Asking for rows, a row's index or the layer at a height must not rescan the layers."""
    calls, reset = scans
    view = timeline_for(long_project(30))
    view.sync()
    reset()
    for _ in range(50):
        view.rows()
    view.row_of("tx3")
    assert total(calls) == 0


def test_painting_the_row_names_does_not_rescan_the_layers(qt_app, scans) -> None:
    calls, reset = scans
    view = timeline_for(long_project(30))
    view.show()
    view.header.grab()  # once, so Qt's own first-paint work is out of the count
    reset()
    view.header.grab()
    assert calls["ancestors"] == 0
    assert total(calls) == 0


def test_the_index_follows_the_snapshot_not_a_stale_one(qt_app) -> None:
    view = timeline_for(long_project(2))
    before = [x.id for x in view.rows()]
    doc = view.document
    doc.apply(edits.remove_layer(doc.project, "dt0"), "Delete layer")
    after = [x.id for x in view.rows()]
    assert "dt0" in before
    assert "dt0" not in after
    assert len(after) == len(before) - 1


def test_the_layers_panel_sync_asks_the_project_a_constant_number_of_times(qt_app, scans) -> None:
    calls, reset = scans

    def panel_for(project: Project) -> LayersPanel:
        doc = Document(project)
        panel = LayersPanel(BuildService(doc, FakeWorker()))
        panel.show()
        return panel

    small, big = panel_for(long_project(5)), panel_for(long_project(40))
    reset()
    small.sync()
    few = total(calls)
    reset()
    big.sync()
    many = total(calls)
    assert many == few, f"sync scanned the project {few} times at 45 layers but {many} at 360"
    assert many <= 10
    assert len(big.ids_front_to_back()) == len(big.project.layers)
    small.close()
    big.close()


def test_a_clip_edit_invalidates_with_a_constant_number_of_scans(scans) -> None:
    calls, reset = scans
    counts = []
    for slides in (5, 40):
        project = long_project(slides)
        evaluator = Evaluator(project)
        edited = project.model_copy(deep=True)
        edited.layers[3].clips[0].duration = 0.5
        reset()
        evaluator.invalidate(edited, {"sq0"}, "clip")
        counts.append(total(calls))
    assert counts[0] == counts[1], counts


def test_a_visible_timeline_rebuilds_into_a_new_scene_keeping_its_scroll(qt_app) -> None:
    """Clearing one scene again and again got slower each time (B68): a rebuild starts a new one."""
    view = timeline_for(long_project(10))
    view.show()
    qt_app.processEvents()
    view.verticalScrollBar().setValue(200)
    view.horizontalScrollBar().setValue(300)
    before = view.scene()
    view.sync()
    assert view.scene() is not before
    assert view.verticalScrollBar().value() == 200 and view.horizontalScrollBar().value() == 300
    assert len(view.clip_items()) == sum(len(layer.clips) for layer in view.project.layers)
    view.close()
