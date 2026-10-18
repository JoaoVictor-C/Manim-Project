"""Build a 150-second Manim Studio lesson on matrices."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "matrices.json"

SLIDES = [
    ("A language for structure", "A matrix is a rectangular arrangement of numbers.", "Rows run across; columns run down.", "A = [ 2   1 ]\n    [ 0   3 ]", "Think of a matrix as a compact way to store relationships."),
    ("Read its shape", "Count rows first, then columns.", "This example has 2 rows and 3 columns: a 2 by 3 matrix.", "B = [ 4   1   7 ]\n    [ 2   0   5 ]", "The entry in row 2, column 3 is 5. We write that position as b₂₃."),
    ("Where matrices appear", "A spreadsheet, a pixel grid, and a table of measurements are all matrix-shaped.", "Each position has a meaning set by its row and column.", "[ red   green ]\n[ blue  white ]", "For an image, each cell can store a pixel value. For data, it can store a measurement."),
    ("Add matching entries", "Matrices can be added when they have the same shape.", "Add each number to the number in the same position.", "[ 1   2 ]   [ 4   0 ]   [ 5   2 ]\n[ 3   1 ] + [ 2   6 ] = [ 5   7 ]", "Here, top left is 1 plus 4, and bottom right is 1 plus 6."),
    ("Scale every entry", "Multiplying a matrix by a number scales every entry.", "This is called scalar multiplication.", "3 [ 1   2 ] = [ 3   6 ]\n  [ 0  -1 ]   [ 0  -3 ]", "A scalar changes the values while keeping the same rows and columns."),
    ("Multiply row by column", "Matrix multiplication combines rows of the first matrix with columns of the second.", "Multiply matching entries, then add the products.", "[ 1   2 ] [ 3 ] = [ 1·3 + 2·4 ] = [ 11 ]\n          [ 4 ]", "The result is one number: the dot product of that row and column."),
    ("Order matters", "A 2 by 3 matrix times a 3 by 1 matrix gives a 2 by 1 matrix.", "The inside dimensions must match; the outside dimensions give the answer's shape.", "(2 × 3) · (3 × 1)  →  (2 × 1)", "If the inside numbers do not match, that multiplication is not defined."),
    ("Matrices move points", "A matrix can transform a vector: rotate, stretch, reflect, or shear it.", "For a quarter-turn, (x, y) becomes (-y, x).", "[ 0  -1 ] [ x ] = [ -y ]\n[ 1   0 ] [ y ]   [  x ]", "Apply this matrix to (2, 1), and the point moves to (-1, 2)."),
    ("Transform, then transform", "Multiplying two transformation matrices combines their actions.", "The rightmost transformation acts first.", "point  →  rotate  →  stretch\n       same as one combined matrix", "This lets graphics and robotics build complex motion from simple steps."),
    ("The big idea", "Matrices organize numbers so operations can act on many values at once.", "Know the shape. Match positions. For multiplication, pair rows with columns.", "MATRIX  =  structure  +  action", "You now know how to read a matrix, add and scale one, multiply matrices, and use them to transform space."),
]

BG = "#081426"
WHITE = "#edf4ff"
CYAN = "#54d6ff"
MUTED = "#a9bbd2"


def layer(layer_id: str, name: str, text: str, y: float, color: str, start: float, end: float, size: int):
    return {
        "id": layer_id,
        "name": name,
        "spec": {"type": "Text", "params": {"text": text, "font_size": size}, "style": {"fill": color}},
        "base": {"position": [0, y], "scale": 1, "rotation": 0, "opacity": 1},
        "lifetime": {"in": start, "out": end},
        "tracks": {},
        "clips": [
            {"id": f"{layer_id}-in", "kind": "FadeIn", "start": start, "duration": 0.45, "ease": None, "params": {}, "to_layer": None},
            {"id": f"{layer_id}-out", "kind": "FadeOut", "start": end - 0.45, "duration": 0.45, "ease": None, "params": {}, "to_layer": None},
        ],
    }


def build() -> dict:
    layers = []
    subtitles = []
    for index, (title, line1, line2, visual, narration) in enumerate(SLIDES):
        start, end = index * 15.0, (index + 1) * 15.0
        prefix = f"s{index + 1}"
        layers.extend([
            layer(f"{prefix}-kicker", "SECTION", f"MATRICES  /  {index + 1:02d}", 3.12, CYAN, start, end, 21),
            layer(f"{prefix}-title", title, title, 2.25, WHITE, start, end, 39),
            layer(f"{prefix}-line1", "Concept", line1, 1.12, WHITE, start, end, 27),
            layer(f"{prefix}-line2", "Detail", line2, 0.25, MUTED, start, end, 25),
            layer(f"{prefix}-visual", "Matrix / diagram", visual, -1.45, CYAN, start, end, 29),
        ])
        subtitles.append({"id": f"cap-{index + 1}", "start": start + 0.3, "end": end - 0.3, "text": narration})
    return {
        "schema_version": 1,
        "canvas": {"width_px": 1280, "height_px": 720, "fps": 30, "background": BG, "frame_height": 8.0, "duration": 150.0},
        "layers": layers,
        "subtitles": subtitles,
        "subtitle_style": {"font_size": 25, "y": -3.42, "colour": WHITE, "band": True, "band_colour": "#020817", "band_opacity": 0.88, "fade": 0.25, "burn_in": True, "max_width": 12.0},
        "markers": [{"id": f"chapter-{i + 1}", "t": i * 15.0, "name": slide[0], "colour": CYAN} for i, slide in enumerate(SLIDES)],
    }


if __name__ == "__main__":
    project = build()
    OUTPUT.write_text(json.dumps(project, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(project['layers'])} layers, {project['canvas']['duration']:.0f}s)")
