# 0003. Stack: Python 3.13, uv, PySide6, pinned Manim behind an adapter

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

The engine is Manim (Python). Options for the editor were a Python desktop UI in
the same process, or a web UI (Electron/Tauri) talking to a Python sidecar.
The evaluator relies on Manim internals (`begin`, `interpolate`, `finish`, Cairo
camera), which may change between releases.

## Decision

- **Python 3.13**, managed with **uv**. 3.12 is not supported: it decodes `.pth`
  files with the legacy code page, which breaks the editable install under
  non-ASCII paths (seen on Windows).
- **PySide6 (Qt 6)** for the UI, in the same process as Manim — no IPC.
- **Manim CE pinned exactly** (`manim==0.22.0`). All knowledge of Manim
  mobject/animation classes lives in `core/adapter.py`; other modules use only
  the generic `Mobject` API.
- **pydantic** for the document, **numpy** for transforms, **PyAV** (bundled
  with Manim) for video encoding.

## Consequences

- One language, one process, no protocol to maintain.
- Upgrading Manim = bump the pin, run the full test suite, fix the adapter.
- Heavy work (export) runs in a subprocess to keep the UI responsive and avoid
  Manim's global `config`.

## Alternatives considered

- **Electron/Tauri + Python sidecar** — modern UI tooling, but two languages and
  an IPC protocol for every frame's geometry.
- **Floating Manim version** — silent breakage of the evaluator.

## Evidence

- Setup issues and workarounds: [../dev/setup.md](../dev/setup.md)
