# Third-party software

Manim Studio is released under the MIT license (see [LICENSE](LICENSE)). It is
distributed as a Python package that *depends on* the libraries below; it does not
bundle them. Installing it (for example with `uv tool install`) downloads each one
under its own license. Versions are those pinned in `uv.lock` when this file was
written (2026-10-15).

## Direct dependencies

| package | version | license | used for |
|---|---|---|---|
| [Manim Community](https://www.manim.community/) | 0.22.0 | MIT | the animation engine: every object, animation and frame |
| [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python) | 6.12.0 | LGPL-3.0-only (or GPL-2.0/3.0) | the editor's window, panels and canvas |
| [QtAwesome](https://github.com/spyder-ide/qtawesome) | 1.4.2 | MIT | icons; it ships the [Phosphor](https://phosphoricons.com/) icon font (MIT) |
| [NumPy](https://numpy.org/) | 2.5.3 | BSD-3-Clause (and 0BSD, MIT, Zlib, CC0-1.0 parts) | geometry and pixel buffers |
| [Pillow](https://python-pillow.org/) | 12.3.0 | MIT-CMU | images |
| [pydantic](https://docs.pydantic.dev/) | 2.14.0 | MIT | the project file format and its validation |

## Notable indirect dependencies (through Manim)

| package | version | license |
|---|---|---|
| PyAV (with its FFmpeg libraries) | 19.0.1 | BSD-3-Clause; the FFmpeg libraries in its wheels are LGPL |
| pycairo (with Cairo) | 1.29.2 | LGPL-2.1-only or MPL-1.1 |
| ManimPango (with Pango) | 0.7.0 | MIT (Pango: LGPL) |
| SciPy | 1.18.1 | BSD-3-Clause |
| moderngl | 5.13.0 | MIT |
| skia-pathops | 0.9.2 | BSD-3-Clause |
| svgelements | 1.9.6 | MIT |
| mapbox-earcut | 2.1.0 | ISC |
| networkx | 3.7 | BSD-3-Clause |
| pydub, srt, rich, isosurfaces, screeninfo, beautifulsoup4 | - | MIT |
| click, cloup | - | BSD-3-Clause |
| Pygments, decorator | - | BSD-2-Clause |
| tqdm | 4.70.1 | MPL-2.0 and MIT |
| watchdog | 6.0.0 | Apache-2.0 |
| audioop-lts | 0.2.2 | PSF-2.0 |

## Not installed with Manim Studio

- **A LaTeX distribution** (MiKTeX or TeX Live) draws `MathTex` and `Tex` objects. Install
  it yourself; it keeps its own licenses.

## The LGPL libraries

Qt (PySide6), Cairo, Pango and the FFmpeg libraries are LGPL. Manim Studio uses them only
as separately installed, dynamically loaded libraries, so you can replace any of them
with your own build of a compatible version.
