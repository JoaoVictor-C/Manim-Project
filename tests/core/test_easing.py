"""Easing (ADR 0004 keyframes, ADR 0007 clamping): cubic-bezier and keyframe sampling."""

from __future__ import annotations

import functools

import numpy as np
import pytest

from manim_studio.core import adapter
from manim_studio.core.evaluator import _sample
from manim_studio.core.schema import Easing, Keyframe

# CSS named timing functions, as defined by the CSS Easing spec.
CSS = {
    "ease": (0.25, 0.1, 0.25, 1.0),
    "ease-in": (0.42, 0.0, 1.0, 1.0),
    "ease-out": (0.0, 0.0, 0.58, 1.0),
    "ease-in-out": (0.42, 0.0, 0.58, 1.0),
}


@functools.cache
def _dense_curve(x1: float, y1: float, x2: float, y2: float) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0, 1, 200_001)
    bx = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t**2 * x2 + t**3
    by = 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t**2 * y2 + t**3
    return bx, by


def brute_force_bezier(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    """Independent reference: sample the parametric curve densely and interpolate y at x."""
    bx, by = _dense_curve(x1, y1, x2, y2)
    return float(np.interp(x, bx, by))


@pytest.mark.parametrize("name", CSS)
def test_css_timing_functions_match_reference(name: str) -> None:
    func = adapter.cubic_bezier(*CSS[name])
    for x in np.linspace(0, 1, 41):
        assert func(x) == pytest.approx(brute_force_bezier(*CSS[name], x), abs=1e-4), f"{name} at {x}"


def test_known_css_ease_value() -> None:
    # Widely published value of CSS `ease` at the midpoint.
    assert adapter.cubic_bezier(*CSS["ease"])(0.5) == pytest.approx(0.8024, abs=1e-3)


def test_linear_bezier_is_identity() -> None:
    func = adapter.cubic_bezier(0, 0, 1, 1)
    for x in np.linspace(0, 1, 11):
        assert func(x) == pytest.approx(x, abs=1e-6)


def test_endpoints_are_exact_and_clamped_outside() -> None:
    func = adapter.cubic_bezier(0.3, 1.8, 0.6, -0.8)
    assert func(0) == 0.0 and func(1) == 1.0
    assert func(-0.5) == 0.0 and func(1.5) == 1.0


def test_overshooting_curve_overshoots() -> None:
    back_out = (0.34, 1.56, 0.64, 1.0)
    func = adapter.cubic_bezier(*back_out)
    peak = max(func(x) for x in np.linspace(0, 1, 101))
    assert peak > 1.05
    assert peak == pytest.approx(
        max(brute_force_bezier(*back_out, x) for x in np.linspace(0, 1, 101)), abs=1e-3
    )


def test_steep_curve_uses_bisection_fallback() -> None:
    """x1 = x2 = 0 or 1 makes dx/dt vanish at the ends, where Newton stalls."""
    func = adapter.cubic_bezier(1.0, 0.0, 0.0, 1.0)
    for x in np.linspace(0.01, 0.99, 25):
        assert func(x) == pytest.approx(brute_force_bezier(1.0, 0.0, 0.0, 1.0, x), abs=1e-3)


@pytest.mark.parametrize("name", ["linear", "smooth", "rush_into", "rush_from", "there_and_back"])
def test_named_manim_rate_functions_resolve(name: str) -> None:
    func = adapter.rate_func(Easing(name=name))
    assert callable(func) and isinstance(func(0.5), int | float)  # Manim may return ints


# --- keyframe sampling --------------------------------------------------------


def test_sample_holds_before_first_and_after_last() -> None:
    track = [Keyframe(t=1, value=2.0), Keyframe(t=2, value=4.0)]
    assert _sample(track, 0.0, 9.0) == 2.0
    assert _sample(track, 5.0, 9.0) == 4.0


def test_sample_without_track_uses_default() -> None:
    assert _sample(None, 1.0, 7.0) == 7.0
    assert _sample([], 1.0, 7.0) == 7.0


def test_sample_interpolates_vectors_linearly() -> None:
    track = [
        Keyframe(t=0, value=(0.0, 0.0), ease=Easing(name="linear")),
        Keyframe(t=2, value=(4.0, -2.0)),
    ]
    assert _sample(track, 1.0, (9.0, 9.0)) == pytest.approx((2.0, -1.0))


def test_sample_uses_the_leaving_keyframes_ease() -> None:
    """The ease on keyframe k shapes the segment from k to k+1 (docs/project-format.md)."""
    track = [
        Keyframe(t=0, value=0.0, ease=Easing(bezier=CSS["ease-in"])),
        Keyframe(t=1, value=1.0, ease=Easing(name="linear")),
        Keyframe(t=2, value=0.0),
    ]
    assert _sample(track, 0.5, 0.0) == pytest.approx(adapter.cubic_bezier(*CSS["ease-in"])(0.5))
    assert _sample(track, 1.5, 0.0) == pytest.approx(0.5)
