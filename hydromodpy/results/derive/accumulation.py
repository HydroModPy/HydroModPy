"""Accumulation fluxes rebuilt on read, by range, on the descent D of the run.

``accumulation_flux`` routes the local drain outflow down D, and
``release_accumulation_flux`` routes the release flux (every path groundwater
leaves the aquifer by). Both come from the per-cell budget terms and the
stored descent, so neither is written. Every row depends on its own step only,
so a row read alone is the row of a range read.

A run stored before D was has none: D is then rebuilt from the stored top, once
per store. A run with neither D nor a mesh topology serves no accumulation.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import numpy as np

from hydromodpy.core.descent import descent_from_stored_mesh, descent_graph
from hydromodpy.core.field_routing import (
    DRN_TO_MVR_KEYS,
    DownhillGraph,
    accumulate_on_downhill_graph,
    drain_budget_stack_to_positive_outflow,
    drain_stack_with_mover,
    find_drain_budget_key,
    has_release_budget,
    release_flux_stack,
)
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_STORED_D = ("descent_receiver", "descent_surface")
_MESH_TOPOLOGY = ("topography", "face_node_connectivity", "vertices")

_CACHE_SIZE = 4
_graphs: OrderedDict[tuple, DownhillGraph] = OrderedDict()
_graphs_lock = threading.Lock()


def accumulation_flux_available(root: Any) -> bool:
    """Say whether the drain outflow of ``root`` can be routed on a descent."""
    budget = _budget(root)
    if budget is None or "head" not in root:
        return False
    has_drain = find_drain_budget_key(budget) is not None or any(
        key in budget for key in DRN_TO_MVR_KEYS
    )
    return has_drain and _has_route(root)


def release_accumulation_flux_available(root: Any) -> bool:
    """Say whether the release flux of ``root`` can be routed on a descent."""
    budget = _budget(root)
    if budget is None or "head" not in root:
        return False
    return has_release_budget(budget) and _has_route(root)


def accumulation_flux_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return the accumulated drain outflow for steps ``[start, stop)``.

    Raises
    ------
    KeyError
        The run holds no drain budget, or no descent and no mesh topology.
    """
    if not accumulation_flux_available(root):
        raise KeyError("accumulation_flux needs a drain budget and a descent or a mesh topology")
    n_cells = _n_cells(root)
    if int(stop) <= int(start):
        return np.empty((0, n_cells), dtype="float64")
    budget = root["budget"]
    drain_key = find_drain_budget_key(budget)

    def local(first: int, last: int) -> np.ndarray:
        drain = drain_stack_with_mover(budget, drain_key, first, last)
        return drain_budget_stack_to_positive_outflow(drain, n_cells=n_cells)

    return _route(root, local, int(start), int(stop), n_cells)


def release_accumulation_flux_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return the accumulated release flux for steps ``[start, stop)``.

    Raises
    ------
    KeyError
        The run holds no release budget, or no descent and no mesh topology.
    """
    if not release_accumulation_flux_available(root):
        raise KeyError(
            "release_accumulation_flux needs a release budget and a descent or a mesh topology"
        )
    n_cells = _n_cells(root)
    if int(stop) <= int(start):
        return np.empty((0, n_cells), dtype="float64")
    budget = root["budget"]

    def local(first: int, last: int) -> np.ndarray:
        return release_flux_stack(budget, n_cells=n_cells, start=first, stop=last)

    return _route(root, local, int(start), int(stop), n_cells)


def _budget(root: Any) -> Any | None:
    return root["budget"] if "budget" in root else None


def _n_cells(root: Any) -> int:
    return int(root["head"].shape[-1])


def _has_route(root: Any) -> bool:
    """Say whether ``root`` holds a descent of the cells of its head, or a mesh to rebuild one."""
    if "mesh" not in root:
        return False
    mesh = root["mesh"]
    if all(name in mesh for name in _STORED_D):
        return int(np.prod(mesh["descent_receiver"].shape)) == _n_cells(root)
    return all(name in mesh for name in _MESH_TOPOLOGY)


def _route(
    root: Any, local: Callable[[int, int], np.ndarray], start: int, stop: int, n_cells: int
) -> np.ndarray:
    """Route ``local(first, last)`` down D over ``[start, stop)``, in bounded passes.

    The graph is built once and reused by every pass. Every row is routed on
    its own, so the joined passes equal one pass.
    """
    # Late import: virtual_fields imports this module.
    from hydromodpy.results.derive.virtual_fields import _in_passes

    graph = _graph(root, n_cells)

    def routed(first: int, last: int) -> np.ndarray:
        rows = np.asarray(local(first, last), dtype="float64")
        positive = np.maximum(rows.reshape(rows.shape[0], -1), 0.0)
        return accumulate_on_downhill_graph(graph, positive)

    return _in_passes(routed, start, stop, n_cells)


def _graph(root: Any, n_cells: int) -> DownhillGraph:
    """Return the receiver graph of D, built once per store and per D.

    The catalog hands out a fresh handle per step, so the cache keys on the
    store path, or on the handle itself for an in-memory store, and on a digest
    of the arrays the graph is built from: a store rewritten in place misses.
    """
    mesh = root["mesh"]
    if all(name in mesh for name in _STORED_D):
        receiver = np.asarray(mesh["descent_receiver"][:], dtype="int64").reshape(-1)
        surface = np.asarray(mesh["descent_surface"][:], dtype="float64").reshape(-1)
        if receiver.size != n_cells:
            raise ValueError(f"the descent has {receiver.size} cells, expected {n_cells}.")
        key = (_store_id(root), "stored", n_cells, _digest(receiver, surface))
        return _cached(key, lambda: descent_graph(receiver, surface))

    topography = np.asarray(mesh["topography"][:], dtype="float64").reshape(-1)[:n_cells]
    if topography.size != n_cells:
        raise ValueError(f"topography has {topography.size} cells, expected {n_cells}.")
    connectivity = np.asarray(mesh["face_node_connectivity"][:], dtype="int32")
    vertices = np.asarray(mesh["vertices"][:], dtype="float64")
    key = (
        _store_id(root),
        "rebuilt",
        n_cells,
        _digest(topography, connectivity, vertices),
    )

    def build() -> DownhillGraph:
        logger.debug(
            "The run stores no descent: D was rebuilt from the stored top, without "
            "channel pins, constant-head seeds or lakes."
        )
        return descent_from_stored_mesh(topography, connectivity, vertices).metric.graph

    return _cached(key, build)


def _cached(key: tuple, build: Any) -> DownhillGraph:
    with _graphs_lock:
        if key in _graphs:
            _graphs.move_to_end(key)
            return _graphs[key]
    graph = build()
    with _graphs_lock:
        _graphs[key] = graph
        while len(_graphs) > _CACHE_SIZE:
            _graphs.popitem(last=False)
    return graph


def _store_id(root: Any) -> tuple:
    store = getattr(root, "store", None)
    path = getattr(store, "root", None)
    if path is not None:
        return ("path", str(path), str(getattr(root, "path", "")))
    return ("object", id(store if store is not None else root))


def _digest(*arrays: np.ndarray) -> str:
    digest = hashlib.blake2b(digest_size=16)
    for array in arrays:
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


__all__ = [
    "accumulation_flux_available",
    "accumulation_flux_rows",
    "release_accumulation_flux_available",
    "release_accumulation_flux_rows",
]
