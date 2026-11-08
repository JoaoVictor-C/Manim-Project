"""Properties dock (S2.5): edit the selected layer or clip.

The object section is generated from ``adapter.MOBJECT_PARAMS``; style, the
layer transform, lifetime and clip timing are fixed sections. A part layer
(ADR 0012) shows its key (TeX and occurrence) instead of an object section. Each finished
field edit is one operation submitted to the ``BuildService`` (ADR 0015) with
the field as its supersede key, so typing a new equation never freezes the UI
and the field keeps showing what was typed while it builds. Clip params stay
hidden (ADR 0007).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Hashable
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ... import plugins
from ...core.code import helpers, python_object
from ...core.editing import edits
from ...core.engine import adapter
from ...core.engine.adapter import Param
from ...core.engine.evaluator import camera_scale, camera_size, camera_transform, layer_transform
from ...core.model import glyph_colours, parts, scene_length, shape
from ...core.model.schema import (
    CAMERA_TYPES,
    CLIP_KIND_INFO,
    CODE_TYPES,
    DIRECTIONS,
    GLYPH_COLOURS,
    GRAPH_PARAMS,
    GROUP_TYPES,
    PART_PARENT_TYPES,
    PYTHON_TYPES,
    RASTER_TYPES,
    SHAPE_TYPES,
    TEXT_TYPES,
    Canvas,
    ClipParam,
    Easing,
    Layer,
    PartKey,
    Project,
    clip_params,
    keyable_props,
)
from ..canvas.gizmo import SHIFTS_ELSEWHERE
from ..session.build_service import BuildService
from ..style import theme
from ..style.fields import (
    BoolField,
    ChoiceField,
    CodeField,
    ColorField,
    Field,
    FloatField,
    IntField,
    KeyDiamond,
    KeyToggle,
    LabelledLineEdit,
    LongTextField,
    PathField,
    PointField,
    ScrubSpinBox,
    Section,
    SliderField,
    TextField,
    caption,
    pick_colour,
)
from ..timeline.curve_editor import ease_label, edit_curve
from .glyph_colours_dialog import ask_glyph_colours
from .inspector_tabs import CLIP, PROPERTIES, SCENE, InspectorTabs
from .kinds import KINDS, Kind, KindChip, kind_of

CUSTOM_CURVE = "custom-curve"  # the "Custom curve..." entry of an easing list
STYLE_KEYS = ("fill", "fill_opacity", "stroke", "stroke_width")
BASE_TRACK = {"position": "position", "scale": "scale", "rotation": "rotation", "opacity": "opacity"}


# -- operations: re-runnable on whatever the current snapshot is (ADR 0015) ---------


def set_param(project: Project, layer_id: str, name: str, value: Any) -> edits.Edit:
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    spec = project.layer(layer_id).spec
    params = {k: v for k, v in spec.params.items() if k != name}
    if value is not None:
        params[name] = list(value) if isinstance(value, tuple) else value
    return edits.update_layer(project, layer_id, spec=spec.model_copy(update={"params": params}))


def set_python_value(project: Project, layer_id: str, name: str, value: Any) -> edits.Edit:
    """Change one parameter of a Python object (ADR 0051); None goes back to its default."""
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    spec = project.layer(layer_id).spec
    values = {k: v for k, v in (spec.params.get("values") or {}).items() if k != name}
    if value is not None:
        values[name] = value
    params = {k: v for k, v in spec.params.items() if k != "values"}
    if values:
        params["values"] = values
    return edits.update_layer(project, layer_id, spec=spec.model_copy(update={"params": params}))


def set_python_code(project: Project, layer_id: str, code: str) -> edits.Edit:
    """Give a Python object new code (ADR 0051), keeping the values of the parameters that are
    still declared and still fit."""
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    spec = project.layer(layer_id).spec
    values = python_object.kept_values(code, spec.params.get("values") or {})
    params = {"code": code, **({"values": values} if values else {})}
    return edits.update_layer(project, layer_id, spec=spec.model_copy(update={"params": params}))


def set_style(project: Project, layer_id: str, key: str, value: Any) -> edits.Edit:
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    spec = project.layer(layer_id).spec
    style = {k: v for k, v in spec.style.items() if k != key}
    if value is not None:
        style[key] = value
    return edits.update_layer(project, layer_id, spec=spec.model_copy(update={"style": style}))


def set_base(project: Project, layer_id: str, name: str, value: Any) -> edits.Edit:
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    base = project.layer(layer_id).base.model_dump()
    base[name] = value
    return edits.update_layer(project, layer_id, base=base)


def set_transform(
    project: Project,
    layer_id: str,
    name: str,
    value: Any,
    at: Callable[[], float],
    auto_key: Callable[[], bool],
) -> edits.Edit:
    """A transform field: base, key at the playhead, or auto-key (ADR 0016, ADR 0018)."""
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    value = tuple(value) if isinstance(value, list) else value
    return edits.set_property(project, layer_id, name, value, at(), auto_key=auto_key())


def set_camera_size(
    project: Project,
    layer_id: str,
    value: Any,
    at: Callable[[], float],
    auto_key: Callable[[], bool],
    name: str = "scale",
) -> edits.Edit:
    """The camera's Size field (ADR 0083): half the height it sees, stored as its scale (the stored truth)."""
    if value is None or float(value) <= 0:
        raise edits.EditError("the size must be above 0")
    scale = camera_scale(float(value), project.canvas.frame_height)
    return set_transform(project, layer_id, "scale", scale, at, auto_key)


def set_camera_param(project: Project, layer_id: str, name: str, value: Any) -> edits.Edit:
    """A camera setting (ADR 0083): background, follow, follow offset; the default is not written."""
    if value in (None, "") or (name == "follow_offset" and tuple(value) == (0.0, 0.0)):
        value = None
    if name == "follow" and value is None:  # following nothing: the offset goes too
        edit = set_param(project, layer_id, "follow_offset", None)
        return set_param(edit.project, layer_id, "follow", None)
    return set_param(project, layer_id, name, value)


def set_anchor(project: Project, layer_id: str, value: Any, at: Callable[[], float]) -> edits.Edit:
    """The anchor point field: moves the pivot, keeping the drawing at the playhead (ADR 0021)."""
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    return edits.set_anchor(project, layer_id, tuple(value), at())


def set_clip_param(project: Project, layer_id: str, value: Any, clip_id: str, name: str) -> edits.Edit:
    """One registered clip param; None goes back to its default (ADR 0022)."""
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    clip = next((c for c in project.layer(layer_id).clips if c.id == clip_id), None)
    if clip is None:
        raise edits.EditError(f"layer {layer_id!r} has no clip {clip_id!r}")
    params = {k: v for k, v in clip.params.items() if k != name}
    if value is not None:
        params[name] = value
    return edits.update_clip(project, layer_id, clip_id, params=params)


def set_animated(
    project: Project, layer_id: str, prop: str, value: bool, at: Callable[[], float]
) -> edits.Edit:
    """The stopwatch (ADR 0016): on = one key at the playhead holding the current value
    (nothing moves); off = drop the keys, keeping the value at the playhead."""
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    layer = project.layer(layer_id)
    if value:
        return edits.set_key(project, layer_id, prop, at(), getattr(layer.base, prop))
    return edits.clear_track(project, layer_id, prop, at())


def _keyed_props(layer: Layer, t: float, fps: int) -> tuple[str, ...]:
    return tuple(prop for prop, track in layer.tracks.items() if any(abs(k.t - t) < 0.5 / fps for k in track))


def _key_at(layer: Layer, prop: str, t: float, fps: int):
    return next(k for k in layer.tracks[prop] if abs(k.t - t) < 0.5 / fps)


def _is_last_key(layer: Layer, prop: str, t: float, fps: int) -> bool:
    return all(k.t < t + 0.5 / fps for k in layer.tracks[prop])


def _set_key_value(project: Project, layer_id: str, value: Any, prop: str, t: float) -> edits.Edit:
    value = tuple(value) if isinstance(value, list) else value
    return edits.set_key(project, layer_id, prop, t, value)


def _set_size_key(project: Project, layer_id: str, value: Any, t: float) -> edits.Edit:
    """A camera's scale key, given as a size (ADR 0083)."""
    if value is None or float(value) <= 0:
        raise edits.EditError("the size must be above 0")
    return edits.set_key(
        project, layer_id, "scale", t, camera_scale(float(value), project.canvas.frame_height)
    )


def _set_key_ease(project: Project, layer_id: str, value: Easing, prop: str, t: float) -> edits.Edit:
    return edits.set_key_ease(project, layer_id, t, value, props=[prop])


def _key_value_field(prop: str, commit: Callable[[Any], None]) -> Field:
    if prop == "position":
        return PointField(commit)
    if prop in ("scale", "scale_x", "scale_y"):
        return FloatField(commit, 0.01, 100, 0.05, 3)
    if prop == "rotation":
        return FloatField(commit, -3600, 3600, 1, 1, suffix=" deg")
    return FloatField(commit, 0, 1, 0.05, 2)


def set_lifetime(project: Project, layer_id: str, key: str, value: float | None) -> edits.Edit:
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    lifetime = project.layer(layer_id).lifetime.model_dump(by_alias=True)
    lifetime[key] = value
    return edits.update_layer(project, layer_id, lifetime=lifetime)


