"""The canvas view: what part of the scene the canvas shows, and how big (P3a, ADR 0023). No Qt.

A view is either **Fit** — the video frame letterboxed in the widget, as before
P3a — or an absolute **scale** (screen pixels per export pixel) around a
**centre** in Manim units. Zooming or panning leaves Fit; the scale and centre
then survive resizes, so an explicit 100 % stays 100 %.

``ViewGeometry`` turns a view into the numbers the canvas needs for one widget
size: pixels per unit and the world point at the widget's centre.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from ...core.model.schema import Canvas

SCALE_LIMITS = (0.05, 32.0)  # screen px per export px: 5 % - 3200 %
ZOOM_STEP = 1.2  # one wheel notch / one Zoom In


@dataclass(frozen=True)
class View:
    fit: bool = True
    scale: float = 1.0  # screen px per export px (ignored in Fit)
    centre: tuple[float, float] = (0.0, 0.0)  # world point at the widget centre (ignored in Fit)


@dataclass(frozen=True)
class ViewGeometry:
    ppu: float  # screen pixels per Manim unit
    centre: np.ndarray  # world point at the widget centre
    scale: float  # screen px per export px (also in Fit, for the readout)


def export_ppu(canvas: Canvas) -> float:
    """Export pixels per Manim unit."""
    return canvas.width_px / canvas.frame_width


def fit_ppu(canvas: Canvas, width: float, height: float) -> float:
    """Pixels per unit of the letterboxed frame in a ``width`` x ``height`` widget."""
    return min(width / canvas.frame_width, height / canvas.frame_height)


def geometry(view: View, canvas: Canvas, width: float, height: float) -> ViewGeometry:
    if view.fit:
        ppu = fit_ppu(canvas, width, height)
        return ViewGeometry(ppu, np.zeros(2), ppu / export_ppu(canvas))
    return ViewGeometry(view.scale * export_ppu(canvas), np.array(view.centre, float), view.scale)


def to_world(geo: ViewGeometry, width: float, height: float, x: float, y: float) -> np.ndarray:
    """Widget pixel (y down) -> Manim units (y up)."""
    return geo.centre + np.array([(x - width / 2) / geo.ppu, -(y - height / 2) / geo.ppu])


def zoom_about(
    view: View, canvas: Canvas, width: float, height: float, factor: float, x: float, y: float
) -> View:
    """Zoom by ``factor`` keeping the world point under widget pixel (x, y) where it is.

    The scale is clamped to SCALE_LIMITS; the anchor holds at the clamped scale too.
    """
    geo = geometry(view, canvas, width, height)
    scale = min(max(geo.scale * factor, SCALE_LIMITS[0]), SCALE_LIMITS[1])
    anchor = to_world(geo, width, height, x, y)
    centre = anchor + (geo.centre - anchor) * (geo.scale / scale)
    return View(fit=False, scale=scale, centre=(float(centre[0]), float(centre[1])))


def pan(view: View, canvas: Canvas, width: float, height: float, dx: float, dy: float) -> View:
    """Move the picture by (dx, dy) screen pixels (y down): the content follows the drag."""
    geo = geometry(view, canvas, width, height)
    centre = geo.centre - np.array([dx, -dy]) / geo.ppu
    return View(fit=False, scale=geo.scale, centre=(float(centre[0]), float(centre[1])))


def at_scale(view: View, canvas: Canvas, width: float, height: float, scale: float) -> View:
    """The same centre at ``scale`` (e.g. 1.0 for 100 %)."""
    geo = geometry(view, canvas, width, height)
    return replace(view, fit=False, scale=scale, centre=(float(geo.centre[0]), float(geo.centre[1])))


FRAME_MARGIN = 0.15  # of the box, on each side, when a selection is framed
MIN_FRAMED_UNITS = 0.5  # a dot or a flat line is framed as if it were this big


def frame_box(
    canvas: Canvas,
    width: float,
    height: float,
    low: tuple[float, float],
    high: tuple[float, float],
) -> View:
    """The view that shows the world box ``low``-``high`` centred, with a margin (F, P7.4)."""
    box_w = max(high[0] - low[0], MIN_FRAMED_UNITS) * (1 + 2 * FRAME_MARGIN)
    box_h = max(high[1] - low[1], MIN_FRAMED_UNITS) * (1 + 2 * FRAME_MARGIN)
    ppu = min(width / box_w, height / box_h)
    scale = min(max(ppu / export_ppu(canvas), SCALE_LIMITS[0]), SCALE_LIMITS[1])
    centre = ((low[0] + high[0]) / 2, (low[1] + high[1]) / 2)
    return View(fit=False, scale=scale, centre=centre)


def label(view: View, geo: ViewGeometry) -> str:
    percent = f"{geo.scale * 100:.0f} %"
    return f"Fit ({percent})" if view.fit else percent
