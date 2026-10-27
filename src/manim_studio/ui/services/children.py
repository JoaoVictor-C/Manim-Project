"""Starting the editor's helper processes, and ending all of them (``manim_studio.lifeline``).

Every service that runs a helper (the build worker, the frame renderer, code renderers, exports, the voice and
import helpers) builds its environment with ``environment()`` and starts its process with ``start()``:

* ``environment()`` tells the helper which editor started it (``MANIM_STUDIO_EDITOR_PID``), so that it ends
  when the editor does, and says it speaks UTF-8;
* ``start()`` puts the new process in the editor's job (Windows), where the operating system ends it when the
  editor's process ends, and remembers it (weakly) so that ``stop_all`` can end every one still running.

``install(app)`` makes ``stop_all`` run when the application quits: a service whose own ``stop`` was never
called (the window was not closed the usual way) cannot leave a helper behind.
"""

from __future__ import annotations

import time
import weakref

import shiboken6
from PySide6.QtCore import QCoreApplication, QProcess, QProcessEnvironment

from ... import lifeline

_started: list[weakref.ReferenceType[QProcess]] = []


def environment(**extra: str) -> QProcessEnvironment:
    """A helper's environment: this process's, plus UTF-8 text, the editor's id and anything in ``extra``."""
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONUTF8", "1")
    for name, value in {**lifeline.editor_environment(), **extra}.items():
        env.insert(name, value)
    return env


def start(process: QProcess) -> None:
    """Start ``process`` and tie it to the editor's life."""
    process.start()
    if process.state() == QProcess.ProcessState.NotRunning:
        return
    lifeline.adopt(int(process.processId()))
    _started[:] = [ref for ref in _started if ref() is not None]
    _started.append(weakref.ref(process))


def running() -> list[QProcess]:
    """The helpers started with ``start`` that are still running."""
    found = []
    for ref in _started:
        process = ref()
        if (
            process is not None
            and shiboken6.isValid(process)
            and process.state() != QProcess.ProcessState.NotRunning
        ):
            found.append(process)
    return found


def ask_all_to_stop() -> None:
    """Close the input of every running helper: the ones that read it end by themselves, all at once, so that
    stopping them one after another does not wait for each in turn."""
    for process in running():
        process.closeWriteChannel()


def stop_all(grace_ms: int = 1500) -> None:
    """End every helper still running: close its input, wait up to ``grace_ms`` for all together, then end
    what is left together with what it started."""
    left = running()
    for process in left:
        process.closeWriteChannel()
    deadline = time.monotonic() + grace_ms / 1000
    for process in left:
        if shiboken6.isValid(process):
            process.waitForFinished(max(0, round((deadline - time.monotonic()) * 1000)))
    for process in left:
        if shiboken6.isValid(process) and process.state() != QProcess.ProcessState.NotRunning:
            lifeline.kill_tree(int(process.processId()))
    _started.clear()


def install(app: QCoreApplication) -> None:
    """End every helper when the application quits."""
    app.aboutToQuit.connect(stop_all)
