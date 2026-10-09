"""Qt test helpers shared by the UI tests."""

from __future__ import annotations

from manim_studio.core.schema import Spec
from manim_studio.core.warm import warm_key
from manim_studio.ui.worker_process import WorkerClient


class FakeWorker(WorkerClient):
    """Records requests; the test decides when and how each one is answered."""

    def __init__(self, available: bool = True) -> None:
        super().__init__()
        self._available = available
        self.requests: dict[int, str] = {}

    @property
    def available(self) -> bool:
        return self._available

    def request(self, request_id: int, spec_json: str) -> None:
        self.requests[request_id] = spec_json

    def reply(self, spec: Spec, ok: bool = True, error: str = "") -> None:
        key = warm_key(spec)
        request_id = next(i for i, k in self.requests.items() if k == key)
        del self.requests[request_id]
        self.replied.emit(request_id, ok, error)
