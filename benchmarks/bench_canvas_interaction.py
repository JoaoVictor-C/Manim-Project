"""S3 planning: the costs of clicking and dragging objects on the canvas.

On the stress scene plus a MathTex morph (``bench_edits.scene``), at a playhead
where most layers are visible:

* hit-testing one click against every layer: bounding boxes, filled paths
  (``qt_paths.vmobject_path``), Qt-stroked paths, and numpy distance to the
  curves' chords (for outlines and lines);
* building and painting a selection outline for one layer;
* one move-drag step: ``edits.update_layer(base=...)`` (or a keyframe edit for a
  keyframed layer) + ``Evaluator.apply`` + evaluate + Cairo render at 960x540;
  a keyframed plain layer, and a keyframed morph source mid-morph (slow path).
"""

from __future__ import annotations

import os
import statistics
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen

from bench_edits import scene
from manim_studio.core import edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Keyframe, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.render.qt_paths import camera_transform, vmobject_path

T = 2.5  # stress layers visible, the morph mid-way


def timed(fn, repeat: int = 15) -> float:
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def layer_mobjects(evaluator: Evaluator, t: float):
    out = []
    for layer in evaluator.project.layers:
        mob = evaluator._layer_at(layer, t)  # prototype: the public API returns no layer ids yet
        if mob is not None:
            out.append((layer.id, mob))
    return out


def bbox_hit(mobs, point) -> str | None:
    hit = None
    for layer_id, mob in mobs:
        pts = np.concatenate([m.points for m in mob.family_members_with_points()] or [np.zeros((1, 3))])
        lo, hi = pts[:, :2].min(axis=0), pts[:, :2].max(axis=0)
        if (lo <= point).all() and (point <= hi).all():
            hit = layer_id  # last = front-most
    return hit


def path_of(mob, stroke_tolerance: float | None) -> QPainterPath:
    path = QPainterPath()
    for sub in mob.family_members_with_points():
        if not hasattr(sub, "get_subpath_split_indices_from_points"):
            continue
        p = vmobject_path(sub)
        if stroke_tolerance:
            stroker = QPainterPathStroker()
            stroker.setWidth(stroke_tolerance)
            p = p.united(stroker.createStroke(p))
        path.addPath(p)
    return path


def path_hit(mobs, point, stroke_tolerance: float | None) -> str | None:
    hit = None
    q = QPointF(*point)
    for layer_id, mob in mobs:
        if path_of(mob, stroke_tolerance).contains(q):
            hit = layer_id
    return hit


def segment_hit(mobs, point, tolerance: float) -> str | None:
    """Distance from the click to each cubic's chord (anchor to anchor), vectorised."""
    hit = None
    for layer_id, mob in mobs:
        for sub in mob.family_members_with_points():
            pts = sub.points[:, :2]
            a, b = pts[0::4], pts[3::4]
            n = min(len(a), len(b))
            if n == 0:
                continue
            a, b = a[:n], b[:n]
            ab = b - a
            denom = (ab * ab).sum(1)
            denom[denom == 0] = 1
            u = np.clip(((point - a) * ab).sum(1) / denom, 0, 1)
            if (np.linalg.norm(a + ab * u[:, None] - point, axis=1) < tolerance).any():
                hit = layer_id
                break
    return hit


def main() -> None:
    QGuiApplication([])
    project = scene(keyframed_source=False)
    evaluator = Evaluator(project)
    camera = make_camera(project.canvas.model_copy(update={"width_px": 960, "height_px": 540}))
    render_frame(camera, evaluator.frame(T))
    mobs = layer_mobjects(evaluator, T)
    point = np.array([0.1, 0.2])
    print(f"visible layers at t={T}: {len(mobs)}")
    print(f"hit-test, bounding boxes      {timed(lambda: bbox_hit(mobs, point)):7.2f} ms/click")
    print(f"hit-test, filled paths        {timed(lambda: path_hit(mobs, point, None)):7.2f} ms/click")
    print(f"hit-test, fill + 0.1u stroke  {timed(lambda: path_hit(mobs, point, 0.1), 5):7.2f} ms/click")
    print(f"hit-test, chords within 0.1u  {timed(lambda: segment_hit(mobs, point, 0.1)):7.2f} ms/click")

    # what ships: render.hit_test (prefilter, alpha gate, numpy winding + flattened strokes)
    from manim_studio.render.hit_test import hit_layers

    layers = evaluator.frame_layers(T)
    clicks = np.random.default_rng(0).uniform([-7, -4], [7, 4], size=(40, 2))
    shipped = []
    for click in clicks:
        t0 = time.perf_counter()
        hit_layers(layers, click, 960 / project.canvas.frame_width)
        shipped.append((time.perf_counter() - t0) * 1000)
    median = statistics.median(shipped)
    print(f"hit_layers (shipped)          {median:7.2f} ms median, {max(shipped):.2f} ms max")

    # selection outline of the MathTex morph source, painted over a 960x540 image
    target = dict(mobs)["ma"]
    transform = camera_transform(project.canvas, 960, 540)
    image = QImage(960, 540, QImage.Format.Format_ARGB32_Premultiplied)

    def outline() -> None:
        path = transform.map(path_of(target, None))
        painter = QPainter(image)
        painter.setPen(QPen(QColor("#38bdf8"), 1.5))
        painter.drawPath(path)
        painter.drawRect(path.boundingRect())
        painter.end()

    print(f"selection outline (MathTex)   {timed(outline):7.2f} ms/frame")

    # move drag: base position of a static layer, then a keyframe of a keyframed layer
    plain_track = {"position": [Keyframe(t=0, value=(-2.0, 0.0)), Keyframe(t=4, value=(2.0, 0.0))]}
    for label, keyframed, layer_id in (
        ("move static layer (base)", False, "l1"),
        ("move keyframed layer (key)", True, "l1"),
        ("move morph source mid-morph", True, "ma"),
    ):
        project = scene(keyframed_source=keyframed)
        if keyframed and layer_id == "l1":
            project = edits.update_layer(project, "l1", tracks=plain_track).project
        evaluator = Evaluator(project)
        render_frame(camera, evaluator.frame(T))
        samples = []
        for i in range(12):
            t0 = time.perf_counter()
            layer = project.layer(layer_id)
            if keyframed:
                track = [k for k in layer.tracks["position"] if abs(k.t - T) > 1e-9]
                track.append(Keyframe(t=T, value=(0.05 * i, 0.0)))
                edit = edits.update_layer(project, layer_id, tracks={**layer.tracks, "position": track})
            else:
                edit = edits.update_layer(project, layer_id, base=Transform2D(position=(0.05 * i, 0.0)))
            evaluator.apply(edit)
            render_frame(camera, evaluator.frame(T))
            samples.append((time.perf_counter() - t0) * 1000)
            project = edit.project
        print(f"{label:<29} {statistics.median(samples[1:]):7.2f} ms/step  (kind {edit.kind})")


if __name__ == "__main__":
    main()
