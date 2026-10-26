"""The Values tab of the Code page (P13.7): try a Python object's parameters while reading its code.

One field per parameter its ``PARAMS`` declares (read without running the code), built from the same
field widgets as Properties and committing through the same edit (``set_python_value``), so it is a
second *view* of the same state: a value changed here changes the document once and Properties shows
it, and the other way round. Only values live here; the schema is edited in the code.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ...core.code import python_object
from ...core.engine import adapter
from ...core.model.schema import PYTHON_TYPES, Project
from ..style.fields import Field, Section, caption
from .properties_panel import _first_error, _param_field, set_python_value

NO_OBJECT = "Select a Python object to try its parameters here."
NO_PARAMS = "This Python object has no parameters: add some to PARAMS in its code."
NOT_PYTHON = "A scene has no parameters; only Python objects do."


class ValuesPanel(QScrollArea):
    def __init__(self, builds, message=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.builds = builds
        self.message = message  # a callable taking text, or None
        self.layer_id: str | None = None
        self.fields: dict[str, Field] = {}
        self._shown: tuple | None = None  # the parameters the fields were built for
        self.setWidgetResizable(True)
        self.setObjectName("valuesPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.note = QLabel(NO_OBJECT)
        self.note.setWordWrap(True)
        self.note.setProperty("role", "hint")
        self.note.setContentsMargins(14, 12, 14, 12)
        # Lumen: the parameters are a section of fields that hold their labels inside (number, text) or
        # show them above (a list, a colour), as in Properties.
        self.section = Section("Parameters", collapsible=False)
        self.section.rule = False
        self.form_host = self.section
        self.form = self.section.body_layout
        self.section.hide()
        column.addWidget(self.note)
        column.addWidget(self.section)
        column.addStretch(1)
        self.setWidget(body)

    # -- showing a layer ----------------------------------------------------------------------

    def show_layer(self, project: Project | None, layer_id: str | None) -> None:
        """Show the parameters of ``layer_id`` (a Python object), or say why there are none."""
        self.layer_id = layer_id
        layer = None
        if project is not None and layer_id is not None:
            layer = next((x for x in project.layers if x.id == layer_id), None)
        if layer is None or layer.spec is None:
            self._clear(NO_OBJECT)
            return
        if layer.spec.type not in PYTHON_TYPES:
            self._clear(NOT_PYTHON)
            return
        params = adapter.python_params(layer.spec)
        if not params:
            self._clear(NO_PARAMS)
            return
        key = (layer_id, params)
        if key != self._shown:
            self._build(layer_id, params)
            self._shown = key
        self.note.hide()
        self.refresh(project)

    def refresh(self, project: Project | None) -> None:
        """Put the document's values into the fields that are not being edited."""
        if project is None or self.layer_id is None:
            return
        layer = next((x for x in project.layers if x.id == self.layer_id), None)
        if layer is None or layer.spec is None or layer.spec.type not in PYTHON_TYPES:
            return
        code = str(layer.spec.params.get("code", ""))
        values = python_object.call_values(code, layer.spec.params.get("values") or {})
        for name, field in self.fields.items():
            if name in values and not field.has_focus():
                field.set_value(values[name])

    def has_params(self) -> bool:
        return bool(self.fields)

    # -- building -----------------------------------------------------------------------------

    def _empty(self) -> None:
        while self.form.count():
            item = self.form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _clear(self, text: str) -> None:
        self._shown = None
        self.fields = {}
        self._empty()
        self.section.hide()
        self.note.setText(text)
        self.note.show()

    def _build(self, layer_id: str, params: tuple) -> None:
        self.fields = {}
        self._empty()
        for param in params:
            field = _param_field(param, self._commit(layer_id, param.name))
            self.fields[param.name] = field
            if not field.set_label(param.title):
                row = QWidget()
                column = QVBoxLayout(row)
                column.setContentsMargins(0, 0, 0, 0)
                column.setSpacing(5)
                column.addWidget(caption(param.title))
                column.addWidget(field.widget)
                self.form.addWidget(row)
            else:
                self.form.addWidget(field.widget)
        self.section.show()

    def _commit(self, layer_id: str, name: str):
        def commit(value: Any) -> None:
            if layer_id != self.layer_id:
                return  # a field of the previous layer losing focus
            op = partial(set_python_value, layer_id=layer_id, name=name, value=value)
            try:
                self.builds.submit(op, f"Change {name}", supersede=("values", layer_id, name), value=value)
            except Exception as exc:
                if self.message is not None:
                    self.message(f"Change {name}: {_first_error(exc)}")

        return commit
