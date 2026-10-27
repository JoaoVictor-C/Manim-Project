"""Manim Studio: a visual, timeline-based editor that uses Manim as its engine."""

from importlib.metadata import PackageNotFoundError, version

from . import lifeline

lifeline.limit_native_threads()  # before numpy is imported anywhere: one thread per core is hundreds of MB

try:
    __version__ = version("manim-studio")  # one source of truth: pyproject.toml (P6e)
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"
