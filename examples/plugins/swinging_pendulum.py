"""An example Manim Studio simulation: a damped pendulum swinging under gravity (ADR 0033).

Copy this file into your plugin folder (``~/.manim-studio/plugins``, or a folder
named in ``MANIM_STUDIO_PLUGINS``) and restart the editor: Add > Physics >
Swinging pendulum appears. Select it and use Add > Simulation > Traced path to
draw the path of its bob.

The editor steps the state once per frame (dt = 1 / fps), like a Manim updater,
and keeps states along the way so any frame can be shown in any order.
"""

import math

import manim as m

from manim_studio.plugins import Param, Simulation, register

GRAVITY = 9.81


def start(params: dict) -> tuple[float, float]:
    """The state: the angle from straight down (radians) and the angular speed."""
    return math.radians(params["angle"]), 0.0


def step(state: tuple[float, float], dt: float, params: dict) -> tuple[float, float]:
    """One frame of motion, integrated with four Runge-Kutta stages."""

    def rates(theta: float, omega: float) -> tuple[float, float]:
        return omega, -GRAVITY / params["length"] * math.sin(theta) - params["damping"] * omega

    theta, omega = state
    k1 = rates(theta, omega)
    k2 = rates(theta + dt / 2 * k1[0], omega + dt / 2 * k1[1])
    k3 = rates(theta + dt / 2 * k2[0], omega + dt / 2 * k2[1])
    k4 = rates(theta + dt * k3[0], omega + dt * k3[1])
    return (
        theta + dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]),
        omega + dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]),
    )


def bob(state: tuple[float, float], params: dict) -> tuple[float, float]:
    """Where the bob is, from the pivot (what a traced path follows)."""
    return params["length"] * math.sin(state[0]), -params["length"] * math.cos(state[0])


def draw(state: tuple[float, float], params: dict) -> m.VMobject:
    """The pivot at the layer's position, the rod and the bob."""
    x, y = bob(state, params)
    tip = [x, y, 0.0]
    weight = m.Circle(radius=params["bob"]).move_to(tip).set_fill(opacity=1.0)
    return m.VGroup(m.Line(m.ORIGIN, tip), m.Dot(m.ORIGIN, radius=0.05), weight)


register(
    Simulation(
        "SwingingPendulum",
        start,
        step,
        draw,
        point=bob,
        params=(
            Param("length", "float", 2.0, minimum=0.1, maximum=20.0, step=0.1),
            Param("angle", "float", 60.0, "Start angle (degrees)", minimum=-179.0, maximum=179.0, step=1.0),
            Param("damping", "float", 0.15, minimum=0.0, maximum=5.0, step=0.05),
            Param("bob", "float", 0.2, "Bob radius", minimum=0.01, maximum=5.0, step=0.05),
        ),
        section="Physics",
        label="Swinging pendulum",
    )
)
