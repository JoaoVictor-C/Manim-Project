"""Ready-made code for Python objects (P10): the Code page's "New Python object" menu.

Each template is the source a user would write: ``PARAMS`` (read without running it) and
``build(p)``. They are plain Manim, so they double as examples to copy from.
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

TEMPLATES: dict[str, str] = {
    "Right triangle": python_object.STARTER,
    "Matrix": MATRIX,
}
