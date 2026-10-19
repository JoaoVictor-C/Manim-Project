"""Smart morph matching, the pure geometry (ADR 0056): ``core/morph.py``, numpy only."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from manim_studio.core import morph


def line(p: tuple, q: tuple) -> np.ndarray:
    """One straight cubic curve from p to q (Manim's layout: anchor, handle, handle, anchor)."""
    a, b = np.array([*p, 0.0]), np.array([*q, 0.0])
    return np.array([a, a + (b - a) / 3, a + 2 * (b - a) / 3, b])


def polygon(*corners: tuple) -> np.ndarray:
    """A closed outline through ``corners``, one curve per side."""
    return np.concatenate([line(p, q) for p, q in itertools.pairwise([*corners, corners[0]])])


SQUARE = polygon((1, 1), (-1, 1), (-1, -1), (1, -1))  # Manim's order: UR, UL, DL, DR (counter-clockwise)
TRIANGLE = polygon((0, 1.5), (-1.3, -0.75), (1.3, -0.75))


def anchors(points: np.ndarray) -> np.ndarray:
    return points[:: morph.N, :2]


def on_outline(points: np.ndarray, outline: np.ndarray, tol: float = 1e-6) -> bool:
    """Every anchor of ``points`` lies on ``outline`` (a polygon of straight sides)."""
    corners = anchors(outline)
    for p in anchors(points):
        best = np.inf
        for a, b in itertools.pairwise([*corners, corners[0]]):
            t = np.clip(np.dot(p - a, b - a) / np.dot(b - a, b - a), 0, 1)
            best = min(best, np.linalg.norm(a + t * (b - a) - p))
        if best > tol:
            return False
    return True


def circle(n: int = 8, r: float = 1.0) -> np.ndarray:
    """Manim's circle layout: n arcs from angle 0, counter-clockwise."""
    out = []
    k = 4 / 3 * np.tan(np.pi / (2 * n))
    for i in range(n):
        t0, t1 = 2 * np.pi * i / n, 2 * np.pi * (i + 1) / n
        p0 = r * np.array([np.cos(t0), np.sin(t0), 0.0])
        p3 = r * np.array([np.cos(t1), np.sin(t1), 0.0])
        d0 = r * k * np.array([-np.sin(t0), np.cos(t0), 0.0])
        d1 = r * k * np.array([-np.sin(t1), np.cos(t1), 0.0])
        out.append([p0, p0 + d0, p3 - d1, p3])
    return np.array(out).reshape(-1, 3)


# -- outlines ---------------------------------------------------------------------------------------


def test_subpaths_split_where_a_curve_does_not_continue() -> None:
    hole = polygon((0.5, 0.5), (0.5, -0.5), (-0.5, -0.5), (-0.5, 0.5))
    parts = morph.subpaths(np.concatenate([SQUARE, hole]))
    assert [len(p) for p in parts] == [16, 16]
    assert all(morph.is_closed(p) for p in parts)
    assert not morph.is_closed(line((0, 0), (1, 0)))
    assert morph.subpaths(np.zeros((3, 3))) == []  # no whole curve


def test_split_curve_draws_the_same_curve() -> None:
    curve = circle(4)[:4]
    left, right = morph.split_curve(curve, 0.3)
    whole = morph._bezier(curve[None], np.linspace(0, 1, 11))[0]
    assert np.allclose(left[-1], right[0]) and np.allclose(left[0], curve[0]) and np.allclose(right[-1], curve[-1])
    assert np.allclose(morph._bezier(left[None], [1.0])[0, 0], morph._bezier(curve[None], [0.3])[0, 0])
    assert np.allclose(whole[0], curve[0])


# -- one loop pair ---------------------------------------------------------------------------------


def test_a_square_into_itself_turned_90_degrees_does_not_turn() -> None:
    """The same square starting at its next corner: every point stays where it is."""
    turned = np.concatenate([SQUARE[4:], SQUARE[:4]])
    a, b = morph.align_loops(SQUARE, turned)
    assert a.shape == b.shape
    assert np.allclose(a, b)  # interpolation is the square itself at every alpha


def test_a_shifted_and_scaled_copy_only_moves_and_grows() -> None:
    other = np.concatenate([SQUARE[8:], SQUARE[:8]]) * 2.0 + np.array([3.0, 1.0, 0.0])
    a, b = morph.align_loops(SQUARE, other)
    assert np.allclose(a * 2.0 + np.array([3.0, 1.0, 0.0]), b)


def test_opposite_windings_flip_instead_of_collapsing() -> None:
    clockwise = morph._reverse(SQUARE)
    a, b = morph.align_loops(SQUARE, clockwise)
    assert np.allclose(a, b)
    a, b = morph.align_loops(SQUARE, clockwise, flip=False)  # forced: the travel is longer
    assert not np.allclose(a, b)


def test_open_paths_run_the_shorter_way() -> None:
    a, b = morph.align_loops(line((-1, 0), (1, 0)), line((1, 0.1), (-1, 0.1)))
    assert np.allclose(a[0, :2], [1, 0]) and np.allclose(b[0, :2], [1, 0.1])


def test_cutting_keeps_every_corner_and_the_drawing() -> None:
    a, b = morph.align_loops(TRIANGLE, SQUARE)
    assert a.shape == b.shape and len(a) % morph.N == 0
    for corner in anchors(TRIANGLE):  # corners stay anchors: no side is rounded off
        assert np.min(np.linalg.norm(anchors(a) - corner, axis=1)) < 1e-9
    for corner in anchors(SQUARE):
        assert np.min(np.linalg.norm(anchors(b) - corner, axis=1)) < 1e-9
    assert on_outline(a, TRIANGLE) and on_outline(b, SQUARE)  # new anchors sit on the old sides


def test_close_corners_snap_together() -> None:
    """A square into a circle of 4 arcs whose anchors are near the square's corners: the
    corners pair with the anchors instead of adding a curve each."""
    ring = circle(4, r=1.4)
    turned = ring @ np.array([[np.cos(0.8), np.sin(0.8), 0], [-np.sin(0.8), np.cos(0.8), 0], [0, 0, 1]])
    a, b = morph.align_loops(SQUARE, turned)
    assert len(a) == len(SQUARE)  # 4 curves each: every corner found a partner


def test_square_into_circle_is_symmetric() -> None:
    a, b = morph.align_loops(SQUARE, circle(8))
    mid = (a + b) / 2
    # a corner of the square travels to the circle point on its own diagonal, not a quarter turn
    corner = np.argmin(np.linalg.norm(anchors(a) - [1, 1], axis=1))
    assert np.allclose(anchors(b)[corner], [np.sqrt(0.5), np.sqrt(0.5)])
    poly = morph.sample_subpath(mid[:, :2])
    assert morph.self_crossings(poly) == 0
    assert np.allclose(np.abs(poly).max(axis=0), np.abs(poly).max(axis=0)[::-1], atol=1e-6)  # x and y alike


# -- pieces ----------------------------------------------------------------------------------------


def brute_force(cost: np.ndarray) -> float:
    rows, cols = cost.shape
    k = min(rows, cols)
    if rows <= cols:
        return min(sum(cost[i, p[i]] for i in range(k)) for p in itertools.permutations(range(cols), k))
    return min(sum(cost[p[j], j] for j in range(k)) for p in itertools.permutations(range(rows), k))


@pytest.mark.parametrize("shape", [(5, 5), (4, 6), (6, 4), (1, 3), (3, 1)])
def test_assignment_is_optimal(shape) -> None:
    rng = np.random.default_rng(7)
    for _ in range(5):
        cost = rng.random(shape)
        pairs = morph.assign(cost)
        assert len(pairs) == min(shape)
        assert len({i for i, _ in pairs}) == len({j for _, j in pairs}) == min(shape)
        assert sum(cost[i, j] for i, j in pairs) == pytest.approx(brute_force(cost))


def blob(x: float, y: float, size: float = 0.4) -> np.ndarray:
    return polygon((x + size, y + size), (x - size, y + size), (x - size, y - size), (x + size, y - size))


def test_pieces_pair_by_place_whatever_their_order() -> None:
    source = [blob(-2, 0), blob(0, 0), blob(2, 0)]
    target = [blob(7, 1), blob(3, 1), blob(5, 1)]  # moved, listed in another order
    plan = morph.plan(source, target)
    assert sorted((p.source, p.target) for p in plan) == [(0, 1), (1, 2), (2, 0)]
    for p in plan:  # each piece only moves: no deformation
        assert np.allclose(p.end - p.start, p.end[0] - p.start[0])


def test_a_piece_without_partner_shrinks_to_its_place_and_one_grows_from_it() -> None:
    plan = morph.plan([blob(-2, 0), blob(0, 0), blob(2, 0)], [blob(-2, 0), blob(2, 0)])
    lone = [p for p in plan if p.target is None]
    assert len(lone) == 1 and lone[0].source == 1
    assert np.allclose(lone[0].start, blob(0, 0)) and np.allclose(lone[0].end, lone[0].end[0])  # one point
    assert np.allclose(lone[0].end[0, :2], [0, 0])  # the middle of the target, where it was in the source
    grown = [p for p in morph.plan([blob(0, 0)], [blob(-1, 0), blob(1, 0)]) if p.source is None]
    assert len(grown) == 1 and np.allclose(grown[0].start, grown[0].start[0])


def test_the_same_glyph_keeps_its_partner_when_near() -> None:
    source = [blob(-0.15, 0), blob(0.15, 0, size=0.3)]
    target = [blob(-0.15, 0, size=0.3), blob(0.15, 0)]  # close neighbours trading places
    by_place = morph.plan(source, target)
    assert sorted((p.source, p.target) for p in by_place) == [(0, 0), (1, 1)]
    keyed = morph.plan(source, target, ["big", "small"], ["small", "big"])
    assert sorted((p.source, p.target) for p in keyed) == [(0, 1), (1, 0)]
    far = [blob(-2, 0), blob(2, 0, size=0.3)], [blob(-2, 0, size=0.3), blob(2, 0)]
    across = morph.plan(*far, ["big", "small"], ["small", "big"])  # never across the whole object
    assert sorted((p.source, p.target) for p in across) == [(0, 0), (1, 1)]


def test_holes_pair_with_holes() -> None:
    hole = morph._reverse(blob(0.3, 0, size=0.2))
    ring = np.concatenate([blob(0, 0, size=1.0), hole])
    other_hole = morph._reverse(blob(-0.2, 0.1, size=0.3))
    other = np.concatenate([other_hole, blob(0, 0, size=1.2)])  # listed hole first
    start, end = morph.align_pieces(ring, other)
    parts_start, parts_end = morph.subpaths(start), morph.subpaths(end)
    assert len(parts_start) == len(parts_end) == 2
    sizes = [np.ptp(p[:, 0]) for p in parts_end]
    starts = [np.ptp(p[:, 0]) for p in parts_start]
    assert np.argmin(sizes) == np.argmin(starts)  # the small loop (hole) into the small loop


def test_an_unpaired_hole_closes_inside_its_piece() -> None:
    letter_o = np.concatenate([blob(0, 0, size=1.0), morph._reverse(blob(0, 0, size=0.5))])
    start, end = morph.align_pieces(letter_o, blob(3, 0, size=1.0))
    closing = morph.subpaths(end)[-1]
    assert np.allclose(closing, closing[0]) and np.allclose(closing[0, :2], [3, 0])  # at the centre


def test_plans_are_deterministic() -> None:
    source = [circle(8), blob(2, 0), TRIANGLE]
    target = [SQUARE * 1.5, blob(-2, 1)]
    one, two = morph.plan(source, target), morph.plan(source, target)
    assert [(p.source, p.target) for p in one] == [(p.source, p.target) for p in two]
    assert all(np.array_equal(p.start, q.start) and np.array_equal(p.end, q.end) for p, q in zip(one, two))


# -- colour ----------------------------------------------------------------------------------------


def test_colour_ends_are_exact_and_the_middle_is_not_muddy() -> None:
    blue, red = np.array([[0.2, 0.4, 1.0, 1.0]]), np.array([[1.0, 0.2, 0.2, 1.0]])
    assert np.array_equal(morph.blend_rgbas(blue, red, 0.0), blue)
    assert np.array_equal(morph.blend_rgbas(blue, red, 1.0), red)
    assert np.array_equal(morph.blend_rgbas(blue, red, -0.3), blue)  # an overshooting ease is held
    middle = morph.blend_rgbas(blue, red, 0.5)
    lightness = morph.srgb_to_oklab(np.vstack([blue[:, :3], red[:, :3], middle[:, :3]]))[:, 0]
    assert lightness[2] == pytest.approx((lightness[0] + lightness[1]) / 2, abs=1e-9)
    straight = (blue + red) / 2  # what a plain sRGB blend gives: darker than both ends' mean
    assert morph.srgb_to_oklab(straight[:, :3])[0, 0] < lightness[2] - 0.02


def test_a_colour_fading_out_does_not_tint_the_other() -> None:
    shown, hidden = np.array([[0.2, 0.4, 1.0, 0.8]]), np.array([[1.0, 1.0, 1.0, 0.0]])
    middle = morph.blend_rgbas(shown, hidden, 0.5)
    assert np.allclose(middle[0, :3], shown[0, :3], atol=1e-9)
    assert middle[0, 3] == pytest.approx(0.4)


def test_oklab_round_trips() -> None:
    rgb = np.random.default_rng(1).random((20, 3))
    assert np.allclose(morph.oklab_to_srgb(morph.srgb_to_oklab(rgb)), rgb, atol=1e-9)


def test_per_row_alphas() -> None:
    a, b = np.zeros((3, 4)), np.ones((3, 4))
    out = morph.blend_rgbas(a, b, np.array([0.0, 0.5, 1.0]))
    assert np.array_equal(out[0], a[0]) and np.array_equal(out[2], b[2]) and out[1, 3] == pytest.approx(0.5)


# -- measures --------------------------------------------------------------------------------------


def test_self_crossings_and_area() -> None:
    bow = np.array([[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]], dtype=float)
    assert morph.self_crossings(bow) == 1
    assert morph.self_crossings(morph.sample_subpath(SQUARE[:, :2])) == 0
    assert morph.signed_area(anchors(SQUARE)) == pytest.approx(4.0)
    assert morph.signed_area(anchors(morph._reverse(SQUARE))) == pytest.approx(-4.0)
