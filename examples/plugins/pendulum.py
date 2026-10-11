"""An example Manim Studio plugin: a pendulum object (ADR 0032).

Copy this file into your plugin folder (``~/.manim-studio/plugins``, or a folder
named in ``MANIM_STUDIO_PLUGINS``) and restart the editor: Add > Physics >
Pendulum appears, with its length, angle and bob size in Properties.
"""

import math

import manim as m

from manim_studio.plugins import ObjectType, Param, register


def build(params: dict) -> m.VMobject:
    """A rod hanging from a pivot at ``angle`` degrees, with a bob at its end.

    Depends only on ``params``: the editor builds it twice on first use and
    refuses a builder that draws differently each time.
    """
    angle = math.radians(params["angle"])
    tip = params["length"] * (math.sin(angle) * m.RIGHT + math.cos(angle) * m.DOWN)
    pivot = m.Dot(m.ORIGIN, radius=0.05)
    rod = m.Line(m.ORIGIN, tip)
    bob = m.Circle(radius=params["bob"]).move_to(tip).set_fill(opacity=1.0)
    return m.VGroup(rod, pivot, bob)


register(
    ObjectType(
        "Pendulum",
        build,
        params=(
            Param("length", "float", 2.0, minimum=0.1, maximum=20.0, step=0.1),
            Param("angle", "float", 20.0, "Angle (degrees)", minimum=-180.0, maximum=180.0, step=1.0),
            Param("bob", "float", 0.25, "Bob radius", minimum=0.01, maximum=5.0, step=0.05),
        ),
        section="Physics",
    )
)
