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

from collections.abc import Callable, Hashable
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import adapter, edits, parts
from ..core.adapter import Param
from ..core.evaluator import layer_transform
from ..core.schema import (
    CLIP_KIND_INFO,
    CODE_TYPES,
    DIRECTIONS,
    GRAPH_PARAMS,
    RASTER_TYPES,
    ClipParam,
    Easing,
    Layer,
    PartKey,
    Project,
    clip_params,
    keyable_props,
)
from .build_service import BuildService
from .curve_editor import ease_label, edit_curve
from .fields import (
    BoolField,
    ChoiceField,
    CodeField,
    ColorField,
    Field,
    FloatField,
    IntField,
    LongTextField,
    PathField,
    PointField,
    TextField,
)
from .gizmo import SHIFTS_ELSEWHERE

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


def _set_key_ease(project: Project, layer_id: str, value: Easing, prop: str, t: float) -> edits.Edit:
    return edits.set_key_ease(project, layer_id, t, value, props=[prop])


def _key_value_field(prop: str, commit: Callable[[Any], None]) -> Field:
    if prop == "position":
        return PointField(commit)
    if prop == "scale":
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


def _has(project: Project, layer_id: str) -> bool:
    return any(layer.id == layer_id for layer in project.layers)


# -- the panel ----------------------------------------------------------------------


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
        self.fields: dict[str, Field] = {}
        self._getters: dict[str, Callable[[Layer], Any]] = {}
        self._keys: dict[str, Hashable] = {}
        self._generation = 0  # bumped on every rebuild: old widgets can no longer commit
        self._shown_props: tuple[str, ...] = ()  # keys view: the properties keyed at key_time
        self._shown_kind: str | None = None  # clip view: the kind whose params are shown (ADR 0022)
        self.playhead: Callable[[], float] = lambda: 0.0  # set by the window (stopwatch keys)
        self.auto_key: Callable[[], bool] = lambda: False  # Edit > Auto-key (ADR 0018)
        # Code layers (ADR 0019), set by the window: status text, retry, and trusting applied code.
        self.code_status: Callable[[str], str | None] = lambda layer_id: None
        self.code_failed: Callable[[str], bool] = lambda layer_id: False
        self.retry_code: Callable[[str], None] = lambda layer_id: None
        self.trust_code: Callable[[str], None] = lambda code: None
        self.code_label: QLabel | None = None
        self.retry_button: QPushButton | None = None
        # "Custom curve...": shows the curve editor; tests replace it (P2b)
        self.curve_dialog: Callable[[Easing | None], Easing | None] = lambda ease: edit_curve(self, ease)

        self.title = QLabel()
        self.title.setWordWrap(True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(300)
        scroll.setWidget(self.body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
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
        self.layer_id = self.clip_id = self.key_time = self.audio_id = self.subtitle_id = None
        self._rebuild()
        self.title.setText("Select a layer, a clip or a keyframe.")

    def show_layer(self, layer_id: str) -> None:
        if not layer_id or not _has(self.project, layer_id):
            self.show_nothing()
            return
        self.layer_id, self.clip_id, self.key_time, self.audio_id = layer_id, None, None, None
        self.subtitle_id = None
        self._rebuild()
        layer = self.project.layer(layer_id)
        self._section(
            "Layer", [("Name", "name", TextField(self._layer_op("name", self._set_name), layer.id))]
        )
        if layer.is_part:
            self._part_section()
        else:
            self._object_section(layer)
            if layer.spec.type not in RASTER_TYPES | CODE_TYPES:  # no style on images or code
                self._style_section()
        self._transform_section(layer)
        self._lifetime_section()
        self.body_layout.addStretch(1)
        self.refresh()

    def show_clip(self, layer_id: str, clip_id: str) -> None:
        if not _has(self.project, layer_id) or self._clip(layer_id, clip_id) is None:
            self.show_nothing()
            return
        self.layer_id, self.clip_id, self.key_time, self.audio_id = layer_id, clip_id, None, None
        self.subtitle_id = None
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
        self.subtitle_id = None
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
        self.layer_id = self.clip_id = self.key_time = self.subtitle_id = None
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
        self.layer_id = self.clip_id = self.key_time = self.audio_id = None
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

    def _refresh_subtitle(self, force: bool) -> None:
        cue = next((c for c in self.project.subtitles if c.id == self.subtitle_id), None)
        if cue is None:
            self.show_nothing()
            return
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
        if self.layer_id is None:
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
        self._update_title(layer)
        for path, field in self.fields.items():
            if field.has_focus() and not force:
                continue
            waiting, value = self.builds.pending_value(self._keys[path])
            field.set_value(value if waiting else self._getters[path](layer), pending=waiting)
            if path.startswith("base.") and layer.tracks.get(path.split(".", 1)[1]):
                field.widget.setToolTip("Keyed: a change sets a key at the playhead frame")

    def _update_title(self, layer: Layer) -> None:
        name = layer.name or layer.id
        if self.key_time is not None:
            self.title.setText(f"<b>Keys at {self.key_time:g} s</b> on {name}")
        elif self.clip_id is None and layer.is_part:
            parent = self.project.layer(layer.parent_id)
            orphans = parts.resolve(self.project, self.project.root_of(layer.id).id).orphans
            note = f"<br><i>Not drawn: {orphans[layer.id]}</i>" if layer.id in orphans else ""
            self.title.setText(f"<b>{name}</b> - part of {parent.name or parent.id}{note}")
        elif self.clip_id is None:
            self.title.setText(f"<b>{name}</b> - {layer.spec.type}")
        else:
            clip = self._clip(layer.id, self.clip_id)
            self.title.setText(f"<b>{clip.kind}</b> clip on {name}")

    # -- sections ---------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._generation += 1
        self.code_label = self.retry_button = None
        self.fields.clear()
        self._getters.clear()
        self._keys.clear()
        while self.body_layout.count():
            widget = self.body_layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()  # deleteLater only runs once control returns to the event loop
                widget.deleteLater()

    def _section(self, title: str, rows: list[tuple[str, str, Field]]) -> None:
        if not rows:
            return
        box = QGroupBox(title)
        form = QFormLayout(box)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for label, *cells in rows:
            # (label, path, field) or (label, [(path, field), ...]) for several fields on one row
            cells = [tuple(cells)] if len(cells) == 2 else cells[0]
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            for path, field in cells:
                line.addWidget(field.widget, 1 if len(cells) == 1 or path.startswith("base.") else 0)
                self.fields[path] = field
            form.addRow(label, row if len(cells) > 1 else cells[0][1].widget)
        self.body_layout.addWidget(box)

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
        for prop in props:
            label = prop.capitalize()
            value_path, ease_path = f"keys.{prop}.value", f"keys.{prop}.ease"
            self._register(value_path, lambda layer, p=prop: _key_at(layer, p, t, fps).value)
            self._register(ease_path, lambda layer, p=prop: _key_at(layer, p, t, fps).ease)
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
            rows.append(("  easing", ease_path, ease_field))
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
                choices = [(x.name or x.id, x.id) for x in graphs]
                required = dict(GRAPH_PARAMS.get(layer.spec.type, ())).get(param.name, True)
                if not required:
                    choices.insert(0, ("(the x axis)", ""))
                rows.append((param.title, path, ChoiceField(commit, choices)))
                continue
            if param.kind == "layer":  # the layer a trace follows (ADR 0033)
                names = {x.id: x.name or x.id for x in self.project.layers}
                choices = [(names[i], i) for i in self.project.traceable_ids(layer.id)]
                rows.append((param.title, path, ChoiceField(commit, choices)))
                continue
            rows.append((param.title, path, _param_field(param, commit)))
        self._section(layer.spec.type, rows)
        if layer.spec.type in CODE_TYPES:
            self._code_status_row(layer.id)

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
        self.code_label = QLabel()
        self.code_label.setWordWrap(True)
        self.retry_button = QPushButton("Run again")
        self.retry_button.clicked.connect(lambda: self.retry_code(layer_id))
        line.addWidget(self.code_label, 1)
        line.addWidget(self.retry_button)
        self.body_layout.addWidget(box)
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

    def _style_section(self) -> None:
        rows = []
        for key, label, make in (
            ("fill", "Fill", lambda c: ColorField(c)),
            ("fill_opacity", "Fill opacity", lambda c: FloatField(c, 0, 1, 0.05, 2, none_text="Default")),
            ("stroke", "Stroke", lambda c: ColorField(c)),
            ("stroke_width", "Stroke width", lambda c: FloatField(c, 0, 50, 0.5, 1, none_text="Default")),
        ):
            path = f"style.{key}"
            self._register(path, lambda layer, k=key: layer.spec.style.get(k))
            rows.append(
                (label, path, make(self._op(path, partial(set_style, key=key), f"Change {label.lower()}")))
            )
        self._section("Style", rows)

    def _transform_section(self, layer: Layer) -> None:
        rows = []
        keyable = keyable_props(layer)  # a graph keeps only its opacity (ADR 0024)
        for name, label, field_type in (
            ("position", "Position", lambda c: PointField(c)),
            ("scale", "Scale", lambda c: FloatField(c, 0.01, 100, 0.05, 3)),
            ("rotation", "Rotation", lambda c: FloatField(c, -3600, 3600, 1, 1, suffix=" deg")),
            ("opacity", "Opacity", lambda c: FloatField(c, 0, 1, 0.05, 2)),
        ):
            if name not in keyable:
                continue
            path = f"base.{name}"
            self._register(path, lambda layer, n=name: self._transform_value(layer, n))
            op = partial(
                set_transform, name=name, at=lambda: self.playhead(), auto_key=lambda: self.auto_key()
            )
            field = field_type(self._op(path, op, f"Change {label.lower()}"))
            key_path = f"keys.{name}"
            self._register(key_path, lambda layer, n=name: bool(layer.tracks.get(n)))
            animate = partial(set_animated, prop=name, at=lambda: self.playhead())
            toggle = BoolField(self._op(key_path, animate, f"Animate {label.lower()}"), "Keys")
            toggle.widget.setToolTip(f"Keyframes for {label.lower()}: on = changes set a key at the playhead")
            rows.append((label, [(path, field), (key_path, toggle)]))
            if name == "position":
                rows.append(self._anchor_row())
        self._section("Transform", rows)

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
                (other.name or other.id, other.id)
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
                choices = [(other.name or other.id, other.id) for other in self.project.path_layers(layer.id)]
                commit = self._op(path, op, f"Change {param.label.lower()}")
                rows.append((param.label, path, ChoiceField(commit, choices)))
                continue
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
        decimals = 0 if param.step >= 1 else 2 if param.step >= 0.05 else 3
        return FloatField(commit, param.minimum or 0.0, param.maximum or 1e4, param.step, decimals)
    if param.kind == "int":
        return IntField(commit, int(param.minimum or 0), int(param.maximum or 1000))
    if param.kind == "choice":
        return ChoiceField(commit, [(c.capitalize(), c) for c in param.choices])
    if param.kind == "point":
        return PointField(commit)
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
