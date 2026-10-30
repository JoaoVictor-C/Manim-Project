"""Shape objects (P10.2, ADR 0052): an object frozen into plain vector data - pure, no Manim.

A shape is ``Spec(type="Shape", params={"version": 1, "shapes": [...]})``: what another object
*drew*, kept as data, so it needs no code, no trust prompt and no LaTeX. Each entry of
``shapes`` is one drawn piece (a leaf of Manim's ``family_members_with_points()``, in that
order)::

    {
        "points": [[x, y], ...],     # its cubic bezier control points ([x, y, z] when any z is not 0)
        "fill": [r, g, b, a],        # one colour, or a gradient: the list of its stops [[r, g, b, a], ...]
        "stroke": [r, g, b, a],      # the same
        "stroke_width": 4.0,
        # optional, left out when Manim's default:
        "background": [r, g, b, a], "background_width": 0.0,   # the stroke drawn under the fill
        "sheen_direction": [-1, 1, 0], "sheen_factor": 0.0,    # where a gradient runs
        "joint": "AUTO", "cap": "AUTO",                        # line joints and caps
        "z_index": 0, "shade_in_3d": False,
    }

Colours are Manim's ``rgbas`` as they were (red, green, blue, opacity from 0 to 1), so the
same pixels are drawn. Points are stored centred on the origin, as every object is built.

*Freezing* replaces a layer's spec by a shape of what it draws (``edits.freeze_layer``); the
data comes from the built object (``adapter.shape_data``). This module checks the data and
says which layers can be frozen and why not.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .schema import (
    AXES_OBJECTS,
    CODE_TYPES,
    CONNECTOR_TYPES,
    GROUP_TYPES,
    RASTER_TYPES,
    SHAPE_TYPE,
    SHAPE_TYPES,
    TRACE_TYPES,
    Layer,
    Project,
)

VERSION = 1
MAX_POINTS = 300_000  # bezier control points a shape may hold (a long equation has ~10 000)
MAX_BYTES = 4 * 1024 * 1024  # its data as JSON
REQUIRED = frozenset({"points", "fill", "stroke", "stroke_width"})
OPTIONAL = frozenset(
    {
        "background",
        "background_width",
        "sheen_direction",
        "sheen_factor",
        "joint",
        "cap",
        "z_index",
        "shade_in_3d",
    }
)
JOINTS = ("AUTO", "ROUND", "BEVEL", "MITER")  # Manim's LineJointType names
CAPS = ("AUTO", "ROUND", "BUTT", "SQUARE")  # Manim's CapStyleType names
FROZEN_NOTE = "Frozen: plain vector data"
__all__ = ["FROZEN_NOTE", "MAX_BYTES", "MAX_POINTS", "SHAPE_TYPE", "VERSION"]


# -- the data ----------------------------------------------------------------------------------------


def spec_problem(params: dict[str, Any]) -> str | None:
    """Why a shape's spec params are not acceptable (the file format), or None."""
    unknown = sorted(set(params) - {"version", "shapes"})
    if unknown:
        return f"unknown params {unknown} (a shape has version and shapes)"
    if params.get("version") != VERSION:
        return f"shape version {params.get('version')!r} is not supported (this editor reads {VERSION})"
    shapes = params.get("shapes")
    if not isinstance(shapes, list) or not shapes:
        return "a shape needs its pieces: shapes is a list of drawn paths"
    total = 0
    for index, piece in enumerate(shapes):
        why = _piece_problem(piece)
        if why is not None:
            return f"shapes[{index}]: {why}"
        total += len(piece["points"])
    if total > MAX_POINTS:
        return f"{total} points is more than a shape may hold ({MAX_POINTS})"
    return None


def _piece_problem(piece: Any) -> str | None:
    if not isinstance(piece, dict):
        return "each piece is an object with points and colours"
    missing = sorted(REQUIRED - set(piece))
    if missing:
        return f"missing {missing}"
    unknown = sorted(set(piece) - REQUIRED - OPTIONAL)
    if unknown:
        return f"unknown keys {unknown}"
    if not _points(piece["points"]):
        return "points must be a non-empty list of [x, y] or [x, y, z], all of one size, finite numbers"
    for key in ("fill", "stroke", "background"):
        if key in piece and not _rgbas(piece[key]):
            return f"{key} must be [r, g, b, a] or a list of them, numbers from 0 to 1"
    for key in ("stroke_width", "background_width"):
        if key in piece and not (_finite(piece[key]) and piece[key] >= 0):
            return f"{key} must be a number, 0 or more"
    if "sheen_direction" in piece:
        direction = piece["sheen_direction"]
        if not (isinstance(direction, list) and len(direction) == 3 and all(map(_finite, direction))):
            return "sheen_direction must be [x, y, z]"
    if "sheen_factor" in piece and not _finite(piece["sheen_factor"]):
        return "sheen_factor must be a number"
    if piece.get("joint", "AUTO") not in JOINTS:
        return f"joint must be one of {', '.join(JOINTS)}"
    if piece.get("cap", "AUTO") not in CAPS:
        return f"cap must be one of {', '.join(CAPS)}"
    if "z_index" in piece and not _finite(piece["z_index"]):
        return "z_index must be a number"
    if "shade_in_3d" in piece and not isinstance(piece["shade_in_3d"], bool):
        return "shade_in_3d must be true or false"
    return None


