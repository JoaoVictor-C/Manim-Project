"""Canvas widget: shows the exact Manim (Cairo) frame at the playhead.

Since S3 it also draws the selection outline over the frame and forwards mouse
and keyboard input to a tool (``canvas_tools.MoveTool``). Since P3a (ADR 0023)
it has a view (``viewport.View``): the frame letterboxed (Fit) or any scale and
centre; the camera is re-framed to cover the whole widget, so what lies outside
the video frame shows, dimmed. Widget pixels map to Manim units (y up) through
``px_per_unit``, ``to_units`` and ``units_transform`` only. Code dragged from the
Code workspace or ``.py`` files from the desktop (P12.7) show a cross where they
would land and are handed to the window with that point in Manim units.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

import manim as m
import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

from ...core.code.code_frame import CodeFrame
from ...core.engine.evaluator import Evaluator
from ...core.model.schema import CONNECTOR_TYPES, Camera, Canvas
from ...render.cairo_export import render_frame
from ...render.preview import PreviewView, preview_camera, set_preview_centre
from ...render.qt_paths import vmobject_path
from ..session import code_drag
from ..style import theme
from ..style.render_activity import spinner
from . import motion_overlay, param_handles, viewport
from .gizmo import GRAB_PX, HANDLE_PX, KNOB_OFFSET_PX, MIN_BOX_PX, Box, affine_box

OUTLINE_COLOR = theme.qcolor(theme.THEME.outline)
MOTION_COLOR = theme.qcolor(theme.THEME.motion_path)  # the motion path (ADR 0026)
KEY_PX = 7.0  # a key's square on the motion path
PASTEBOARD_DIM = theme.qcolor(theme.THEME.pasteboard_dim)  # over what lies outside the video frame
FRAME_BORDER = theme.qcolor(theme.THEME.frame_border)
DRAFT_ABOVE_MS = 60.0  # a render slower than this, again and again, is a heavy edit (ADR 0070)
DRAFT_BURST_S = 0.3  # renders closer than this belong to one interaction
DRAFT_SETTLE_MS = 350  # without a render for this long the interaction is over: full quality again
DRAFT_SCALE = 0.5
DRAFT_LABEL = "DRAFT"
BADGE = theme.qcolor(theme.THEME.badge)  # handle squares, key squares
BADGE_TEXT = theme.qcolor(theme.THEME.badge_text)
GUIDE_COLOR = theme.qcolor(theme.THEME.guide)  # snapping guides (ADR 0043)
DROP_COLOR = theme.qcolor(theme.THEME.accent)  # where dragged code would land (P12.7)
DOT_GAP = 18  # the dotted pasteboard (Lumen, ADR 0063)
SHADOW_PX = 22  # how far the frame's shadow reaches


_colours_for = theme.THEME.name


def refresh_colours() -> None:
    """Read the overlay colours from the current theme again (the paint code reads these module names, so
    switching Ink and Paper restyles the handles and guides without rebuilding the canvas)."""
    global _colours_for
    c = theme.THEME
    _colours_for = c.name
    g = globals()
    g["OUTLINE_COLOR"] = theme.qcolor(c.outline)
    g["MOTION_COLOR"] = theme.qcolor(c.motion_path)
    g["PASTEBOARD_DIM"] = theme.qcolor(c.pasteboard_dim)
    g["FRAME_BORDER"] = theme.qcolor(c.frame_border)
    g["BADGE"] = theme.qcolor(c.badge)
    g["BADGE_TEXT"] = theme.qcolor(c.badge_text)
    g["GUIDE_COLOR"] = theme.qcolor(c.guide)
    g["DROP_COLOR"] = theme.qcolor(c.accent)


theme.signals.themeChanged.connect(lambda _name: refresh_colours())
DROP_PX = 10.0  # the drop cross's arm
PARAM_HANDLE_PX = 9.0  # parameter handles: round, drawn size (ADR 0043)
CLEAR_OF_MIDDLE_PX = 14.0  # parameter handles nearer an object's middle or pivot than this are hidden
WHEEL_PAN_PX = 48.0  # one wheel notch
TURNED_NOTICE = "Camera turned: no handles or clicking objects here. Reset it in Properties > Camera."


@dataclass
class Outline:
    """The selected layer as drawn at the current time, in Manim units."""

    path: QPainterPath
    bounds: QRectF
    anchor: tuple[float, float]
    box: Box  # oriented: the frame the handles live in (P2a)
    snaps: np.ndarray  # where the pivot cross snaps: the unpadded box's corners, edge midpoints, centre (P2f)


class CanvasWidget(QWidget):
    """Letterboxed view of the Manim frame at the current time."""

    _decor_key: tuple | None = None  # what the cached pasteboard decoration was drawn for

    resized = Signal()
    view_changed = Signal()  # zoom or pan: the window renders again and updates the readout
    addRequested = Signal(str, float, float)  # text/shape tool: kind and scene position in units
    codeDropped = Signal(dict, float, float)  # a Code workspace drag (code_drag payload), x, y in units
    filesDropped = Signal(list, float, float)  # .py files dropped from the desktop, x, y in units

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 270 + the Stage's tool rail (44 px) and its gap (6) = the old 320 px stage minimum
        self.setMinimumSize(270, 180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)  # code from the Code workspace, .py files (P12.7)
        self.drop_point: QPointF | None = None  # where dragged code would land, widget pixels
        self._canvas: Canvas | None = None
        self._evaluator: Evaluator | None = None
        self._camera: m.Camera | None = None
        self._camera_view: PreviewView | None = None
        self._camera_angles: Camera | None = None  # the project camera self._camera was built for
        self._image: QImage | None = None
        self.half_resolution = False
        self.draft_enabled = True  # heavy edits are drawn small, then again in full (ADR 0070)
        self.draft = False
        self._last_render_at = 0.0
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(DRAFT_SETTLE_MS)
        self._settle.timeout.connect(self._leave_draft)
        self.last_render_ms = 0.0
        self._t = 0.0  # the time last drawn (F frames the selection as it is then)
        self.selected_layer: str | None = None  # whose outline to draw
        self.busy_text = ""  # what code is rendering, as a badge on the picture (ADR 0059)
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(100)
        self._busy_timer.timeout.connect(self.update)
        self.show_overlays = True  # outlines, handles and motion paths; off on the Code page (P12)
        self.show_edit_handles = True  # point and independent-width handles; corners stay available
        self.select_by_bounds = True  # let object bounds count as canvas hits (View toggle)
        self.presenting = False  # full screen: what lies outside the frame is black, no border (P12)
        self.other_layers: tuple[str, ...] = ()  # also selected (ADR 0043): outlined, no handles
        self.other_outlines: list[tuple[str, QPainterPath]] = []  # theirs, in Manim units
        self.marquee: tuple[np.ndarray, np.ndarray] | None = None  # a selection rectangle being drawn
        self.outline: Outline | None = None
        self.readout: tuple[QPointF, str] | None = None  # a value shown next to the cursor while dragging
        self.tool = None  # receives mouse/key input (canvas_tools.MoveTool)
        self.interaction_mode = "select"  # select, hand, anchor, text, or shape (Stage tool rail)
        self.view = viewport.View()  # editor state, remembered per project in Preferences (ADR 0023)
        self.view_locked = False  # stop accidental pan and zoom gestures on the stage
        self.motion: motion_overlay.MotionPath | None = None  # the selected layer's path (ADR 0026)
        self.playing = False  # the motion path hides while playing
        self.render_ahead = None  # frames rendered ahead (ui.render_ahead.RenderAhead, ADR 0028)
        self.from_cache = False  # the frame shown came from it
        self._pan_from: QPointF | None = None  # middle-drag in progress
        self.param_handles: list[param_handles.ParamHandle] = []  # the selected object's sizes (ADR 0043)
        self.guides: list[tuple[tuple[float, float], tuple[float, float]]] = []  # snapped edges, units
        self._rest: dict[str, np.ndarray] = {}  # built drawings' points by spec, for the handles
        self._rest_origin: dict[str, np.ndarray] = {}  # their pre-centre origins in parameter space

    @property
    def evaluator(self) -> Evaluator | None:
        return self._evaluator

    def set_scene(self, canvas: Canvas, evaluator: Evaluator) -> None:
        self._canvas, self._evaluator = canvas, evaluator
        self._camera = None
        self.view = viewport.View()  # a project opens at Fit

    def set_canvas(self, canvas: Canvas) -> None:
        """The same picture with other settings that do not move it (its length)."""
        self._canvas = canvas

    # -- geometry ----------------------------------------------------------------

    def geometry_now(self) -> viewport.ViewGeometry:
        assert self._canvas is not None
        return viewport.geometry(self.view, self._canvas, self.width(), self.height())

    def px_per_unit(self) -> float:
        return self.geometry_now().ppu

    def to_units(self, pos: QPointF) -> np.ndarray:
        """A widget position in Manim units."""
        return viewport.to_world(self.geometry_now(), self.width(), self.height(), pos.x(), pos.y())

    def units_transform(self) -> QTransform:
        """Manim units -> widget pixels."""
        geo = self.geometry_now()
        cx, cy = geo.centre
        return QTransform(
            geo.ppu, 0, 0, -geo.ppu, self.width() / 2 - geo.ppu * cx, self.height() / 2 + geo.ppu * cy
        )

    def frame_rect(self) -> QRectF:
        """Where the video frame lies, in widget pixels (it may extend past the widget)."""
        half_w, half_h = self._canvas.frame_width / 2, self._canvas.frame_height / 2
        return self.units_transform().mapRect(QRectF(-half_w, -half_h, 2 * half_w, 2 * half_h))

    def zoom_label(self) -> str:
        return viewport.label(self.view, self.geometry_now()) if self._canvas is not None else ""

    # -- view (ADR 0023) ---------------------------------------------------------

    def set_view(self, view: viewport.View) -> None:
        if view != self.view:
            self.view = view
            self.view_changed.emit()

    def set_view_locked(self, locked: bool) -> None:
        """Ignore stage navigation until the user unlocks the canvas view."""
        self.view_locked = bool(locked)
        if self.view_locked:
            self._pan_from = None

    def set_interaction_mode(self, mode: str) -> None:
        if mode not in {"select", "hand", "anchor", "text", "shape"}:
            raise ValueError(f"unknown Stage tool {mode!r}")
        if self.interaction_mode != mode:
            self.interaction_mode = mode
            self._pan_from = None
            self.unsetCursor()
            if mode == "hand":
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif mode == "anchor" or mode in {"text", "shape"}:
                self.setCursor(Qt.CursorShape.CrossCursor)

    def zoom(self, factor: float, pos: QPointF | None = None) -> None:
        """Zoom about a widget position (default: the centre)."""
        if self.view_locked or self._canvas is None or self._dragging():
            return
        pos = pos if pos is not None else QPointF(self.width() / 2, self.height() / 2)
        self.set_view(
            viewport.zoom_about(
                self.view, self._canvas, self.width(), self.height(), factor, pos.x(), pos.y()
            )
        )

    def pan(self, dx: float, dy: float) -> None:
        if self.view_locked or self._canvas is None or self._dragging():
            return
        self.set_view(viewport.pan(self.view, self._canvas, self.width(), self.height(), dx, dy))

    def fit(self) -> None:
        if self.view_locked:
            return
        self.set_view(viewport.View())

    def frame_selection(self) -> None:
        """Show the selected objects as large as fit (Unity's F); with nothing selected, Fit."""
        if self.view_locked or self._canvas is None or self._evaluator is None:
            return
        if self.camera_turned:  # flat bounds would frame the wrong place (ADR 0048)
            self.fit()
            return
        ids = [self.selected_layer, *self.other_layers] if self.selected_layer else []
        points = []
        for layer_id in dict.fromkeys(i for i in ids if i):
            if not any(layer.id == layer_id for layer in self._evaluator.project.layers):
                continue
            for _, mob in self._evaluator.object_frame(layer_id, self._t):
                points += [sub.points[:, :2] for sub in mob.family_members_with_points()]
        if not points:
            self.fit()
            return
        box = np.concatenate(points)
        low, high = box.min(axis=0), box.max(axis=0)
        self.set_view(
            viewport.frame_box(
                self._canvas,
                self.width(),
                self.height(),
                (float(low[0]), float(low[1])),
                (float(high[0]), float(high[1])),
            )
        )

    def actual_size(self) -> None:
        if not self.view_locked and self._canvas is not None:
            self.set_view(viewport.at_scale(self.view, self._canvas, self.width(), self.height(), 1.0))

    def _dragging(self) -> bool:
        """A tool gesture is in progress: the view waits (the dragged object would jump)."""
        return self.tool is not None and getattr(self.tool, "_drag", None) is not None

    # -- rendering ---------------------------------------------------------------

    def render_at(self, t: float) -> None:
        if self._canvas is None or self._evaluator is None:
            return
        self._t = t
        view = self.preview_view()
        seen_from = self._evaluator.project.camera  # the project's camera (ADR 0048)
        if (
            self._camera is None
            or replace(view, centre=(0, 0)) != replace(self._camera_view, centre=(0, 0))
            or seen_from != self._camera_angles
        ):
            self._camera = preview_camera(view, seen_from)
            self._camera_angles = seen_from
        elif view.centre != self._camera_view.centre:  # a pan: same camera, moved
            set_preview_centre(self._camera, view.centre)
        self._camera_view = view
        if self.camera_turned:  # outlines and handles are flat: they would be drawn in the wrong place
            self._render_turned(t, view)
            return
        start = time.perf_counter()
        cached = None
        if self.render_ahead is not None:
            self.render_ahead.set_view(view)
            cached = self.render_ahead.image(t)
        self.from_cache = cached is not None
        if cached is not None:  # rendered ahead (ADR 0028): only the selected object is evaluated
            self._image = cached
            self.outline = self._outline(self._selected_object(t), t)
            self.other_outlines = [
                (layer_id, self._path_of(layer_id, self._evaluator.object_frame(layer_id, t)))
                for layer_id in self._others()
            ]
        else:
            try:
                layers = self._evaluator.frame_layers(t)
                overlay = self._evaluator.overlay(t)  # subtitles, never hit-tested (ADR 0035)
                pixels = render_frame(self._camera, [mob for _, mob in layers], overlay)
            except Exception:
                # Never the last picture stretched to a new size: it looked like a squashed
                # scene with stale objects (the user's report). The exception is reported.
                self._image = self.outline = None
                self.other_outlines = []
                self.update()
                raise
            self.outline = self._outline(layers, t)  # built now: the mobjects are shared buffers
            self.other_outlines = [(i, self._path_of(i, layers)) for i in self._others()]
            height, width = pixels.shape[:2]
            self._image = QImage(pixels.data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        self.motion = self._motion(t)
        self.param_handles = self._param_handles(t)
        if not self.show_overlays:  # a plain view: nothing over the picture, nothing to grab
            self.outline, self.other_outlines, self.motion, self.param_handles = None, [], None, []
        self.last_render_ms = (time.perf_counter() - start) * 1000
        self._note_render(self.last_render_ms)
        self.update()

    def _note_render(self, ms: float) -> None:
        """Draft preview (ADR 0070): slow renders in a burst - a drag, a scrub, a heavy scene playing - are
        drawn at half size and marked, and the first quiet moment draws the frame in full again."""
        now = time.monotonic()
        burst = now - self._last_render_at < DRAFT_BURST_S
        self._last_render_at = now
        if not self.draft_enabled or self.half_resolution or self.from_cache:
            return
        if not self.draft and burst and ms > DRAFT_ABOVE_MS:
            self.draft = True
        if self.draft:
            self._settle.start()

    def _leave_draft(self) -> None:
        if not self.draft:
            return
        self.draft = False
        if self._evaluator is not None and self._canvas is not None:
            self.render_at(self._t)
        else:
            self.update()

    def set_draft_enabled(self, enabled: bool) -> None:
        self.draft_enabled = enabled
        if not enabled:
            self._settle.stop()
            self._leave_draft()

    def set_overlays(self, shown: bool) -> None:
        """Draw the selection outline, handles and motion path (the default), or only the picture."""
        if shown == self.show_overlays:
            return
        self.show_overlays = shown
        if self._evaluator is not None and self._canvas is not None:
            self.render_at(self._t)
        else:
            self.update()

    def set_edit_handles(self, shown: bool) -> None:
        """Show geometry-point and independent width/height handles on the selected object."""
        if shown == self.show_edit_handles:
            return
        self.show_edit_handles = shown
        if self._evaluator is not None and self._canvas is not None:
            self.render_at(self._t)
        else:
            self.update()

    def set_select_by_bounds(self, enabled: bool) -> None:
        """Let clicks inside an object's bounds select it, even away from visible geometry."""
        self.select_by_bounds = enabled

    @property
    def camera_turned(self) -> bool:
        """The project's camera is not the flat 2D view (ADR 0048): the picture is seen from an angle,
        so outlines, handles and clicking objects (all in flat scene units) are off until it is reset."""
        return self._evaluator is not None and not self._evaluator.project.camera.is_default

    def _render_turned(self, t: float, view: PreviewView) -> None:
        """The frame seen by a turned camera, with no outline, handle or motion path over it."""
        start = time.perf_counter()
        self.outline, self.other_outlines, self.motion, self.param_handles = None, [], None, []
        cached = None
        if self.render_ahead is not None:
            self.render_ahead.set_view(view)
            cached = self.render_ahead.image(t)
        self.from_cache = cached is not None
        if cached is not None:
            self._image = cached
        else:
            try:
                layers = [mob for _, mob in self._evaluator.frame_layers(t)]
                pixels = render_frame(self._camera, layers, self._evaluator.overlay(t))
            except Exception:
                self._image = None
                self.update()
                raise
            height, width = pixels.shape[:2]
            self._image = QImage(pixels.data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        self.last_render_ms = (time.perf_counter() - start) * 1000
        self.update()

    def _selected_object(self, t: float) -> list[tuple[str, m.Mobject]]:
        project = self._evaluator.project
        if not self.selected_layer or not any(layer.id == self.selected_layer for layer in project.layers):
            return []
        return self._evaluator.object_frame(self.selected_layer, t)

    def preview_view(self) -> PreviewView:
        """How the frame is framed now (ADR 0028): the camera covers the whole widget."""
        geo = self.geometry_now()
        scale = self.devicePixelRatioF() * (DRAFT_SCALE if self.half_resolution or self.draft else 1.0)
        return PreviewView(
            pixel_width=max(2, int(self.width() * scale)),
            pixel_height=max(2, int(self.height() * scale)),
            frame_width=self.width() / geo.ppu,
            frame_height=self.height() / geo.ppu,
            centre=(float(geo.centre[0]), float(geo.centre[1])),
            background=self._canvas.background,
        )

    def _motion(self, t: float) -> motion_overlay.MotionPath | None:
        if self.playing or not self.selected_layer or self._evaluator is None or self.other_layers:
            return None
        project = self._evaluator.project
        if not any(layer.id == self.selected_layer for layer in project.layers):
            return None
        layer = project.layer(self.selected_layer)
        return motion_overlay.build(layer, *self._evaluator.position_frame(layer, t))

    def _param_handles(self, t: float) -> list[param_handles.ParamHandle]:
        """The selected object's editable handles at ``t`` (none while playing)."""
        if (
            not self.show_edit_handles
            or self.playing
            or self.outline is None
            or not self.selected_layer
            or self._evaluator is None
        ):
            return []
        if self.other_layers:  # several objects: they move together, no sizes (ADR 0043)
            return []
        project = self._evaluator.project
        layer = next((x for x in project.layers if x.id == self.selected_layer), None)
        if layer is None or layer.is_part or layer.spec is None:
            return []
        if layer.is_group or not param_handles.supports_object_handles(layer.spec):
            return []
        if layer.spec.type in CONNECTOR_TYPES:
            found = param_handles.connector_handles(layer.spec, self._evaluator.connector_frames(layer, t))
        else:
            built = self._evaluator.built(layer.spec)
            if not isinstance(built, m.Mobject):  # an untrusted or invalid Python object has no handles yet
                return []
            a, b = self._evaluator.world_affine(layer, t)
            found = param_handles.object_handles(
                layer.spec, self.rest_points(layer.spec), self.rest_origin(layer.spec), a, b, built
            )
        clear_of_resize = 12.0 / self.px_per_unit()
        mids = np.array(
            [
                (self.outline.box.corners[0] + self.outline.box.corners[1]) / 2,
                (self.outline.box.corners[1] + self.outline.box.corners[2]) / 2,
                (self.outline.box.corners[2] + self.outline.box.corners[3]) / 2,
                (self.outline.box.corners[3] + self.outline.box.corners[0]) / 2,
            ]
        )
        transform_handles = np.vstack([self.outline.box.corners, mids])
        point_gap = 14.0 / self.px_per_unit()
        point_collision = 2 * GRAB_PX / self.px_per_unit()
        adjusted = []
        for handle in found:
            if not handle.point_control and handle.mode != "point":
                reach = max(float(np.linalg.norm(handle.a @ handle.axis)), 1e-9)
                offset = handle.axis * clear_of_resize / reach
                adjusted.append(replace(handle, display_offset=tuple(offset)))
                continue
            if (handle.point_control or handle.mode == "point") and min(
                np.linalg.norm(transform_handles - handle.world, axis=1)
            ) < point_collision:
                toward = handle.to_local(self.outline.box.centre) - handle.local
                reach = float(np.linalg.norm(handle.a @ toward))
                offset = toward * min(1.0, point_gap / max(reach, 1e-9))
                adjusted.append(replace(handle, display_offset=tuple(offset)))
                continue
            adjusted.append(handle)
        found = adjusted
        if layer.spec.type in CONNECTOR_TYPES:
            return found
        # On a small object the handles would cover its middle, where a press moves it: zoom in.
        clear = CLEAR_OF_MIDDLE_PX / self.px_per_unit()
        middles = (np.asarray(self.outline.anchor), self.outline.box.centre)
        return [
            h for h in found if h.point_control or min(np.linalg.norm(h.world - c) for c in middles) >= clear
        ]

    def rest_points(self, spec) -> np.ndarray:
        """The points of ``spec``'s drawing as built (centred on the origin), kept per spec."""
        key = spec.model_dump_json()
        if key not in self._rest:
            if len(self._rest) > 32:
                self._rest.clear()
                self._rest_origin.clear()
            built = self._evaluator.built(spec)
            if not isinstance(built, m.Mobject):
                self._rest[key] = np.zeros((0, 2))
                self._rest_origin[key] = np.zeros(2)
                return self._rest[key]
            family = built.family_members_with_points()
            self._rest[key] = (
                np.concatenate([sub.points[:, :2] for sub in family]) if family else np.zeros((0, 2))
            )
            self._rest_origin[key] = np.asarray(getattr(built, "_studio_origin", (0.0, 0.0)), float)[:2]
        return self._rest[key]

    def rest_origin(self, spec) -> np.ndarray:
        """The built object's centre before the adapter moved it to the origin."""
        self.rest_points(spec)
        return self._rest_origin.get(spec.model_dump_json(), np.zeros(2))

    def _others(self) -> list[str]:
        """The other selected layers that still exist."""
        present = {layer.id for layer in self._evaluator.project.layers}
        return [i for i in self.other_layers if i in present and i != self.selected_layer]

    def _path_of(self, layer_id: str, layers: list[tuple[str, m.Mobject]]) -> QPainterPath:
        """The drawing of ``layer_id`` with its parts and child objects, in Manim units."""
        project = self._evaluator.project
        members = {layer_id} | {d.id for d in project.descendants(layer_id)}
        path = QPainterPath()
        for owner, mob in layers:
            if owner not in members:
                continue
            if isinstance(mob, (m.ImageMobject, CodeFrame)):
                path.addPolygon(QPolygonF([QPointF(*mob.points[i, :2]) for i in (0, 1, 3, 2, 0)]))
                continue
            for sub in mob.family_members_with_points():
                if isinstance(sub, m.VMobject):
                    path.addPath(vmobject_path(sub))
        return path

    def _outline(self, layers: list[tuple[str, m.Mobject]], t: float) -> Outline | None:
        if not self.selected_layer:
            return None
        project = self._evaluator.project
        if not any(layer.id == self.selected_layer for layer in project.layers):
            return None
        # An object with parts is drawn as several mobjects: outline all of them (ADR 0012).
        members = {self.selected_layer} | {d.id for d in project.descendants(self.selected_layer)}
        drawn = [mob for layer_id, mob in layers if layer_id in members]
        if not drawn:
            return None
        mob = drawn[0] if len(drawn) == 1 else m.Group(*drawn)
        path = QPainterPath()
        if isinstance(mob, (m.ImageMobject, CodeFrame)):  # a rectangle: UL, UR, DL, DR
            points = mob.points[:4, :2].copy()
            ul, ur, dl, dr = (QPointF(*points[i]) for i in range(4))
            path.moveTo(ul)
            for corner in (ur, dr, dl):
                path.lineTo(corner)
            path.closeSubpath()
        else:
            family = [sub for sub in mob.family_members_with_points() if isinstance(sub, m.VMobject)]
            for sub in family:
                path.addPath(vmobject_path(sub))
            points = np.concatenate([sub.points[:, :2] for sub in family]) if family else np.zeros((1, 2))
        layer = project.layer(self.selected_layer)
        pivot, _rotation, _ = self._evaluator.layer_frame(layer, t)
        anchor = (float(pivot[0]), float(pivot[1]))
        a, b = self._evaluator.world_affine(layer, t)
        box = affine_box(points, anchor, a, b, MIN_BOX_PX / self.px_per_unit())
        snaps = box.snap_points()  # a line snaps to its ends, not beside them
        return Outline(path, path.boundingRect(), anchor, box, snaps)

    def paintEvent(self, event) -> None:
        if _colours_for != theme.THEME.name:  # the theme was applied without a change signal (at start)
            refresh_colours()
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.qcolor(theme.THEME.window))
        if self._image is not None and self._canvas is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(QRectF(self.rect()), self._image)
            self._paint_pasteboard(painter)
            if self.motion is not None:
                self._paint_motion(painter)
            if self.outline is not None:
                self._paint_outline(painter)
            if self.other_outlines:
                self._paint_others(painter)
            if self.marquee is not None:
                self._paint_marquee(painter)
            if self.guides:
                self._paint_guides(painter)
            if self.readout is not None:
                pos, text = self.readout
                painter.setPen(BADGE_TEXT)
                painter.drawText(pos + QPointF(14, -10), text)
            if self.camera_turned:
                self._paint_turned_notice(painter)
            if self.draft:
                self._paint_draft(painter)
            if self.busy_text:
                self._paint_busy(painter)
        if self.drop_point is not None:
            self._paint_drop(painter)
        painter.end()

    def _paint_drop(self, painter: QPainter) -> None:
        """A cross and a ring where dragged code would land (P12.7)."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(DROP_COLOR, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        x, y = self.drop_point.x(), self.drop_point.y()
        painter.drawLine(QPointF(x - DROP_PX, y), QPointF(x + DROP_PX, y))
        painter.drawLine(QPointF(x, y - DROP_PX), QPointF(x, y + DROP_PX))
        painter.drawEllipse(self.drop_point, DROP_PX / 2, DROP_PX / 2)
        painter.restore()

    def set_busy(self, text: str) -> None:
        """Show (or clear, with '') the badge that says code is rendering behind the picture."""
        if text == self.busy_text:
            return
        self.busy_text = text
        self._busy_timer.start() if text else self._busy_timer.stop()
        self.update()

    def _paint_busy(self, painter: QPainter) -> None:
        """A spinner and a line at the top right: a code layer is still rendering (ADR 0059)."""
        painter.save()
        metrics = painter.fontMetrics()
        text = metrics.elidedText(
            f"{spinner()}  {self.busy_text}", Qt.TextElideMode.ElideRight, max(40, self.width() - 36)
        )
        width = metrics.horizontalAdvance(text) + 20
        box = QRectF(self.width() - width - 8, 8, width, metrics.height() + 10)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BADGE)
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(DROP_COLOR)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _paint_draft(self, painter: QPainter) -> None:
        """The frame is a draft, drawn small while the edit goes on (ADR 0070)."""
        painter.save()
        metrics = painter.fontMetrics()
        top = 8 + (metrics.height() + 12 if self.camera_turned else 0)
        box = QRectF(8, top, metrics.horizontalAdvance(DRAFT_LABEL) + 16, metrics.height() + 8)
        painter.fillRect(box, BADGE)
        painter.setPen(BADGE_TEXT)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, DRAFT_LABEL)
        painter.restore()

    def _paint_turned_notice(self, painter: QPainter) -> None:
        """Why there are no handles: the camera is turned (ADR 0048)."""
        painter.save()
        metrics = painter.fontMetrics()
        box = QRectF(8, 8, metrics.horizontalAdvance(TURNED_NOTICE) + 16, metrics.height() + 8)
        painter.fillRect(box, BADGE)
        painter.setPen(BADGE_TEXT)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, TURNED_NOTICE)
        painter.restore()

    def _paint_others(self, painter: QPainter) -> None:
        """The other selected objects: their outline and box, no handles (ADR 0043)."""
        to_px = self.units_transform()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(OUTLINE_COLOR, 1.5)
        pen.setCosmetic(True)
        dashed = QPen(OUTLINE_COLOR, 1, Qt.PenStyle.DashLine)
        dashed.setCosmetic(True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for _layer_id, path in self.other_outlines:
            mapped = to_px.map(path)
            painter.setPen(pen)
            painter.drawPath(mapped)
            painter.setPen(dashed)
            painter.drawRect(mapped.boundingRect())
        painter.restore()

    def _paint_marquee(self, painter: QPainter) -> None:
        """The selection rectangle being drawn from empty canvas (ADR 0043)."""
        to_px = self.units_transform()
        start, end = (to_px.map(QPointF(float(p[0]), float(p[1]))) for p in self.marquee)
        painter.save()
        fill = QColor(OUTLINE_COLOR)
        fill.setAlpha(40)
        pen = QPen(OUTLINE_COLOR, 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawRect(QRectF(start, end).normalized())
        painter.restore()

    def _paint_guides(self, painter: QPainter) -> None:
        """Where a dragged edge or centre snapped (ADR 0043)."""
        to_px = self.units_transform()
        painter.save()
        pen = QPen(GUIDE_COLOR, 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for start, end in self.guides:
            painter.drawLine(to_px.map(QPointF(*start)), to_px.map(QPointF(*end)))
        painter.restore()

    def _paint_pasteboard(self, painter: QPainter) -> None:
        """Dim what lies outside the video frame (four bands) and draw the frame's border."""
        frame, widget = self.frame_rect(), QRectF(self.rect())
        top, bottom = max(frame.top(), widget.top()), min(frame.bottom(), widget.bottom())
        for band in (
            QRectF(widget.left(), widget.top(), widget.width(), top - widget.top()),
            QRectF(widget.left(), bottom, widget.width(), widget.bottom() - bottom),
            QRectF(widget.left(), top, frame.left() - widget.left(), bottom - top),
            QRectF(frame.right(), top, widget.right() - frame.right(), bottom - top),
        ):
            if band.width() > 0 and band.height() > 0:
                painter.fillRect(band, Qt.GlobalColor.black if self.presenting else PASTEBOARD_DIM)
        if self.presenting:
            return
        self._paint_pasteboard_dots(painter, frame, widget)
        pen = QPen(FRAME_BORDER, 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Half a pixel inside, so a frame exactly as wide or tall as the widget (Fit) keeps
        # its border on the far edges too: a 1 px line at x = width lies outside (P6d.4).
        painter.drawRect(frame.adjusted(0.5, 0.5, -0.5, -0.5))

    def _paint_pasteboard_dots(self, painter: QPainter, frame: QRectF, widget: QRectF) -> None:
        """A faint dot grid on the pasteboard and a soft shadow under the frame (Lumen, ADR 0063), drawn once
        into a pixmap and reused until the size, the frame or the theme changes."""
        key = (
            self.width(),
            self.height(),
            frame.toRect().getRect(),
            theme.THEME.name,
            self.devicePixelRatioF(),
        )
        if self._decor_key != key:
            self._decor_key = key
            self._decor = self._decoration(frame, widget)
        painter.drawPixmap(0, 0, self._decor)

    def _decoration(self, frame: QRectF, widget: QRectF) -> QPixmap:
        c = theme.THEME
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap((widget.size() * ratio).toSize())
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outside = QPainterPath()
        outside.addRect(widget)
        inside = QPainterPath()
        inside.addRect(frame)
        painter.setClipPath(outside.subtracted(inside))
        shadow = theme.qcolor(c.shadow)
        shadow.setAlpha(max(1, int(shadow.alpha() * 0.07)))
        for i in range(SHADOW_PX, 0, -2):  # overlapping rings: darkest next to the frame
            ring = QPainterPath()
            box = frame.adjusted(-i, -i + 6, i, i + 6)
            ring.addRoundedRect(box, i, i)
            painter.fillPath(ring, shadow)
        dot = theme.qcolor(c.line_strong)
        dot.setAlpha(110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        y = DOT_GAP / 2
        while y < widget.bottom():
            x = DOT_GAP / 2
            while x < widget.right():
                if not frame.contains(x, y):
                    painter.drawRect(QRectF(x - 0.5, y - 0.5, 1.2, 1.2))
                x += DOT_GAP
            y += DOT_GAP
        painter.end()
        return pixmap

    def _paint_motion(self, painter: QPainter) -> None:
        """The motion path: dashed through the keys, a square per key, its tangent handles."""
        to_px = self.units_transform()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dashed = QPen(MOTION_COLOR, 1, Qt.PenStyle.DashLine)
        dashed.setCosmetic(True)
        painter.setPen(dashed)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF([to_px.map(QPointF(*p)) for p in self.motion.polyline]))
        solid = QPen(MOTION_COLOR, 1)
        solid.setCosmetic(True)
        painter.setPen(solid)
        half = KEY_PX / 2
        for key in self.motion.keys:
            centre = to_px.map(QPointF(*key.point))
            for handle in (key.in_handle, key.out_handle):
                if handle is not None:
                    end = to_px.map(QPointF(*handle))
                    painter.drawLine(centre, end)
                    painter.setBrush(MOTION_COLOR)
                    painter.drawEllipse(end, 3.0, 3.0)
            painter.setBrush(BADGE)
            painter.drawRect(QRectF(centre.x() - half, centre.y() - half, KEY_PX, KEY_PX))
        painter.restore()

    def _paint_outline(self, painter: QPainter) -> None:
        to_px = self.units_transform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(QRectF(self.rect()))
        pen = QPen(OUTLINE_COLOR, 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(to_px.map(self.outline.path))
        dashed = QPen(OUTLINE_COLOR, 1, Qt.PenStyle.DashLine)
        dashed.setCosmetic(True)
        painter.setPen(dashed)
        box = self.outline.box
        corners = [to_px.map(QPointF(*c)) for c in box.corners]
        painter.drawPolygon(QPolygonF(corners))
        if self.other_outlines:  # several objects selected: they move together (ADR 0043)
            return
        cx, cy = to_px.map(QPointF(*self.outline.anchor)).toTuple()
        painter.setPen(pen)
        painter.drawLine(QPointF(cx - 6, cy), QPointF(cx + 6, cy))
        painter.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy + 6))
        painter.drawEllipse(QPointF(cx, cy), 3.0, 3.0)  # the pivot: drag it to move the anchor (P2f)
        # handles: corner squares scale, the knob rotates (P2a)
        painter.setBrush(BADGE)
        half = HANDLE_PX / 2
        for corner in corners:
            painter.drawRect(QRectF(corner.x() - half, corner.y() - half, HANDLE_PX, HANDLE_PX))
        layer = next(
            (item for item in self._evaluator.project.layers if item.id == self.selected_layer), None
        )
        if self.show_edit_handles and layer is not None and not layer.is_group:
            mids = [
                (box.corners[0] + box.corners[1]) / 2,
                (box.corners[1] + box.corners[2]) / 2,
                (box.corners[2] + box.corners[3]) / 2,
                (box.corners[3] + box.corners[0]) / 2,
            ]
            for midpoint in mids:
                centre = to_px.map(QPointF(*midpoint))
                painter.drawRect(QRectF(centre.x() - half, centre.y() - half, HANDLE_PX, HANDLE_PX))
        knob = to_px.map(QPointF(*box.knob(KNOB_OFFSET_PX / self.px_per_unit())))
        top_middle = (corners[2] + corners[3]) / 2
        painter.drawLine(top_middle, knob)
        painter.drawEllipse(knob, half, half)
        # parameter handles: round, filled with the outline colour (ADR 0043)
        if self.show_edit_handles:
            painter.setBrush(OUTLINE_COLOR)
            painter.setPen(QPen(BADGE, 1.5))
            radius = PARAM_HANDLE_PX / 2
            for handle in self.param_handles:
                if handle.mode == "point" and handle.display_offset is not None:
                    start = handle.a @ handle.local + handle.b
                    painter.setPen(QPen(OUTLINE_COLOR, 1.0))
                    painter.drawLine(to_px.map(QPointF(*start)), to_px.map(QPointF(*handle.world)))
                    painter.setPen(QPen(BADGE, 1.5))
                painter.drawEllipse(to_px.map(QPointF(*handle.world)), radius, radius)

    # -- input: forwarded to the tool ---------------------------------------------

    def event(self, event) -> bool:
        override = event.type() == QEvent.Type.ShortcutOverride
        if override and self.tool is not None and self.tool.wants_key(event):
            event.accept()  # arrow keys nudge the selection instead of stepping frames
            return True
        return super().event(event)

    def wheelEvent(self, event) -> None:
        """Ctrl+wheel zooms about the cursor; wheel pans (Shift: sideways) - ADR 0023."""
        if self._canvas is None:
            super().wheelEvent(event)
            return
        if self.view_locked:
            event.accept()
            return
        pixel_delta = event.pixelDelta()
        if not pixel_delta.isNull():  # smooth scrolling devices report pixels instead of wheel notches
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                distance = pixel_delta.y() or pixel_delta.x()
                self.zoom(viewport.ZOOM_STEP ** (distance / WHEEL_PAN_PX), event.position())
            elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                distance = pixel_delta.y() or pixel_delta.x()
                self.pan(float(distance), 0.0)
            else:
                self.pan(float(pixel_delta.x()), float(pixel_delta.y()))
        else:
            delta = event.angleDelta()
            notches = (delta.y() or delta.x()) / 120
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.zoom(viewport.ZOOM_STEP**notches, event.position())
            elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.pan(notches * WHEEL_PAN_PX, 0.0)
            else:
                self.pan(delta.x() / 120 * WHEEL_PAN_PX, delta.y() / 120 * WHEEL_PAN_PX)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.interaction_mode == "hand":
            if not self.view_locked and not self._dragging():
                self._pan_from = QPointF(event.position())
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.interaction_mode in {"text", "shape"}:
            if self._tool_input():
                point = self.to_units(event.position())
                self.addRequested.emit(self.interaction_mode, float(point[0]), float(point[1]))
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton and self._canvas is not None:
            if not self.view_locked and not self._dragging():
                self._pan_from = QPointF(event.position())  # middle-drag pans
            event.accept()
            return
        if not self._tool_input() or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus()
        self.tool.press(event.position(), event.modifiers())

    def _tool_input(self) -> bool:
        """Mouse input goes to the tool: not while the camera is turned (ADR 0048), when what the
        tool hit-tests and drags - flat scene units - is not where the picture shows it."""
        return self.tool is not None and self._canvas is not None and not self.camera_turned

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._tool_input() or event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        self.tool.double_click(event.position(), event.modifiers())

    def mouseMoveEvent(self, event) -> None:
        if self._pan_from is not None:
            delta = event.position() - self._pan_from
            self._pan_from = QPointF(event.position())
            self.pan(delta.x(), delta.y())
            event.accept()
            return
        if self.interaction_mode == "hand":
            return
        if self._tool_input():
            self.tool.move(event.position(), event.modifiers())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.interaction_mode == "hand":
            self._pan_from = None
            if not self.view_locked:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_from = None
            event.accept()
            return
        if self._tool_input():
            self.tool.release()

    def keyPressEvent(self, event) -> None:
        if self.tool is not None and self._canvas is not None and self.tool.key(event):
            return
        if event.key() == Qt.Key.Key_F and not event.modifiers():  # Unity's F (P7.4)
            self.frame_selection()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()

    # -- code dropped (P12.7) ------------------------------------------------------

    def _set_drop_point(self, point: QPointF | None) -> None:
        if point != self.drop_point:
            self.drop_point = point
            self.update()

    def dragEnterEvent(self, event) -> None:
        if self._canvas is not None and code_drag.accepts(event.mimeData()):
            event.acceptProposedAction()
            self._set_drop_point(QPointF(event.position()))
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self.drop_point is not None and self._canvas is not None:
            event.acceptProposedAction()
            self._set_drop_point(QPointF(event.position()))
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_point(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        self._set_drop_point(None)
        if self._canvas is None or not code_drag.accepts(mime):
            super().dropEvent(event)
            return
        event.acceptProposedAction()
        x, y = (float(v) for v in self.to_units(event.position())[:2])
        payload, files = code_drag.decode(mime), code_drag.python_files(mime)
        # After the drop returns: the window may open a dialog, which must not run inside the
        # system's drag loop (the program dragged from would wait for it).
        if payload is not None:
            QTimer.singleShot(0, lambda: self.codeDropped.emit(payload, x, y))
        else:
            QTimer.singleShot(0, lambda: self.filesDropped.emit(files, x, y))