def set_part_key(project: Project, layer_id: str, name: str, value: Any) -> edits.Edit:
    """Change a part's TeX or occurrence (1-based in the panel); refused if it would not resolve."""
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    layer = project.layer(layer_id)
    key = layer.part.model_dump()
    key[name] = int(value) - 1 if name == "occurrence" else str(value)
    edit = edits.update_layer(project, layer_id, part=PartKey(**key))
    orphans = parts.resolve(edit.project, edit.project.root_of(layer_id).id).orphans
    if layer_id in orphans:
        raise edits.EditError(orphans[layer_id])
    return edit


def set_part_colour(project: Project, layer_id: str, key: str, value: str | None) -> edits.Edit:
    """A part's fill or stroke colour (ADR 0049); None goes back to its object's."""
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    return edits.set_part_style(project, layer_id, **{key: value})


def set_piece_colour(project: Project, layer_id: str, value: str | None, piece: str) -> edits.Edit:
    """The colour of a piece of a Text (Manim's ``t2c``, ADR 0049); None stops colouring it."""
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    return edits.set_text_colour(project, layer_id, piece, value)


def _has(project: Project, layer_id: str) -> bool:
    return any(layer.id == layer_id for layer in project.layers)


# -- the panel ----------------------------------------------------------------------


class TitleBlock(QWidget):
    """The head of Properties (Lumen): the shown thing's kind chip, its name, and a line about it.

    ``setText`` takes the same rich text the panel always wrote ("<b>name</b> - what it is", maybe a
    second line in italics) and ``text`` gives it back, so callers and tests read it as before; the name
    is shown large and the rest under it, muted."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self.chip = KindChip(32)
        self.name = QLabel()
        self.name.setFont(theme.font("heading"))
        self.name.setWordWrap(True)
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.detail = QLabel()
        self.detail.setFont(theme.font("caption"))
        self.detail.setProperty("role", "muted")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(1)
        words.addWidget(self.name)
        words.addWidget(self.detail)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 14, 14, 12)
        row.setSpacing(10)
        row.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(words, 1)

    def setText(self, text: str) -> None:
        self._text = text
        found = re.match(r"\s*<b>(.*?)</b>(.*)", text, re.DOTALL)
        name, rest = (found.group(1), found.group(2)) if found else (text, "")
        rest = re.sub(r"^\s*(-\s*|<br>)", "", rest.strip())
        self.name.setText(name)
        self.detail.setText(rest)
        self.detail.setVisible(bool(rest))

    def text(self) -> str:
        return self._text

    def set_kind(self, kind: Kind) -> None:
        self.chip.set_kind(kind)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(0, self.height() - 1, self.width(), 1, theme.qcolor(theme.THEME.line))
        painter.end()


class PropertiesPanel(QWidget):
    message = Signal(str)
    keyMoved = Signal(str, float)  # the shown keys were retimed: layer id, new time

    def __init__(self, builds: BuildService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.builds = builds
        self.document = builds.document
        self.layer_id: str | None = None
        self.clip_id: str | None = None
        self.key_time: float | None = None
        self.audio_id: str | None = None  # a sound is shown (ADR 0034)
        self.subtitle_id: str | None = None  # a subtitle is shown (ADR 0035)
        self.others_selected = 0  # other selected objects besides the one shown (ADR 0043)
        self.marker_id: str | None = None  # a marker is shown (ADR 0037)
        self.scene_shown = False  # nothing selected: the scene's settings (P7.1)
        self._scene_tips: dict[str, str] = {}  # their fields' tooltips
        self.code_ends: Callable[[], list[float]] = lambda: []  # rendered code animations, set by the window
        self.fit_button: QPushButton | None = None
        self.fields: dict[str, Field] = {}
        self._tips: dict[str, str] = {}  # re-applied after each refresh: set_value clears a field's tooltip
        self._getters: dict[str, Callable[[Layer], Any]] = {}
        self._keys: dict[str, Hashable] = {}
        self._generation = 0  # bumped on every rebuild: old widgets can no longer commit
        self._shown_props: tuple[str, ...] = ()  # keys view: the properties keyed at key_time
        self._shown_kind: str | None = None  # clip view: the kind whose params are shown (ADR 0022)
        self._shown_pieces: tuple[str, ...] | None = None  # a Text's coloured pieces shown (ADR 0049)
        self.part_tex: QLineEdit | None = None  # "Colour a part" / "Colour a piece" (ADR 0049)
        self.part_occurrence: QSpinBox | None = None
        self.part_colour_button: QPushButton | None = None
        # Asks for a colour (current colour or None -> "#rrggbb" or None); tests replace it.
        self.ask_colour: Callable[[str | None], str | None] = lambda current: pick_colour(self, current)
        self.playhead: Callable[[], float] = lambda: 0.0  # set by the window (stopwatch keys)
        self.auto_key: Callable[[], bool] = lambda: False  # Edit > Auto-key (ADR 0018)
        # Code layers (ADR 0019), set by the window: status text, retry, and trusting applied code.
        self.code_status: Callable[[str], str | None] = lambda layer_id: None
        self.code_failed: Callable[[str], bool] = lambda layer_id: False
        self.retry_code: Callable[[str], None] = lambda layer_id: None
        self.trust_code: Callable[[str], None] = lambda code: None
        self.code_label: QLabel | None = None
        self.retry_button: QPushButton | None = None
        # Python objects (ADR 0051): open the code page on one (set by the window).
        self.edit_code: Callable[[str], None] = lambda layer_id: None
        self.python_label: QLabel | None = None
        self._shown_params: tuple[Param, ...] | None = None  # a Python object's parameters shown
        # Freeze to shape (ADR 0052): set by the window, which knows what is drawn.
        self.freeze: Callable[[str], None] = lambda layer_id: None
        self.freeze_button: QPushButton | None = None
        # Colour characters (ADR 0055): (layer id, current colours) -> the new list, or None.
        self.ask_glyph_colours: Callable[[str, list | None], list | None] = lambda layer_id, current: (
            ask_glyph_colours(self, self.project, layer_id)
        )
        self.characters_button: QPushButton | None = None
        self._shown_type: str | None = None  # the object type whose sections are shown
        # "Custom curve...": shows the curve editor; tests replace it (P2b)
        self.curve_dialog: Callable[[Easing | None], Easing | None] = lambda ease: edit_curve(self, ease)

        self.sections: dict[str, Section] = {}  # the sections shown, by title
        self._section_keys: tuple[QToolButton, list[KeyToggle]] | None = None  # Transform's diamond
        self._collapsed: set[str] = set()  # titles of the sections the user closed (kept across selections)
        self.title = TitleBlock()
        self.tabs = InspectorTabs()  # Properties | Clip | Scene, in the card's header (ADR 0084)
        self.tabs.tabChosen.connect(self._on_tab)
        self._return_to: str | None = None  # the object the Scene tab was opened from
        self.body = QWidget()
        self.body.setObjectName("propertiesBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(300)
        scroll.setWidget(self.body)
        self.scroll = scroll
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title)
        layout.addWidget(scroll, 1)

        self.document.changed.connect(lambda *_: self.refresh())
        self.document.reset.connect(lambda _project: self.show_nothing())
        builds.pendingChanged.connect(self.refresh)
        self.show_nothing()

    @property
    def project(self) -> Project:
        return self.document.project

    # -- selection ----------------------------------------------------------------

    def show_nothing(self) -> None:
        """Nothing selected: the scene's settings (P7.1)."""
        self.layer_id = self.clip_id = self.key_time = self.audio_id = self.subtitle_id = None
        self.marker_id = None
        self._rebuild()
        self.scene_shown = True
        generation = self._generation

        def commit(name: str, text: str) -> Callable[[Any], None]:
            def apply(value: Any) -> None:
                if generation != self._generation:
                    return
                self.set_scene(name, value, text)

            return apply

        rows = [
            (
                "Length",
                "canvas.duration",
                FloatField(commit("duration", "Scene length"), 0.04, 36000.0, 1.0, 2, suffix=" s"),
            ),
            (
                "",
                "canvas.grow_with_content",
                BoolField(commit("grow_with_content", "Grow with content"), "Grow with content"),
            ),
            (
                "Size",
                [
                    ("canvas.width_px", IntField(commit("width_px", "Scene size"), 16, 7680), "W"),
                    ("canvas.height_px", IntField(commit("height_px", "Scene size"), 16, 4320), "H"),
                ],
            ),
            ("Frame rate", "canvas.fps", IntField(commit("fps", "Frame rate"), 1, 240)),
            ("Background", "canvas.background", ColorField(commit("background", "Background"))),
            (
                "New morphs",
                "project.morph_matching",
                ChoiceField(
                    commit("morph_matching", "New morphs"),
                    [("Smart (better look)", "smart"), ("Classic (readable Python export)", "classic")],
                ),
            ),
        ]
        self._section("Scene", rows)
        self._scene_tips = {  # re-applied after each refresh: set_value clears a field's tooltip
            "canvas.duration": "How long the video is. Shorter than its content also stops it growing.",
            "canvas.grow_with_content": (
                "The scene gets longer by itself when something is placed past its end"
            ),
            "project.morph_matching": (
                "How Transform clips added from now on pair their pieces. Smart: fewer twisted or "
                "tangled in-between frames, but a project that uses it exports its Python scene as "
                "an exact replay. Classic: Manim's own Transform, so the export stays readable. "
                "Existing clips keep their own choice (Matching, in their Properties)."
            ),
        }
        self.fit_button = QPushButton("Fit Length to Content")
        self.fit_button.setToolTip("End the scene where its last clip, key, sound or subtitle ends")
        self.fit_button.clicked.connect(self.fit_length)
        self._append(self.fit_button)
        self._camera_section(generation)
        self.body_layout.addStretch(1)
        self.title.set_kind(KINDS["scene"])
        self.title.setText("<b>Scene</b> - select a layer, a clip or a keyframe to edit it.")
        self._refresh_scene(True)

    def _camera_section(self, generation: int) -> None:
        """The camera (ADR 0048): the flat 2D view by default; any other angle shows the flat scene
        tilted, turned or rolled, and the canvas has no handles until it is reset."""

        def commit(name: str) -> Callable[[Any], None]:
            def apply(value: Any) -> None:
                if generation == self._generation and value is not None:
                    self.set_camera(name, value)

            return apply

        def angle(name: str, low: float, high: float) -> FloatField:
            return FloatField(commit(name), low, high, 5.0, 1, suffix=" deg")

        self._section(
            "Camera",
            [
                ("Tilt (phi)", "camera.phi", angle("phi", 0.0, 180.0)),
                ("Turn (theta)", "camera.theta", angle("theta", -180.0, 180.0)),
                ("Roll (gamma)", "camera.gamma", angle("gamma", -180.0, 180.0)),
            ],
        )
        tips = {
            "phi": "Tilt off straight-on: 0 is the flat 2D view, 90 looks along the scene's plane",
            "theta": "Turn about the scene's centre: -90 is the flat 2D view",
            "gamma": "Roll about the line of sight: 0 is the flat 2D view",
        }
        for name, tip in tips.items():
            self._scene_tips[f"camera.{name}"] = (
                f"{tip}. Any other camera than the flat view hides the canvas handles."
            )
        self.camera_reset = QPushButton("Reset Camera")
        self.camera_reset.setToolTip("Back to the flat 2D view (handles and clicking objects return)")
        self.camera_reset.clicked.connect(self.reset_camera)
        self._append(self.camera_reset)

    def set_camera(self, name: str, value: float) -> None:
        """Change one of the camera's angles (one undo step)."""
        try:
            self.document.apply(edits.set_camera(self.project, **{name: value}), "Camera")
        except edits.EditError as exc:
            self.message.emit(f"Camera: {exc}")
        self._refresh_scene(True)

    def reset_camera(self) -> None:
        self.document.apply(edits.reset_camera(self.project), "Reset Camera")
        self._refresh_scene(True)

    def set_scene(self, name: str, value: Any, text: str) -> None:
        """Change one of the scene's settings (one undo step)."""
        project = self.project
        try:
            if name == "morph_matching":
                edit = edits.set_morph_matching(project, value)
            elif name == "duration":
                new = scene_length.set_length(project, value)
                if project.canvas.grow_with_content and not new.canvas.grow_with_content:
                    self.message.emit("The scene is shorter than its content: it no longer grows by itself.")
                edit = edits.Edit(new, "timing", frozenset())
            else:
                edit = edits.set_canvas(
                    project,
                    **{
                        name: Canvas.model_fields["background"].default
                        if value is None and name == "background"
                        else value
                    },
                )
            self.document.apply(edit, text)
        except (edits.EditError, ValidationError) as exc:
            self.message.emit(f"{text}: {_first_error(exc)}")
        self._refresh_scene(True)

    def fit_length(self) -> None:
        """End the scene where its content ends (one undo step)."""
        fitted = scene_length.fit_to_content(self.project, self.code_ends())
        if fitted is self.project:
            self.message.emit("Nothing in the scene is timed yet: its length stays as it is.")
            return
        self.document.apply(edits.Edit(fitted, "timing", frozenset()), "Fit Length to Content")

    def _refresh_scene(self, force: bool) -> None:
        owners = {"canvas": self.project.canvas, "camera": self.project.camera, "project": self.project}
        for path, field in self.fields.items():
            if not field.has_focus() or force:
                owner, name = path.split(".", 1)
                field.set_value(getattr(owners[owner], name))
            if path in self._scene_tips:
                field.widget.setToolTip(self._scene_tips[path])

    def show_layer(self, layer_id: str) -> None:
        if not layer_id or not _has(self.project, layer_id):
            self.show_nothing()
            return
        self.layer_id, self.clip_id, self.key_time, self.audio_id = layer_id, None, None, None
        self.subtitle_id = self.marker_id = None
        self._rebuild()
        layer = self.project.layer(layer_id)
        self._section(
            "Layer", [("Name", "name", TextField(self._layer_op("name", self._set_name), layer.label))]
        )
        self._shown_pieces = None
        if layer.is_part:
            self._part_section()
            self._part_style_section()
        elif layer.is_camera:  # Unity's 2D camera: Transform and Camera sections (ADR 0083)
            self._shown_type = layer.spec.type
        else:
            self._shown_type = layer.spec.type
            self._object_section(layer)
            if layer.spec.type in TEXT_TYPES:
                self._colour_characters_row(layer.id)
            self._freeze_row(layer)
            if (
                layer.spec.type not in RASTER_TYPES | CODE_TYPES | GROUP_TYPES | CAMERA_TYPES
            ):  # no style on images, code, groups, the camera
                self._style_section()
            if layer.spec.type in PART_PARENT_TYPES:
                self._colour_part_section(layer.id)
            elif layer.spec.type == "Text":
                self._pieces_section(layer)
        self._transform_section(layer)
        if layer.is_camera and not layer.is_part:
            self._camera_layer_section()
        if not layer.is_camera:  # the camera is the view at every time
            self._lifetime_section()
        self.body_layout.addStretch(1)
        self.refresh()

    def show_clip(self, layer_id: str, clip_id: str) -> None:
        if not _has(self.project, layer_id) or self._clip(layer_id, clip_id) is None:
            self.show_nothing()
            return
        self.layer_id, self.clip_id, self.key_time, self.audio_id = layer_id, clip_id, None, None
        self.subtitle_id = self.marker_id = None
        self._rebuild()
        self._clip_section(self.project.layer(layer_id), self._clip(layer_id, clip_id))
        self.body_layout.addStretch(1)
        self.refresh()

    def show_key(self, layer_id: str, t: float) -> None:
        """The keys of a layer at one time (P2b): their time, values and easing."""
        if not _has(self.project, layer_id):
            self.show_nothing()
            return
        if not _keyed_props(self.project.layer(layer_id), t, self.project.canvas.fps):
            self.show_layer(layer_id)
            return
        self.layer_id, self.clip_id, self.key_time, self.audio_id = layer_id, None, t, None
        self.subtitle_id = self.marker_id = None
        self._rebuild()
        self._key_section(self.project.layer(layer_id), t)
        self.body_layout.addStretch(1)
        self.refresh()

    def show_audio(self, audio_id: str) -> None:
        """A sound (ADR 0034): its name, place, trim, gain and fades."""
        clip = next((c for c in self.project.audio if c.id == audio_id), None)
        if clip is None:
            self.show_nothing()
            return
        self.layer_id = self.clip_id = self.key_time = self.subtitle_id = self.marker_id = None
        self.audio_id = audio_id
        self._rebuild()
        generation = self._generation

        def commit(name: str, text: str) -> Callable[[Any], None]:
            def apply(value: Any) -> None:
                if generation != self._generation:
                    return
                if name == "name":
                    value = value.strip()
                try:
                    self.document.apply(edits.update_audio(self.project, audio_id, **{name: value}), text)
                except (edits.EditError, ValidationError) as exc:
                    self.message.emit(f"{text}: {_first_error(exc)}")
                    self.refresh(force=True)

            return apply

        seconds = {"minimum": 0.0, "maximum": 36000.0, "step": 0.1, "suffix": " s"}
        rows = [
            ("Name", "audio.name", TextField(commit("name", "Rename sound"), clip.id)),
            ("Start", "audio.start", FloatField(commit("start", "Move sound"), **seconds)),
            ("Trim start", "audio.offset", FloatField(commit("offset", "Trim sound"), **seconds)),
            (
                "Duration",
                "audio.duration",
                FloatField(commit("duration", "Trim sound"), **{**seconds, "minimum": 0.001}),
            ),
            ("Gain", "audio.gain", FloatField(commit("gain", "Change gain"), -60.0, 24.0, 0.5, suffix=" dB")),
            ("Fade in", "audio.fade_in", FloatField(commit("fade_in", "Change fade"), **seconds)),
            ("Fade out", "audio.fade_out", FloatField(commit("fade_out", "Change fade"), **seconds)),
        ]
        self._section("Sound", rows)
        self.body_layout.addStretch(1)
        self.refresh()

    def show_subtitle(self, cue_id: str) -> None:
        """A subtitle (ADR 0035): its times and text, and the style every subtitle shares."""
        if not any(c.id == cue_id for c in self.project.subtitles):
            self.show_nothing()
            return
        self.layer_id = self.clip_id = self.key_time = self.audio_id = self.marker_id = None
        self.subtitle_id = cue_id
        self._rebuild()
        generation = self._generation

        def commit(op: Callable[..., edits.Edit], name: str, text: str) -> Callable[[Any], None]:
            def apply(value: Any) -> None:
                if generation != self._generation:
                    return
                try:
                    self.document.apply(op(self.project, **{name: value}), text)
                except (edits.EditError, ValidationError) as exc:
                    self.message.emit(f"{text}: {_first_error(exc)}")
                    self.refresh(force=True)

            return apply

        def cue_op(project: Project, **fields: Any) -> edits.Edit:
            return edits.update_cue(project, cue_id, **fields)

        seconds = {"minimum": 0.0, "maximum": 36000.0, "step": 0.1, "suffix": " s"}
        self._section(
            "Subtitle",
            [
                ("Start", "cue.start", FloatField(commit(cue_op, "start", "Move subtitle"), **seconds)),
                ("End", "cue.end", FloatField(commit(cue_op, "end", "Move subtitle"), **seconds)),
                ("Text", "cue.text", LongTextField(commit(cue_op, "text", "Edit subtitle"))),
            ],
        )
        style = edits.set_subtitle_style
        self._section(
            "Subtitle style (all subtitles)",
            [
                (
                    "Size",
                    "subtitle_style.font_size",
                    FloatField(commit(style, "font_size", "Subtitle size"), 6, 120, 1),
                ),
                (
                    "Height",
                    "subtitle_style.y",
                    FloatField(commit(style, "y", "Subtitle height"), -10, 10, 0.1),
                ),
                ("Colour", "subtitle_style.colour", ColorField(commit(style, "colour", "Subtitle colour"))),
                (
                    "Band",
                    "subtitle_style.band",
                    BoolField(commit(style, "band", "Subtitle band"), "Box behind the text"),
                ),
                (
                    "Band colour",
                    "subtitle_style.band_colour",
                    ColorField(commit(style, "band_colour", "Band colour")),
                ),
                (
                    "Band opacity",
                    "subtitle_style.band_opacity",
                    FloatField(commit(style, "band_opacity", "Band opacity"), 0, 1, 0.05),
                ),
                (
                    "Fade",
                    "subtitle_style.fade",
                    FloatField(commit(style, "fade", "Subtitle fade"), **seconds),
                ),
                (
                    "Width",
                    "subtitle_style.max_width",
                    FloatField(commit(style, "max_width", "Subtitle width"), 1, 30, 0.5),
                ),
                (
                    "Burn in",
                    "subtitle_style.burn_in",
                    BoolField(commit(style, "burn_in", "Burn in subtitles"), "Draw them into the video"),
                ),
            ],
        )
        self.body_layout.addStretch(1)
        self.refresh()

    def show_marker(self, marker_id: str) -> None:
        """A marker (ADR 0037): its name, time and colour."""
        if not any(m.id == marker_id for m in self.project.markers):
            self.show_nothing()
            return
        self.layer_id = self.clip_id = self.key_time = self.audio_id = self.subtitle_id = None
        self.marker_id = marker_id
        self._rebuild()
        generation = self._generation

        def commit(name: str, text: str) -> Callable[[Any], None]:
            def apply(value: Any) -> None:
                if generation != self._generation:
                    return
                changes = {name: value}
                if name == "name":
                    changes = {name: value.strip()}
                elif name == "slide":  # off also clears the loop, which only a stop has
                    changes = {"slide": "stop"} if value else {"slide": None, "loop": None}
                elif name == "loop":  # 0 or empty: hold still
                    changes = {"loop": value if value and value > 0 else None}
                try:
                    self.document.apply(edits.update_marker(self.project, marker_id, **changes), text)
                except (edits.EditError, ValidationError) as exc:
                    self.message.emit(f"{text}: {_first_error(exc)}")
                    self.refresh(force=True)

            return apply

        seconds = {"minimum": 0.0, "maximum": 36000.0, "step": 1 / self.project.canvas.fps, "suffix": " s"}
        def slide_stop(value: Any) -> None:
            commit("slide", "Make slide stop" if value else "Remove slide stop")(value)

        rows = [
            ("Name", "marker.name", TextField(commit("name", "Rename marker"), marker_id)),
            ("Time", "marker.t", FloatField(commit("t", "Move marker"), **seconds, decimals=3)),
            ("Colour", "marker.colour", ColorField(commit("colour", "Marker colour"))),
            ("Slide stop", "marker.slide", BoolField(slide_stop, "Wait here when presenting")),
            (
                "Loop",
                "marker.loop",
                FloatField(
                    commit("loop", "Slide loop"), **{**seconds, "minimum": 0.0}, decimals=2, none_text="Hold still"
                ),
            ),
        ]
        self._section("Marker", rows)
        self.body_layout.addStretch(1)
        self.refresh()

    def _refresh_marker(self, force: bool) -> None:
        marker = next((m for m in self.project.markers if m.id == self.marker_id), None)
        if marker is None:
            self.show_nothing()
            return
        self.title.set_kind(KINDS["marker"])
        what = "slide stop" if marker.slide == "stop" else "marker"
        self.title.setText(f"<b>{marker.name or marker.id}</b> - {what} at {marker.t:g} s")
        for path, field in self.fields.items():
            if not field.has_focus() or force:
                value = getattr(marker, path.split(".", 1)[1])
                field.set_value(value == "stop" if path == "marker.slide" else value)
        self.fields["marker.loop"].widget.setEnabled(marker.slide == "stop")  # only a stop waits

    def _refresh_subtitle(self, force: bool) -> None:
        cue = next((c for c in self.project.subtitles if c.id == self.subtitle_id), None)
        if cue is None:
            self.show_nothing()
            return
        self.title.set_kind(KINDS["subtitle"])
        self.title.setText(f"<b>Subtitle</b> {cue.start:g} - {cue.end:g} s")
        for path, field in self.fields.items():
            if field.has_focus() and not force:
                continue
            owner, name = path.split(".", 1)
            field.set_value(getattr(cue if owner == "cue" else self.project.subtitle_style, name))

    def _refresh_audio(self, force: bool) -> None:
        clip = next((c for c in self.project.audio if c.id == self.audio_id), None)
        if clip is None:
            self.show_nothing()
            return
        self.title.set_kind(KINDS["sound"])
        self.title.setText(f"<b>{clip.name or clip.id}</b> - sound ({Path(clip.path).name})")
        for path, field in self.fields.items():
            if not field.has_focus() or force:
                field.set_value(getattr(clip, path.split(".", 1)[1]))

    # -- showing values -------------------------------------------------------------

    def refresh(self, force: bool = False) -> None:
        """Show the document's values (or a pending value) in every field not being edited."""
        if self.audio_id is not None:
            self._refresh_audio(force)
            return
        if self.subtitle_id is not None:
            self._refresh_subtitle(force)
            return
        if self.marker_id is not None:
            self._refresh_marker(force)
            return
        if self.layer_id is None:
            if self.scene_shown:
                self._refresh_scene(force)
            return
        if not _has(self.project, self.layer_id):
            self.show_nothing()
            return
        layer = self.project.layer(self.layer_id)
        if self.clip_id is not None and self._clip(self.layer_id, self.clip_id) is None:
            self.show_layer(self.layer_id)
            return
        if self.clip_id is not None and self._clip(self.layer_id, self.clip_id).kind != self._shown_kind:
            self.show_clip(self.layer_id, self.clip_id)  # another kind has other params
            return
        if self.key_time is not None:
            keyed = _keyed_props(layer, self.key_time, self.project.canvas.fps)
            if keyed != self._shown_props:  # keys moved away or properties changed: rebuild or fall back
                self.show_key(self.layer_id, self.key_time)
                return
        if self._shown_pieces is not None and _pieces(layer) != self._shown_pieces:
            self.show_layer(self.layer_id)  # a piece was coloured or uncoloured: other rows
            return
        if self._shown_params is not None and adapter.python_params(layer.spec) != self._shown_params:
            self.show_layer(self.layer_id)  # its code declares other parameters now
            return
        if self._shown_type is not None and layer.spec is not None and layer.spec.type != self._shown_type:
            self.show_layer(self.layer_id)  # frozen into a shape (or the freeze undone): other sections
            return
        self._refresh_python_status(layer)
        self._update_title(layer)
        for path, field in self.fields.items():
            if field.has_focus() and not force:
                continue
            waiting, value = self.builds.pending_value(self._keys[path])
            field.set_value(value if waiting else self._getters[path](layer), pending=waiting)
            if path.startswith("base.") and layer.tracks.get(path.split(".", 1)[1]):
                field.widget.setToolTip("Keyed: a change sets a key at the playhead frame")
            elif path in self._tips and not waiting:
                field.widget.setToolTip(self._tips[path])
        if self._section_keys is not None:
            button, toggles = self._section_keys
            button.setChecked(any(toggle.widget.isChecked() for toggle in toggles))

    def _update_title(self, layer: Layer) -> None:
        name = layer.label
        if self.key_time is not None:
            self.title.set_kind(KINDS["keys"])
        elif self.clip_id is not None:
            self.title.set_kind(KINDS["clip"])
        else:
            self.title.set_kind(kind_of(layer))
        if self.key_time is not None:
            self.title.setText(f"<b>Keys at {self.key_time:g} s</b> on {name}")
        elif self.clip_id is None and layer.is_part:
            parent = self.project.layer(layer.parent_id)
            orphans = parts.resolve(self.project, self.project.root_of(layer.id).id).orphans
            note = f"<br><i>Not drawn: {orphans[layer.id]}</i>" if layer.id in orphans else ""
            self.title.setText(f"<b>{name}</b> - part of {parent.label}{note}")
        elif self.clip_id is None and layer.is_camera:
            keys = sum(len(track) for track in layer.tracks.values())
            self.title.setText(f"<b>{name}</b> - One per project · {keys} key{'s' * (keys != 1)}")
        elif self.clip_id is None:
            more = ""
            if self.others_selected:  # several objects (ADR 0043): this panel shows the primary one
                more = (
                    f"<br><i>and {self.others_selected} more selected: "
                    "moves, presets and themes apply to all</i>"
                )
            self.title.setText(f"<b>{name}</b> - {layer.spec.type}{more}")
        else:
            clip = self._clip(layer.id, self.clip_id)
            self.title.setText(f"<b>{clip.kind}</b> clip on {name}")

    # -- sections ---------------------------------------------------------------------

    def _tab_layer(self) -> Layer | None:
        """The object the Properties and Clip tabs would show: the one shown, or the Scene tab's origin."""
        layer_id = self.layer_id or self._return_to
        return self.project.layer(layer_id) if layer_id and _has(self.project, layer_id) else None

    def _sync_tabs(self) -> None:
        layer = self._tab_layer()
        if self.clip_id is not None:
            current = CLIP
        elif self.layer_id is not None:
            current = PROPERTIES
        elif self.audio_id is None and self.subtitle_id is None and self.marker_id is None:
            current = SCENE
        else:
            current = None
        self.tabs.show_state(
            current, properties=layer is not None, clip=layer is not None and bool(layer.clips)
        )

    def _on_tab(self, key: str) -> None:
        """A click on a tab of the header: show the object, one of its clips, or the scene's settings."""
        layer = self._tab_layer()
        if key == SCENE:
            came_from = self.layer_id or self._return_to
            self.show_nothing()
            self._return_to = came_from if came_from and _has(self.project, came_from) else None
            self._sync_tabs()
        elif layer is None:
            self._sync_tabs()
        elif key == PROPERTIES:
            self.show_layer(layer.id)
        elif layer.clips:
            t = self.playhead()
            clip = next((c for c in layer.clips if c.start <= t <= c.end), layer.clips[0])
            self.show_clip(layer.id, clip.id)

    def _rebuild(self) -> None:
        self._generation += 1
        self._return_to = None
        self.code_label = self.retry_button = self.fit_button = None
        self.part_tex = self.part_occurrence = self.part_colour_button = None
        self._shown_pieces = None
        self._shown_params = None
        self.python_label = None
        self.freeze_button = None
        self.characters_button = None
        self._shown_type = None
        self.scene_shown = False
        self._section_keys = None
        self.fields.clear()
        self.sections.clear()
        self._tips.clear()
        self._getters.clear()
        self._keys.clear()
        self._sync_tabs()
        while self.body_layout.count():
            widget = self.body_layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()  # deleteLater only runs once control returns to the event loop
                widget.deleteLater()

    def _new_section(self, title: str) -> Section:
        """A collapsible section; one the user closed stays closed for the next selection."""
        section = Section(title)
        section.set_collapsed(title in self._collapsed)
        section.toggled.connect(
            lambda collapsed: self._collapsed.add(title) if collapsed else self._collapsed.discard(title)
        )
        self.sections[title] = section
        self.body_layout.addWidget(section)
        return section

    def _append(self, widget: QWidget) -> None:
        """A button or a note under the last section's fields (or on its own when there is none)."""
        last = self.body_layout.itemAt(self.body_layout.count() - 1)
        box = last.widget() if last is not None else None
        if isinstance(box, Section):
            box.add_widget(widget)
        else:
            self.body_layout.addWidget(widget)

    def _section(self, title: str, rows: list, always: bool = False) -> Section | None:
        """A section of rows: ``(label, path, field)``, or ``(label, [(path, field[, inner label]), ...])``
        for several fields on one row. A lone number or text field holds its label inside; any other row
        has it above, as a caption. Keyframe diamonds (``KeyToggle``) sit at the right of their row."""
        if not rows and not always:
            return None
        section = self._new_section(title)
        for label, *cells in rows:
            cells = [(cells[0], cells[1])] if len(cells) == 2 else cells[0]
            main, keys = [], []
            for path, field, *inner in cells:
                self.fields[path] = field
                if isinstance(field, KeyToggle):
                    keys.append(field)
                    continue
                if inner:
                    field.set_label(inner[0])
                description = (inner[0] if inner else label) or path.rsplit(".", 1)[-1].replace("_", " ")
                self._wire_field_preview(field, description)
                main.append(field)
            inside = bool(label) and len(main) == 1 and len(cells[0]) == 2 and main[0].set_label(label)
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(2 * theme.SPACE)
            for field in main:
                line.addWidget(field.widget, 1)
            for field in keys:
                line.addWidget(field.widget, 0, Qt.AlignmentFlag.AlignVCenter)
            if label and not inside:
                block = QVBoxLayout()
                block.setContentsMargins(0, 0, 0, 0)
                block.setSpacing(5)
                block.addWidget(caption(label))
                block.addLayout(line)
                section.add_layout(block)
            else:
                section.add_layout(line)
        return section

    def _wire_field_preview(self, field: Field, description: str) -> None:
        """Make a field's mouse gesture a live document preview with one undo step."""
        labels = field.scrub_labels()
        slider = field.widget.slider if isinstance(field, SliderField) else None
        if not labels and slider is None:
            return

        def begin() -> None:
            if self.document.dragging:
                return
            field.begin_scrub_preview()
            self.document.begin_preview(field_edit=True)

        def finish() -> None:
            if not self.document.field_edit_preview:
                return
            start, final = field.end_scrub_preview()
            if final == start:
                self.document.cancel_preview()
                return
            self.document.commit_preview(f"Change {description.lower()}")
            # A cold edit was held back during the drag; submit only its final value now.
            field.on_commit(final)

        for scrub_label in labels:
            scrub_label.scrubStarted.connect(begin)
            scrub_label.scrubFinished.connect(finish)
        if slider is not None:
            slider.sliderPressed.connect(begin)
            slider.sliderReleased.connect(finish)

    def _register(self, path: str, getter: Callable[[Layer], Any]) -> None:
        self._getters[path] = getter
        self._keys[path] = self._key(path)

    def _key(self, path: str) -> Hashable:
        """The supersede key: one waiting edit per field of this layer or clip."""
        if self.key_time is not None:
            return (self.layer_id, "keys", self.key_time, path)
        return (self.layer_id, path) if self.clip_id is None else (self.layer_id, self.clip_id, path)

    def _key_section(self, layer: Layer, t: float) -> None:
        fps = self.project.canvas.fps
        props = _keyed_props(layer, t, fps)
        self._shown_props = props
        duration = self.project.canvas.duration
        self._register("keys.time", lambda layer: t)
        time_field = FloatField(self._retime_commit(t), 0, duration, 1 / fps, 3, suffix=" s")
        rows: list = [("Time", "keys.time", time_field)]
        height = self.project.canvas.frame_height
        for prop in props:
            label = prop.capitalize()
            value_path, ease_path = f"keys.{prop}.value", f"keys.{prop}.ease"
            self._register(ease_path, lambda layer, p=prop: _key_at(layer, p, t, fps).ease)
            if layer.is_camera and prop == "scale":  # shown and typed as its size (ADR 0083)
                label = "Size"
                self._register(
                    value_path, lambda layer: camera_size(_key_at(layer, "scale", t, fps).value, height)
                )
                set_size = partial(_set_size_key, t=t)
                value_field = FloatField(
                    self._op(value_path, set_size, "Change size key"), 0.01, 10_000, 0.1, 3
                )
            else:
                self._register(value_path, lambda layer, p=prop: _key_at(layer, p, t, fps).value)
                set_value = partial(_set_key_value, prop=prop, t=t)
                value_field = _key_value_field(prop, self._op(value_path, set_value, f"Change {prop} key"))
            set_ease = partial(_set_key_ease, prop=prop, t=t)
            ease_field = self._ease_field(
                self._op(ease_path, set_ease, "Change easing"), ease_path, keys=True
            )
            if _is_last_key(layer, prop, t, fps):
                ease_field.widget.setEnabled(False)
                ease_field.widget.setToolTip("Last key: no motion follows it, so its easing has no effect")
            else:
                ease_field.widget.setToolTip(f"How {prop} moves from this key to the next")
            rows.append((label, value_path, value_field))
            rows.append(("Easing", ease_path, ease_field))
        self._section("Keyframes", rows)

    def _ease_field(self, commit: Callable[[Any], None], path: str, keys: bool) -> ChoiceField:
        """An easing list ending in "Custom curve...", which opens the curve editor."""
        choices = [*_ease_choices(keys=keys), ("Custom curve...", CUSTOM_CURVE)]
        field = ChoiceField(commit, choices, label_for=ease_label)

        def on_commit(value: Any) -> None:
            if value == CUSTOM_CURVE:
                current = self._getters[path](self.project.layer(self.layer_id))
                value = self.curve_dialog(current)
                if value is None:  # cancelled
                    self.refresh(force=True)
                    return
            commit(value)

        field.on_commit = on_commit
        return field

    def _retime_commit(self, t: float) -> Callable[[Any], None]:
        layer_id, generation = self.layer_id, self._generation

        def commit(value: Any) -> None:
            if generation != self._generation or value is None:
                return
            try:
                self.builds.submit(
                    partial(edits.retime_keys, layer_id=layer_id, t_from=t, t_to=value), "Move keys"
                )
            except (edits.EditError, ValidationError) as exc:
                self.message.emit(f"Move keys: {_first_error(exc)}")
                self.refresh(force=True)
                return
            fps = self.project.canvas.fps
            self.keyMoved.emit(layer_id, round(value * fps) / fps)

        return commit

    def _object_section(self, layer: Layer) -> None:
        if layer.spec.type in PYTHON_TYPES:
            self._python_section(layer)
            return
        rows = []
        for param in adapter.MOBJECT_PARAMS.get(layer.spec.type, ()):
            path = f"params.{param.name}"
            self._register(path, lambda layer, p=param: adapter.param_value(layer.spec, p))
            commit = self._op(path, partial(set_param, name=param.name), f"Change {param.title.lower()}")
            if layer.spec.type in CODE_TYPES:
                commit = self._trusting(commit)
            if param.kind == "graph":  # a graph on the same axes (ADR 0030)
                graphs = [
                    x for x in self.project.children(layer.parent_id) if x.spec and x.spec.type == "Graph"
                ]
                choices = [(x.label, x.id) for x in graphs]
                required = dict(GRAPH_PARAMS.get(layer.spec.type, ())).get(param.name, True)
                if not required:
                    choices.insert(0, ("(the x axis)", ""))
                rows.append((param.title, path, ChoiceField(commit, choices)))
                continue
            if param.kind == "layer":  # the layer a trace follows, or a connector joins (ADR 0033, 0036)
                names = {x.id: x.label for x in self.project.layers}
                choices = [(names[i], i) for i in self.project.traceable_ids(layer.id)]
                rows.append((param.title, path, ChoiceField(commit, choices)))
                continue
            rows.append((param.title, path, _param_field(param, commit)))
        self._section(layer.spec.type, rows)
        if layer.spec.type in CODE_TYPES:
            self._code_status_row(layer.id)

    def _colour_characters_row(self, layer_id: str) -> None:
        """A Text, MathTex or Tex: "Colour characters..." in its object section (ADR 0055)."""
        self.characters_button = QPushButton("Colour characters...")
        self.characters_button.setToolTip(
            "Colour the letters or symbols one by one: click them on a large preview, or give them a "
            "gradient, a rainbow or two alternating colours (one undo step)"
        )
        generation = self._generation
        self.characters_button.clicked.connect(
            lambda: generation == self._generation and self.colour_characters(layer_id)
        )
        self._append(self.characters_button)

    def colour_characters(self, layer_id: str) -> None:
        """Ask for the colour of each glyph and apply it (one undo step, ADR 0055)."""
        if not _has(self.project, layer_id):
            return
        current = self.project.layer(layer_id).spec.params.get(GLYPH_COLOURS)
        colours = self.ask_glyph_colours(layer_id, current)
        if colours is None or glyph_colours.normalised(colours) == glyph_colours.normalised(current):
            return
        try:
            self.builds.submit(
                partial(edits.set_glyph_colours, layer_id=layer_id, colours=colours), "Colour characters"
            )
        except (edits.EditError, ValidationError) as exc:
            self.message.emit(f"Colour characters: {_first_error(exc)}")

    def _freeze_row(self, layer: Layer) -> None:
        """A shape says it is frozen (no parameters: undo is the way back); an object that can be
        frozen has "Freeze to shape" (ADR 0052). Whether it can be now is said on click."""
        if layer.spec.type in SHAPE_TYPES:
            box = self._new_section("Shape")
            note = QLabel(f"{shape.FROZEN_NOTE}: no code, no LaTeX. Undo turns it back.")
            note.setWordWrap(True)
            note.setObjectName("frozenNote")
            note.setProperty("role", "muted")
            box.add_widget(note)
            return
        if shape.kind_problem(layer) is not None or layer.spec.type in plugins.SIMULATIONS:
            return
        box = QWidget()
        line = QHBoxLayout(box)
        line.setContentsMargins(0, 0, 0, 0)
        self.freeze_button = QPushButton("Freeze to shape")
        self.freeze_button.setToolTip(
            "Turn it into plain vector data as it is drawn now: it needs no code, no trust and no "
            "LaTeX, so it plays on any computer. Its parameters are gone (undo turns it back)."
        )
        self.freeze_button.setProperty("role", "ghost")
        self.freeze_button.clicked.connect(lambda: self.freeze(layer.id))
        line.addStretch(1)
        line.addWidget(self.freeze_button)
        self._append(box)

    def _python_section(self, layer: Layer) -> None:
        """A Python object (ADR 0051): a field per parameter its PARAMS declares, read without
        running the code, then what its build says and a way to its code."""
        params = adapter.python_params(layer.spec)
        rows = []
        for param in params:
            path = f"values.{param.name}"

            def getter(layer: Layer, p: Param = param) -> Any:
                code = str(layer.spec.params.get("code", ""))
                return python_object.call_values(code, layer.spec.params.get("values") or {}).get(p.name)

            self._register(path, getter)
            commit = self._op(path, partial(set_python_value, name=param.name), f"Change {param.name}")
            rows.append((param.title, path, _param_field(param, commit)))
        self._section("Python object", rows, always=True)
        self._shown_params = params
        box = QWidget()
        line = QHBoxLayout(box)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(2 * theme.SPACE)
        self.python_label = QLabel()
        self.python_label.setWordWrap(True)
        self.python_label.setObjectName("pythonStatus")
        self.python_label.setProperty("role", "muted")
        edit = QPushButton("Edit code")
        edit.setToolTip("Open its code on the Code page")
        edit.clicked.connect(lambda: self.edit_code(layer.id))
        line.addWidget(self.python_label, 1)
        line.addWidget(edit)
        self._append(box)
        self._refresh_python_status(layer)

    def _refresh_python_status(self, layer: Layer) -> None:
        if self.python_label is None or layer.spec is None or layer.spec.type not in PYTHON_TYPES:
            return
        signature = adapter.media_signature(layer.spec, helpers.sources(self.project))  # (ADR 0058)
        problem = adapter.build_problem(layer.spec, signature)
        if problem == python_object.NOT_TRUSTED:
            text = "Not run: its code is not trusted on this computer. Apply it on the Code page to run it."
        elif problem is not None:
            text = f"Error: {problem}"
        else:
            text = "Built by its code." if self._shown_params else "Built by its code (no PARAMS)."
        try:
            self.python_label.setText(text)
        except RuntimeError:  # the row was rebuilt meanwhile
            self.python_label = None

    def _trusting(self, commit: Callable[[Any], None]) -> Callable[[Any], None]:
        """Code the user applies here is theirs: trust it, then apply it (ADR 0019)."""

        def apply(value: Any) -> None:
            self.trust_code(str(value))
            commit(value)

        return apply

    def _code_status_row(self, layer_id: str) -> None:
        box = QWidget()
        line = QHBoxLayout(box)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(2 * theme.SPACE)
        self.code_label = QLabel()
        self.code_label.setWordWrap(True)
        self.code_label.setProperty("role", "muted")
        self.retry_button = QPushButton("Run again")
        self.retry_button.clicked.connect(lambda: self.retry_code(layer_id))
        line.addWidget(self.code_label, 1)
        line.addWidget(self.retry_button)
        self._append(box)
        self.refresh_code_status(layer_id)

    def refresh_code_status(self, layer_id: str) -> None:
        """Show a code layer's render status (queued, rendering, ready, error, untrusted)."""
        if self.code_label is None or layer_id != self.layer_id or self.clip_id or self.key_time is not None:
            return
        try:
            self.code_label.setText(self.code_status(layer_id) or "")
            self.retry_button.setVisible(self.code_failed(layer_id))
        except RuntimeError:  # the row was rebuilt meanwhile
            self.code_label = self.retry_button = None

    def _part_section(self) -> None:
        """The part's key: which piece of its parent's TeX it is (ADR 0012)."""
        self._register("part.tex", lambda layer: layer.part.tex)
        self._register("part.occurrence", lambda layer: layer.part.occurrence + 1)
        tex = TextField(
            self._op("part.tex", partial(set_part_key, name="tex"), "Change part"), "TeX of the part"
        )
        occurrence = IntField(
            self._op("part.occurrence", partial(set_part_key, name="occurrence"), "Change part"), 1, 999
        )
        self._section("Part", [("TeX", "part.tex", tex), ("Occurrence", "part.occurrence", occurrence)])

    def _part_style_section(self) -> None:
        """A part's colours (ADR 0049): its glyphs only; Default is its object's colour."""
        rows = []
        for key, label in (("fill", "Fill"), ("stroke", "Stroke")):
            path = f"part_style.{key}"
            self._register(path, lambda layer, k=key: layer.style.get(k))
            op = partial(set_part_colour, key=key)
            rows.append((label, path, ColorField(self._op(path, op, f"Colour part {label.lower()}"))))
        self._section("Style", rows)

    def _colour_part_section(self, layer_id: str) -> None:
        """Colour a part of an equation without making it a separate object (ADR 0049): the TeX to
        match and which occurrence; the colour button makes the part layer if needed and colours it,
        in one undo step."""
        box = self._new_section("Colour a part")
        self.part_tex = LabelledLineEdit()
        self.part_tex.set_label("TeX")
        self.part_tex.setPlaceholderText(r"e.g. b^2 or \pi, as in the TeX")
        self.part_tex.setToolTip(r"The TeX of the part, as it appears in the equation (e.g. b^2 or \pi)")
        self.part_occurrence = ScrubSpinBox()
        self.part_occurrence.setRange(1, 999)
        self.part_occurrence.set_label("Occurrence")
        self.part_occurrence.setToolTip("Which match of the TeX: 1 is the first")
        self.part_colour_button = QPushButton("Colour...")
        self.part_colour_button.setToolTip("Choose the colour of that part (it becomes a part layer)")
        generation = self._generation
        self.part_colour_button.clicked.connect(
            lambda: generation == self._generation and self.colour_part(layer_id)
        )
        box.add_widget(self.part_tex)
        line = QHBoxLayout()
        line.setSpacing(2 * theme.SPACE)
        line.addWidget(self.part_occurrence, 1)
        line.addWidget(self.part_colour_button, 1)
        box.add_layout(line)

    def colour_part(self, parent_id: str) -> None:
        """Ask for a colour and give it to the typed part of ``parent_id`` (one undo step)."""
        tex, occurrence = self.part_tex.text(), self.part_occurrence.value() - 1
        if not tex.strip():
            self.message.emit("Colour part: type the TeX of the part first")
            return
        key = PartKey(tex=tex, occurrence=occurrence)
        existing = next((x for x in self.project.children(parent_id) if x.part == key), None)
        colour = self.ask_colour(existing.style.get("fill") if existing is not None else None)
        if colour is None:
            return
        op = partial(edits.colour_part, parent_id=parent_id, tex=tex, occurrence=occurrence, fill=colour)
        try:
            self.builds.submit(op, "Colour part")
        except (edits.EditError, ValidationError) as exc:
            self.message.emit(f"Colour part: {_first_error(exc)}")

    def _pieces_section(self, layer: Layer) -> None:
        """A Text's coloured pieces (Manim's ``t2c``, ADR 0049): one row each (x stops colouring it),
        and a row to colour another piece. Every match of a piece is coloured."""
        pieces = _pieces(layer)
        rows = []
        for piece in pieces:
            path = f"t2c.{piece}"
            self._register(path, lambda layer, p=piece: (layer.spec.params.get("t2c") or {}).get(p))
            commit = self._op(path, partial(set_piece_colour, piece=piece), "Colour piece")
            rows.append((piece, path, ColorField(commit)))
        box = self._section("Colour a piece", rows, always=True)
        self.part_tex = LabelledLineEdit()
        self.part_tex.set_label("Text")
        self.part_tex.setPlaceholderText("a word or letters of the text")
        self.part_colour_button = QPushButton("Colour...")
        self.part_colour_button.setToolTip("Choose the colour of every match of these letters")
        generation, layer_id = self._generation, layer.id
        self.part_colour_button.clicked.connect(
            lambda: generation == self._generation and self.colour_piece(layer_id)
        )
        line = QHBoxLayout()
        line.setSpacing(2 * theme.SPACE)
        line.addWidget(self.part_tex, 1)
        line.addWidget(self.part_colour_button)
        box.add_layout(line)
        help_text = QLabel("To colour single letters, use Colour characters... above.")
        help_text.setWordWrap(True)
        help_text.setObjectName("hint")
        help_text.setProperty("role", "hint")
        box.add_widget(help_text)
        self._shown_pieces = pieces

    def colour_piece(self, layer_id: str) -> None:
        """Ask for a colour and give it to the typed piece of the Text ``layer_id`` (one undo step)."""
        piece = self.part_tex.text()
        if not piece:
            self.message.emit("Colour piece: type the letters to colour first")
            return
        current = (self.project.layer(layer_id).spec.params.get("t2c") or {}).get(piece)
        colour = self.ask_colour(current)
        if colour is None:
            return
        try:
            self.builds.submit(
                partial(edits.set_text_colour, layer_id=layer_id, piece=piece, colour=colour), "Colour piece"
            )
        except (edits.EditError, ValidationError) as exc:
            self.message.emit(f"Colour piece: {_first_error(exc)}")

    def _style_section(self) -> None:
        cells = {}
        for key, label, make in (
            ("fill", "Fill", lambda c: ColorField(c)),
            ("fill_opacity", "Fill opacity", lambda c: FloatField(c, 0, 1, 0.05, 2, none_text="Default")),
            ("stroke", "Stroke", lambda c: ColorField(c)),
            ("stroke_width", "Stroke width", lambda c: FloatField(c, 0, 50, 0.5, 1, none_text="Default")),
        ):
            path = f"style.{key}"
            self._register(path, lambda layer, k=key: layer.spec.style.get(k))
            cells[key] = (path, make(self._op(path, partial(set_style, key=key), f"Change {label.lower()}")))
        # a colour and its amount side by side (the mock-up's row of two)
        rows = [
            ("Fill", [cells["fill"], (*cells["fill_opacity"], "Opacity")]),
            ("Stroke", [cells["stroke"], (*cells["stroke_width"], "Width")]),
        ]
        self._section("Style", rows)

    def _transform_section(self, layer: Layer) -> None:
        rows = []
        toggles: list[tuple[str, KeyToggle]] = []
        keyable = keyable_props(layer)  # a graph keeps only its opacity (ADR 0024)
        if layer.is_group:
            keyable = tuple(name for name in keyable if name not in ("scale_x", "scale_y"))
        if layer.is_camera:  # Unity's Transform of a 2D camera: position, size, rotation (ADR 0083)
            keyable = ("position", "scale", "rotation")
        for name, label, field_type in (
            ("position", "Position", lambda c: PointField(c)),
            ("scale", "Scale", lambda c: FloatField(c, 0.01, 100, 0.05, 3)),
            ("scale_x", "Width scale", lambda c: FloatField(c, 0.01, 100, 0.05, 3)),
            ("scale_y", "Height scale", lambda c: FloatField(c, 0.01, 100, 0.05, 3)),
            ("rotation", "Rotation", lambda c: FloatField(c, -3600, 3600, 1, 1, suffix=" deg")),
            ("opacity", "Opacity", lambda c: SliderField(c, 0, 1)),
        ):
            if name not in keyable:
                continue
            path = f"base.{name}"
            set_value = set_transform
            if layer.is_camera and name == "scale":  # the size: half the height it sees (ADR 0083)
                label = "Size"
                field_type = lambda c: FloatField(c, 0.01, 10_000, 0.1, 3, suffix=" half height")  # noqa: E731
                set_value = set_camera_size
                self._tips[path] = "Half the height the camera sees, in scene units (an orthographic size)"
                self._register(path, self._camera_size_value)
            else:
                self._register(path, lambda layer, n=name: self._transform_value(layer, n))
            op = partial(set_value, name=name, at=lambda: self.playhead(), auto_key=lambda: self.auto_key())
            field = field_type(self._op(path, op, f"Change {label.lower()}"))
            key_path = f"keys.{name}"
            self._register(key_path, lambda layer, n=name: bool(layer.tracks.get(n)))
            animate = partial(set_animated, prop=name, at=lambda: self.playhead())
            toggle = KeyToggle(
                self._op(key_path, animate, f"Animate {label.lower()}"),
                f"Keyframes for {label.lower()}: on = changes set a key at the playhead",
            )
            toggles.append((label, toggle))
            rows.append((label, [(path, field), (key_path, toggle)]))
            if name == "position" and not layer.is_camera:  # the camera has no pivot of its own
                rows.append(self._anchor_row())
        section = self._section("Transform", rows)
        if section is not None and toggles:
            section.add_action(self._keys_button(toggles))

    def _keys_button(self, toggles: list[tuple[str, KeyToggle]]) -> QToolButton:
        """The section's keyframe diamond: filled while any of its properties has keys; its menu turns
        keyframes on or off for each (the same as the diamonds beside the values)."""
        button = KeyDiamond()
        button.setObjectName("sectionKeys")
        button.setToolTip("Keyframes: which of these properties are animated")
        button.setAccessibleName("Keyframes")
        menu = QMenu(button)
        menu.setToolTipsVisible(True)
        actions = []
        for label, toggle in toggles:
            action = menu.addAction(f"Animate {label.lower()}")
            action.setCheckable(True)
            action.setToolTip(toggle.widget.toolTip())
            action.triggered.connect(lambda checked, t=toggle: t.widget.setChecked(checked))
            actions.append((action, toggle))

        def sync() -> None:
            for action, toggle in actions:
                with QSignalBlocker(action):
                    action.setChecked(toggle.widget.isChecked())

        menu.aboutToShow.connect(sync)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._section_keys = (button, [toggle for _label, toggle in toggles])
        return button

    def _anchor_row(self):
        """The anchor point (ADR 0021): base only, so no Keys toggle."""
        path = "base.anchor"
        self._register(path, lambda layer: layer.base.anchor)

        def op(project: Project, layer_id: str, value: Any) -> edits.Edit:
            edit = set_anchor(project, layer_id, value, at=lambda: self.playhead())
            if edits.anchor_shifts_elsewhere(edit.project.layer(layer_id)):
                self.message.emit(SHIFTS_ELSEWHERE)
            return edit

        field = PointField(self._op(path, op, "Move anchor"))
        field.widget.setToolTip(
            "The point it rotates and scales about, in its own units (0, 0 = its centre). "
            "Ctrl+drag the cross on the canvas to move it."
        )
        return ("Anchor point", [(path, field)])

    def _camera_size_value(self, layer: Layer) -> float:
        """The camera's size at the playhead: its scale eased as a size when keyed (ADR 0083)."""
        scale = (
            camera_transform(layer, self.playhead()).scale if layer.tracks.get("scale") else layer.base.scale
        )
        return camera_size(scale, self.project.canvas.frame_height)

    def _camera_layer_section(self) -> None:
        """The camera's own settings (ADR 0083): a background for the whole video, and a layer it follows."""
        rows = []
        background = "params.background"
        self._register(background, lambda layer: layer.spec.params.get("background"))
        commit = self._op(
            background, partial(set_camera_param, name="background"), "Change camera background"
        )
        self._tips[background] = "The colour behind everything in the video; x uses the project's background"
        rows.append(("Background", background, ColorField(commit)))
        follow = "params.follow"
        self._register(follow, lambda layer: layer.spec.params.get("follow") or None)
        choices = [("Nothing", None)] + [(x.label, x.id) for x in self.project.follow_targets()]
        commit = self._op(follow, partial(set_camera_param, name="follow"), "Change followed layer")
        self._tips[follow] = "The camera looks at this layer, wherever it goes; its position keys add to that"
        rows.append(("Follow", follow, ChoiceField(commit, choices)))
        offset = "params.follow_offset"
        self._register(offset, lambda layer: tuple(layer.spec.params.get("follow_offset") or (0.0, 0.0)))
        commit = self._op(offset, partial(set_camera_param, name="follow_offset"), "Change follow offset")
        self._tips[offset] = "Where the camera looks, from the followed layer's centre"
        rows.append(("Offset", offset, PointField(commit)))
        self._section("Camera", rows)

    def _transform_value(self, layer: Layer, name: str):
        """A keyed property shows its value at the playhead; otherwise its base value."""
        if layer.tracks.get(name):
            return getattr(layer_transform(layer, self.playhead()), name)
        return getattr(layer.base, name)

    def _lifetime_section(self) -> None:
        duration = self.project.canvas.duration
        rows = []
        for key, label in (("in", "Appears at"), ("out", "Disappears at")):
            path = f"lifetime.{key}"
            self._register(path, lambda layer, k=key: getattr(layer.lifetime, "in_" if k == "in" else k))
            commit = self._op(path, partial(set_lifetime, key=key), "Change lifetime")
            rows.append((label, path, FloatField(commit, 0, duration, 0.1, 3, none_text="Auto", suffix=" s")))
        self._section("Lifetime", rows)

    def _clip_section(self, layer: Layer, clip) -> None:
        fps = self.project.canvas.fps
        duration = self.project.canvas.duration
        clip_id = clip.id
        morph = clip.info.category == "morph"
        kinds = [
            k
            for k in adapter.allowed_clip_kinds((layer.spec or self.project.root_of(layer.id).spec).type)
            if (CLIP_KIND_INFO[k].category == "morph") == morph
        ]

        def getter(name: str) -> Callable[[Layer], Any]:
            return lambda layer: getattr(self._clip(layer.id, clip_id), name)

        def commit(name: str, text: str) -> Callable[[Any], None]:
            return self._op(
                f"clip.{name}",
                lambda p, layer_id, value: edits.update_clip(p, layer_id, clip_id, **{name: value}),
                text,
            )

        rows: list[tuple[str, str, Field]] = []
        specs = [
            ("kind", "Animation", ChoiceField(commit("kind", "Change animation"), [(k, k) for k in kinds])),
            (
                "start",
                "Start",
                FloatField(commit("start", "Move clip"), 0, duration, 1 / fps, 3, suffix=" s"),
            ),
            (
                "duration",
                "Duration",
                FloatField(commit("duration", "Trim clip"), 1 / fps, duration, 1 / fps, 3, suffix=" s"),
            ),
            ("ease", "Easing", self._ease_field(commit("ease", "Change easing"), "clip.ease", keys=False)),
        ]
        if morph:
            targets = [
                (other.label, other.id)
                for other in self.project.layers
                if other.id != layer.id
                and (other.id == clip.to_layer or other.id not in self.project.morph_sources())
            ]
            specs.append(
                ("to_layer", "Turns into", ChoiceField(commit("to_layer", "Change morph target"), targets))
            )
        for name, label, field in specs:
            path = f"clip.{name}"
            self._register(path, getter(name))
            rows.append((label, path, field))
        for param in clip_params(clip.kind):  # registered params only (ADR 0022)
            path = f"clip.params.{param.name}"
            self._register(
                path, lambda layer, p=param: self._clip(layer.id, clip_id).params.get(p.name, p.default)
            )
            op = partial(set_clip_param, clip_id=clip_id, name=param.name)
            if param.kind == "layer":  # a path layer (ADR 0025)
                choices = [(other.label, other.id) for other in self.project.path_layers(layer.id)]
                commit = self._op(path, op, f"Change {param.label.lower()}")
                rows.append((param.label, path, ChoiceField(commit, choices)))
                continue
            if param.tooltip:  # e.g. a morph's Matching (ADR 0056)
                self._tips[path] = param.tooltip
            rows.append(
                (
                    param.label,
                    path,
                    _clip_param_field(param, self._op(path, op, f"Change {param.label.lower()}")),
                )
            )
        self._shown_kind = clip.kind
        self._section("Clip", rows)

    # -- committing -------------------------------------------------------------------

    def _op(self, path: str, op: Callable[..., edits.Edit], text: str) -> Callable[[Any], None]:
        """A field's commit callback: submit ``op`` for the current layer with the value."""

        layer_id, key, generation = self.layer_id, self._key(path), self._generation

        def commit(value: Any) -> None:
            if layer_id is None or generation != self._generation:
                return  # a widget of a previous selection (e.g. losing focus while deleted)
            bound = partial(_call, op, layer_id=layer_id, value=value)
            try:
                if self.document.field_edit_preview:
                    self.builds.preview(bound)
                else:
                    self.builds.submit(bound, text, supersede=key, value=value)
            except (edits.EditError, ValidationError) as exc:
                self.message.emit(f"{text}: {_first_error(exc)}")
                self.refresh(force=True)

        return commit

    def _layer_op(self, path: str, op: Callable[..., edits.Edit]) -> Callable[[Any], None]:
        self._register(path, lambda layer: layer.name)
        return self._op(path, op, "Rename layer")

    @staticmethod
    def _set_name(project: Project, layer_id: str, value: str) -> edits.Edit:
        name = value.strip()
        return edits.update_layer(project, layer_id, name="" if name == layer_id else name)

    def _clip(self, layer_id: str, clip_id: str):
        return next((c for c in self.project.layer(layer_id).clips if c.id == clip_id), None)