def _points(points: Any) -> bool:
    """A non-empty list of ``[x, y]`` or ``[x, y, z]`` of finite numbers (checked by numpy: a long
    equation's ten thousand points are checked on every edit of its layer)."""
    if not isinstance(points, list) or not points or not all(isinstance(p, list) for p in points):
        return False
    try:
        array = np.asarray(points)
    except ValueError:  # ragged
        return False
    return (
        array.ndim == 2
        and array.shape[1] in (2, 3)
        and array.dtype.kind in "fiu"
        and bool(np.isfinite(array).all())
    )


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _rgba(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(_finite(v) and 0 <= v <= 1 for v in value)


def _rgbas(value: Any) -> bool:
    """One colour ``[r, g, b, a]`` or a gradient: a non-empty list of them."""
    if _rgba(value):
        return True
    return isinstance(value, list) and bool(value) and all(map(_rgba, value))


def size_problem(points: int, json_bytes: int) -> str | None:
    """Why an object of ``points`` control points and ``json_bytes`` of data is too big to freeze."""
    if points > MAX_POINTS:
        return f"it has {points} points; a shape may hold {MAX_POINTS}"
    if json_bytes > MAX_BYTES:
        return f"its data would take {json_bytes / 1e6:.1f} MB; a shape may take {MAX_BYTES // 2**20} MB"
    return None


# -- which layers can be frozen ------------------------------------------------------------------------


def kind_problem(layer: Layer) -> str | None:
    """Why a layer of this kind can never be frozen (whatever its clips or children), or None.

    Properties shows "Freeze to shape" only when this is None."""
    if layer.is_part:
        return "a part draws pieces of its equation: freeze the equation (without parts)"
    spec = layer.spec
    if spec.type in SHAPE_TYPES:
        return "it is already a shape"
    if spec.type in GROUP_TYPES:
        return "a group draws nothing itself: freeze its objects one by one"
    if spec.type in CODE_TYPES:
        return "a code layer is a whole scene played as pictures, not one object"
    if spec.type in CONNECTOR_TYPES:
        return "a connector is redrawn between its two layers every frame"
    if spec.type in TRACE_TYPES:
        return "a traced path is drawn frame by frame from where its target was"
    if spec.type in RASTER_TYPES:
        return "an image is pixels, not vector paths"
    if spec.type in AXES_OBJECTS:
        return f"a {spec.type} is drawn with its axes"
    return None


def freeze_problem(project: Project, layer_id: str) -> str | None:
    """Why ``layer_id`` cannot be frozen into a shape as the project is, or None.

    Besides its kind: a layer with parts or child objects (parts name pieces of its LaTeX, a
    graph is plotted on its axes), and clips that need the object's own type (letter by letter
    on a Text, counting on a Number, a TeX match at either end). Whether it is drawn -
    not a placeholder, not failing - is asked of the built object (``adapter.freeze_data``)."""
    layer = project.layer(layer_id)
    problem = kind_problem(layer)
    if problem is not None:
        return problem
    children = project.children(layer_id)
    if any(child.is_part for child in children):
        return "it has parts (they name pieces of its LaTeX): delete its parts first"
    if children:
        return "it has objects on it (graphs, labels): a shape cannot hold them"
    for clip in layer.clips:
        only = clip.info.only_types
        if only is not None and SHAPE_TYPE not in only:
            return f"its {clip.kind} clip ({clip.id}) needs {' or '.join(sorted(only))}: remove it first"
    for other in project.layers:
        for clip in other.clips:
            only = clip.info.only_types
            if clip.to_layer == layer_id and only is not None and SHAPE_TYPE not in only:
                return (
                    f"{other.name or other.id}'s {clip.kind} clip ({clip.id}) turns it into this "
                    f"object and needs {' or '.join(sorted(only))}: remove that clip first"
                )
    return None
