"""One pass over a project's layers, so tree questions cost O(1) instead of a scan (B66).

``Project.layer``, ``children``, ``descendants``, ``ancestors`` and ``lifetime`` each walk the whole
layer list (and ``lifetime`` rebuilds ``morph_sources`` on top). Asked once per layer - as the
timeline's rebuild and the Layers panel do - that is quadratic: 150 ms for 295 layers (B64). A
``LayerIndex`` maps ids, parents and morph targets once and answers the same questions from the
maps, with the same results and the same order (parents before children, siblings in list order).

It describes the project it was built from, so build one per snapshot (projects are replaced by
edits, never changed in place) and drop it with the snapshot.
"""

from __future__ import annotations

from .schema import Layer, Project, infer_lifetime


class LayerIndex:
    def __init__(self, project: Project) -> None:
        self.project = project
        self._by_id: dict[str, Layer] = {}
        self._kids: dict[str | None, list[Layer]] = {}
        for layer in project.layers:
            self._by_id.setdefault(layer.id, layer)
            self._kids.setdefault(layer.parent_id, []).append(layer)
        self.morph_sources = project.morph_sources()
        self._lifetimes: dict[str, tuple[float, float]] = {}

    def layer(self, layer_id: str) -> Layer:
        try:
            return self._by_id[layer_id]
        except KeyError:
            raise KeyError(layer_id) from None

    def __contains__(self, layer_id: str) -> bool:
        return layer_id in self._by_id

    def roots(self) -> list[Layer]:
        return list(self._kids.get(None, ()))

    def children(self, layer_id: str) -> list[Layer]:
        return list(self._kids.get(layer_id, ()))

    def descendants(self, layer_id: str) -> list[Layer]:
        """Parts under ``layer_id``, parents before children, siblings in list order."""
        out: list[Layer] = []
        stack = list(reversed(self._kids.get(layer_id, ())))
        while stack:
            layer = stack.pop()
            out.append(layer)
            stack.extend(reversed(self._kids.get(layer.id, ())))
        return out

    def ancestors(self, layer_id: str) -> list[Layer]:
        """Parent first, root last."""
        out, layer = [], self.layer(layer_id)
        while layer.parent_id is not None:
            layer = self.layer(layer.parent_id)
            out.append(layer)
        return out

    def depth(self, layer_id: str) -> int:
        """0 for an object, 1 for its parts, 2 for parts of parts..."""
        depth, layer = 0, self.layer(layer_id)
        while layer.parent_id is not None:
            layer = self.layer(layer.parent_id)
            depth += 1
        return depth

    def root_of(self, layer_id: str) -> Layer:
        layer = self.layer(layer_id)
        while layer.parent_id is not None:
            layer = self.layer(layer.parent_id)
        return layer

    def lifetime(self, layer_id: str) -> tuple[float, float]:
        """When a layer is visible; a part's lifetime is clamped to its parent's (ADR 0012)."""
        known = self._lifetimes.get(layer_id)
        if known is not None:
            return known
        layer = self.layer(layer_id)
        start, end = infer_lifetime(layer, self.morph_sources.get(layer_id))
        if layer.parent_id is not None:
            parent_start, parent_end = self.lifetime(layer.parent_id)
            start, end = max(start, parent_start), min(end, parent_end)
        self._lifetimes[layer_id] = (start, end)
        return start, end

    def rows(self) -> list[Layer]:
        """Timeline rows: objects front-most first, each followed by its parts (ADR 0012)."""
        return [x for root in reversed(self.roots()) for x in (root, *self.descendants(root.id))]
