"""Ready-made code for Python objects (P10): the Code page's "New Python object" menu.

Each template is the source a user would write: ``PARAMS`` and optional ``HANDLES`` declarations
(read without running it), plus ``build(p)``. They are plain Manim, so they double as examples to copy from.
"""

from __future__ import annotations

from . import python_object

# A matrix of any size, written by the user for their Pythagoras project: one MathTex (so one LaTeX
# build, fast) with the shape and the entries as parameters.
MATRIX = r"""# A matrix: choose its rows and columns and type the entries.
#
# values: the entries, row by row. Rows are separated by ";" and cells by ",".
# Entries are LaTeX: 1, -2, a_{11}, \frac{1}{2}, \pi ...  A missing entry is 0 and
# extra entries are ignored, so you can change rows/columns first and fill in later.

PARAMS = {
    "rows": (3, 1, 8),
    "columns": (3, 1, 8),
    "values": "1,2,3;4,5,6;7,8,9",
    "color": "#ffffff",
}

def build(p):
    rows = max(1, min(8, int(p["rows"])))
    cols = max(1, min(8, int(p["columns"])))

    # Parse rows separated by semicolons and values separated by commas.
    data = [
        [cell.strip() for cell in row.split(",")]
        for row in p["values"].split(";")
    ]

    # Fill missing cells with 0, then select the requested matrix size.
    matrix_rows = []
    for r in range(rows):
        source_row = data[r] if r < len(data) else []
        cells = [
            source_row[c] if c < len(source_row) and source_row[c] else "0"
            for c in range(cols)
        ]
        matrix_rows.append(" & ".join(cells))

    latex = r"\begin{bmatrix}" + r" \\ ".join(matrix_rows) + r"\end{bmatrix}"
    matrix = MathTex(latex, font_size=48)
    matrix.set_color(p["color"])
    return matrix
"""

GRID = r"""# A clean coordinate grid that works as a reusable background layer.

PARAMS = {
    "rows": (8, 1, 24),
    "columns": (14, 1, 32),
    "width": (14.0, 2.0, 24.0),
    "height": (8.0, 1.0, 14.0),
    "color": "#64748b",
}


def build(p):
    rows = int(p["rows"])
    columns = int(p["columns"])
    width = float(p["width"])
    height = float(p["height"])
    horizontal = [
        Line(
            [-width / 2, -height / 2 + height * row / rows, 0],
            [width / 2, -height / 2 + height * row / rows, 0],
        )
        for row in range(rows + 1)
    ]
    vertical = [
        Line(
            [-width / 2 + width * column / columns, -height / 2, 0],
            [-width / 2 + width * column / columns, height / 2, 0],
        )
        for column in range(columns + 1)
    ]
    return VGroup(*(horizontal + vertical)).set_stroke(color=p["color"], width=1)
"""

LABELED_VECTOR = r"""# A vector with its symbol placed at the tip.

PARAMS = {
    "x": (3.0, -10.0, 10.0),
    "y": (2.0, -10.0, 10.0),
    "label": "v",
    "color": "#38bdf8",
}

HANDLES = {"Tip": ("x", "y")}


def build(p):
    arrow = Arrow(ORIGIN, [p["x"], p["y"], 0], buff=0.08, color=p["color"])
    label = MathTex(p["label"], color=p["color"])
    label.next_to(arrow.get_end(), UR, buff=0.15)
    return VGroup(arrow, label)
"""