def _pieces(layer: Layer) -> tuple[str, ...]:
    """A Text's coloured pieces, in order (ADR 0049)."""
    return tuple(layer.spec.params.get("t2c") or {}) if layer.spec is not None else ()


def _call(op: Callable[..., edits.Edit], project: Project, *, layer_id: str, value: Any) -> edits.Edit:
    return op(project, layer_id=layer_id, value=value)


def _clip_param_field(param: ClipParam, commit: Callable[[Any], None]) -> Field:
    if param.kind == "direction":
        none = [("None", None)] if param.default is None else []
        return ChoiceField(commit, none + [(d.title(), d) for d in DIRECTIONS])
    if param.kind == "color":
        return ColorField(commit)
    if param.kind == "float":
        return FloatField(commit, param.minimum, param.maximum, param.step, 2)
    return ChoiceField(commit, [(c.title(), c) for c in param.choices])


def _param_field(param: Param, commit: Callable[[Any], None]) -> Field:
    if param.kind == "float":
        if param.precision is not None:
            decimals = param.precision
        elif param.step >= 1:
            decimals = 0
        elif param.step >= 0.05:
            decimals = 2
        else:
            decimals = 3
        minimum = 0.0 if param.minimum is None else param.minimum
        maximum = 1e4 if param.maximum is None else param.maximum
        return FloatField(commit, minimum, maximum, param.step, decimals, suffix=param.unit)
    if param.kind == "int":
        minimum = 0 if param.minimum is None else int(param.minimum)
        maximum = 1000 if param.maximum is None else int(param.maximum)
        return IntField(
            commit,
            minimum,
            maximum,
            suffix=param.unit,
            step=max(1, int(param.step)) if param.step else 1,
        )
    if param.kind == "choice":
        return ChoiceField(commit, [(c.capitalize(), c) for c in param.choices])
    if param.kind == "point":
        return PointField(
            commit,
            param.step,
            -1000.0 if param.minimum is None else param.minimum,
            1000.0 if param.maximum is None else param.maximum,
            param.unit,
            param.precision if param.precision is not None else 3,
        )
    if param.kind == "bool":  # a Python object's True/False (ADR 0051)
        return BoolField(commit)
    if param.kind == "colour":
        return ColorField(commit)
    if param.kind == "path":
        return PathField(commit, param.file_filter) if param.file_filter else PathField(commit)
    if param.name == "code":
        return CodeField(commit)
    if param.multiline:
        return LongTextField(commit)
    return TextField(commit, "default" if param.name == "font" else "")


def _ease_choices(keys: bool = False) -> list[tuple[str, Easing | None]]:
    """Clips may keep their animation's own easing (None); keys always have one."""
    choices: list[tuple[str, Easing | None]] = [] if keys else [("Animation default", None)]
    choices += [(name.replace("_", " "), Easing(name=name)) for name in adapter.EASE_NAMES]
    choices += [(label, Easing(name=None, bezier=b)) for label, b in adapter.BEZIER_PRESETS.items()]
    return choices


def _first_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return exc.errors()[0]["msg"].removeprefix("Value error, ")
    return str(exc)
