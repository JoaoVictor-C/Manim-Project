"""Properties dock (S2.5): edit the selected layer or clip.

The object section is generated from ``adapter.MOBJECT_PARAMS``; style, the
layer transform, lifetime and clip timing are fixed sections. Each finished
field edit is one operation submitted to the ``BuildService`` (ADR 0015) with
the field as its supersede key, so typing a new equation never freezes the UI
and the field keeps showing what was typed while it builds. Clip params stay
hidden (ADR 0007).
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from functools import partial
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import adapter, edits
from ..core.adapter import Param
from ..core.schema import CLIP_KIND_INFO, RASTER_TYPES, Easing, Layer, Project
from .build_service import BuildService
from .fields import (
    ChoiceField,
    ColorField,
    Field,
    FloatField,
    IntField,
    LongTextField,
    PathField,
    PointField,
    TextField,
)

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


def set_lifetime(project: Project, layer_id: str, key: str, value: float | None) -> edits.Edit:
    if not _has(project, layer_id):
        raise edits.EditError(f"no layer {layer_id!r}")
    lifetime = project.layer(layer_id).lifetime.model_dump(by_alias=True)
    lifetime[key] = value
    return edits.update_layer(project, layer_id, lifetime=lifetime)


def _has(project: Project, layer_id: str) -> bool:
    return any(layer.id == layer_id for layer in project.layers)


# -- the panel ----------------------------------------------------------------------


class PropertiesPanel(QWidget):
    message = Signal(str)

    def __init__(self, builds: BuildService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.builds = builds
        self.document = builds.document
        self.layer_id: str | None = None
        self.clip_id: str | None = None
        self.fields: dict[str, Field] = {}
        self._getters: dict[str, Callable[[Layer], Any]] = {}
        self._keys: dict[str, Hashable] = {}
        self._generation = 0  # bumped on every rebuild: old widgets can no longer commit

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
        self.layer_id = self.clip_id = None
        self._rebuild()
        self.title.setText("Select a layer or a clip.")

    def show_layer(self, layer_id: str) -> None:
        if not layer_id or not _has(self.project, layer_id):
            self.show_nothing()
            return
        self.layer_id, self.clip_id = layer_id, None
        self._rebuild()
        layer = self.project.layer(layer_id)
        self._section(
            "Layer", [("Name", "name", TextField(self._layer_op("name", self._set_name), layer.id))]
        )
        self._object_section(layer)
        if layer.spec.type not in RASTER_TYPES:
            self._style_section()
        self._transform_section(layer)
        self._lifetime_section()
        self.body_layout.addStretch(1)
        self.refresh()

    def show_clip(self, layer_id: str, clip_id: str) -> None:
        if not _has(self.project, layer_id) or self._clip(layer_id, clip_id) is None:
            self.show_nothing()
            return
        self.layer_id, self.clip_id = layer_id, clip_id
        self._rebuild()
        self._clip_section(self.project.layer(layer_id), self._clip(layer_id, clip_id))
        self.body_layout.addStretch(1)
        self.refresh()

    # -- showing values -------------------------------------------------------------

    def refresh(self, force: bool = False) -> None:
        """Show the document's values (or a pending value) in every field not being edited."""
        if self.layer_id is None:
            return
        if not _has(self.project, self.layer_id):
            self.show_nothing()
            return
        layer = self.project.layer(self.layer_id)
        if self.clip_id is not None and self._clip(self.layer_id, self.clip_id) is None:
            self.show_layer(self.layer_id)
            return
        self._update_title(layer)
        for path, field in self.fields.items():
            if field.has_focus() and not force:
                continue
            waiting, value = self.builds.pending_value(self._keys[path])
            field.set_value(value if waiting else self._getters[path](layer), pending=waiting)

    def _update_title(self, layer: Layer) -> None:
        name = layer.name or layer.id
        if self.clip_id is None:
            self.title.setText(f"<b>{name}</b> - {layer.spec.type}")
        else:
            clip = self._clip(layer.id, self.clip_id)
            self.title.setText(f"<b>{clip.kind}</b> clip on {name}")

    # -- sections ---------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._generation += 1
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
        for label, path, field in rows:
            form.addRow(label, field.widget)
            self.fields[path] = field
        self.body_layout.addWidget(box)

    def _register(self, path: str, getter: Callable[[Layer], Any]) -> None:
        self._getters[path] = getter
        self._keys[path] = self._key(path)

    def _key(self, path: str) -> Hashable:
        """The supersede key: one waiting edit per field of this layer or clip."""
        return (self.layer_id, path) if self.clip_id is None else (self.layer_id, self.clip_id, path)

    def _object_section(self, layer: Layer) -> None:
        rows = []
        for param in adapter.MOBJECT_PARAMS.get(layer.spec.type, ()):
            path = f"params.{param.name}"
            self._register(path, lambda layer, p=param: adapter.param_value(layer.spec, p))
            commit = self._op(path, partial(set_param, name=param.name), f"Change {param.title.lower()}")
            rows.append((param.title, path, _param_field(param, commit)))
        self._section(layer.spec.type, rows)

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
        for name, label, field_type in (
            ("position", "Position", lambda c: PointField(c)),
            ("scale", "Scale", lambda c: FloatField(c, 0.01, 100, 0.05, 3)),
            ("rotation", "Rotation", lambda c: FloatField(c, -3600, 3600, 1, 1, suffix=" deg")),
            ("opacity", "Opacity", lambda c: FloatField(c, 0, 1, 0.05, 2)),
        ):
            path = f"base.{name}"
            self._register(path, lambda layer, n=name: getattr(layer.base, n))
            field = field_type(self._op(path, partial(set_base, name=name), f"Change {label.lower()}"))
            if name in layer.tracks:
                field.widget.setEnabled(False)
                field.widget.setToolTip(f"{label} is animated by keyframes")
            rows.append((label, path, field))
        self._section("Transform", rows)

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
            for k in adapter.allowed_clip_kinds(layer.spec.type)
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
            ("ease", "Easing", ChoiceField(commit("ease", "Change easing"), _ease_choices())),
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
        return PathField(commit)
    if param.multiline:
        return LongTextField(commit)
    return TextField(commit, "default" if param.name == "font" else "")


def _ease_choices() -> list[tuple[str, Easing | None]]:
    choices: list[tuple[str, Easing | None]] = [("Animation default", None)]
    choices += [(name.replace("_", " "), Easing(name=name)) for name in adapter.EASE_NAMES]
    choices += [(label, Easing(name=None, bezier=b)) for label, b in adapter.BEZIER_PRESETS.items()]
    return choices


def _first_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return exc.errors()[0]["msg"].removeprefix("Value error, ")
    return str(exc)