ORBITAL_SATELLITE = r"""# A small satellite system with three draggable geometry handles.
# Drag Planet center to move the planet, Orbit extent to resize the orbit, and
# Satellite to place and aim the orbiter.

PARAMS = {
    "center_x": (0.0, -5.0, 5.0),
    "center_y": (0.0, -3.0, 3.0),
    "orbit_x": (2.8, -6.0, 6.0),
    "orbit_y": (1.65, -4.0, 4.0),
    "satellite_x": (1.9, -6.0, 6.0),
    "satellite_y": (1.0, -4.0, 4.0),
    "planet_radius": (0.62, 0.3, 1.1),
    "accent": "#38bdf8",
}

HANDLES = {
    "Planet center": ("center_x", "center_y"),
    "Orbit extent": ("orbit_x", "orbit_y"),
    "Satellite": ("satellite_x", "satellite_y"),
}


def build(p):
    center = np.array([p["center_x"], p["center_y"], 0.0])
    satellite_tip = np.array([p["satellite_x"], p["satellite_y"], 0.0])
    radius = float(p["planet_radius"])
    orbit_width = max(0.2, 2 * abs(p["orbit_x"] - p["center_x"]))
    orbit_height = max(0.2, 2 * abs(p["orbit_y"] - p["center_y"]))
    orbit = Ellipse(width=orbit_width, height=orbit_height)
    orbit.set_stroke(color="#2563eb", width=2, opacity=0.8)
    orbit.move_to(center)
    dashed_orbit = DashedVMobject(orbit.copy(), num_dashes=64)
    dashed_orbit.set_stroke(color=p["accent"], width=1.5, opacity=0.8)

    stars = VGroup(
        *[
            Circle(radius=0.025, stroke_width=0, fill_opacity=0.9, color="#e0f2fe").move_to(
                center + np.array([x, y, 0.0])
            )
            for x, y in ((-2.7, 1.8), (-2.1, -1.9), (2.2, 2.1), (3.0, -1.6), (0.0, 2.5))
        ]
    )

    moon = Circle(radius=0.16, color="#cbd5e1", fill_opacity=1)
    moon.move_to(center + np.array([-0.68 * orbit_width / 2, 0.62 * orbit_height / 2, 0.0]))
    moon_crater = Circle(radius=0.045, color="#94a3b8", fill_opacity=0.9)
    moon_crater.move_to(moon.get_center() + np.array([0.035, 0.045, 0.0]))

    atmosphere = Circle(radius=radius * 1.18, color=p["accent"], stroke_width=1, stroke_opacity=0.55)
    atmosphere.set_fill(color=p["accent"], opacity=0.08).move_to(center)
    planet = Circle(radius=radius, color="#0f172a", stroke_width=2)
    planet.set_fill(color="#0f3b63", opacity=1).move_to(center)
    continents = VGroup(
        Polygon(
            center + np.array([-0.55 * radius, 0.18 * radius, 0.0]),
            center + np.array([-0.12 * radius, 0.48 * radius, 0.0]),
            center + np.array([0.08 * radius, 0.20 * radius, 0.0]),
            center + np.array([-0.05 * radius, -0.02 * radius, 0.0]),
            center + np.array([-0.40 * radius, -0.12 * radius, 0.0]),
        ),
        Polygon(
            center + np.array([0.18 * radius, -0.10 * radius, 0.0]),
            center + np.array([0.56 * radius, -0.02 * radius, 0.0]),
            center + np.array([0.42 * radius, -0.42 * radius, 0.0]),
            center + np.array([0.12 * radius, -0.48 * radius, 0.0]),
        ),
    )
    continents.set_fill(color="#34d399", opacity=0.85).set_stroke(width=0)
    equator = Ellipse(width=radius * 1.8, height=radius * 0.55)
    equator.set_stroke(color="#7dd3fc", width=1, opacity=0.55).move_to(center)

    trail = DashedLine(center, satellite_tip, dash_length=0.06)
    trail.set_stroke(color="#94a3b8", width=1, opacity=0.5)

    panel_left = Rectangle(width=0.42, height=0.68)
    panel_left.set_fill(color="#1d4ed8", opacity=0.85).set_stroke(color=p["accent"], width=1.4)
    panel_right = panel_left.copy()
    panel_left.move_to([-0.72, 0.0, 0.0])
    panel_right.move_to([0.72, 0.0, 0.0])
    panel_grid = VGroup(
        *[
            Line([x, -0.31, 0.0], [x, 0.31, 0.0]).set_stroke(color="#7dd3fc", width=0.6, opacity=0.8)
            for x in (-0.86, -0.72, -0.58, 0.58, 0.72, 0.86)
        ],
        *[
            Line([x0, y, 0.0], [x1, y, 0.0]).set_stroke(color="#7dd3fc", width=0.6, opacity=0.8)
            for x0, x1 in ((-0.93, -0.51), (0.51, 0.93))
            for y in (-0.14, 0.14)
        ],
    )
    left_arm = Line([-0.28, 0.0, 0.0], [-0.50, 0.0, 0.0]).set_stroke(color="#cbd5e1", width=2)
    right_arm = Line([0.28, 0.0, 0.0], [0.50, 0.0, 0.0]).set_stroke(color="#cbd5e1", width=2)
    body = RoundedRectangle(width=0.58, height=0.38, corner_radius=0.08)
    body.set_fill(color="#f8fafc", opacity=1).set_stroke(color="#0f172a", width=2)
    antenna = Line([0.0, 0.19, 0.0], [0.0, 0.43, 0.0]).set_stroke(color="#f8fafc", width=1.8)
    antenna_tip = Circle(radius=0.065, color="#fbbf24", fill_opacity=1).move_to([0.0, 0.46, 0.0])
    orbiter = VGroup(
        panel_left,
        panel_right,
        panel_grid,
        left_arm,
        right_arm,
        body,
        antenna,
        antenna_tip,
    )
    angle = math.atan2(satellite_tip[1] - center[1], satellite_tip[0] - center[0])
    orbiter.rotate(angle, about_point=ORIGIN).move_to(satellite_tip)
    orbiter_label = Text("ORBITER", font_size=13, color="#e0f2fe")
    orbiter_label.next_to(orbiter, UP, buff=0.12)
    planet_label = Text("KEPLER-01", font_size=16, color="#bae6fd")
    planet_label.next_to(center, DOWN, buff=radius + 0.16)

    return VGroup(
        stars,
        orbit,
        dashed_orbit,
        trail,
        moon,
        moon_crater,
        atmosphere,
        planet,
        continents,
        equator,
        orbiter,
        orbiter_label,
        planet_label,
    )
"""

TEMPLATES: dict[str, str] = {
    "Right triangle": python_object.STARTER,
    "Matrix": MATRIX,
}

# Extra composites shown directly in the Layers panel; the Code page keeps its
# smaller, established New Python object catalog.
LAYER_TEMPLATES: dict[str, str] = {
    **TEMPLATES,
    "Grid": GRID,
    "Labeled vector": LABELED_VECTOR,
    "Orbital satellite": ORBITAL_SATELLITE,
}
