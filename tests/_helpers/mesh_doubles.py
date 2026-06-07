"""Minimal mesh doubles shared by Boussinesq solver unit tests.

These dataclasses are test-only stand-ins for ``BoussinesqMesh``. They expose
exactly the attributes the assembly, jacobian, and runtime functions read, so
finite-difference verification tests can build tiny meshes without the full
mesh builder. Not public API.

``_MiniMesh`` is the union of every field used across the solver unit suites.
Unset fields default to empty arrays, so each test only sets what it needs.
``n_cells`` and ``n_edges`` derive from whichever core array is populated, which
keeps cell-only meshes (no edges) and bound-only meshes (no ``cell_area_m2``)
working with the same class. ``line_mesh`` is a 1D convenience factory for the
steady-state suites.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _empty_float() -> np.ndarray:
    return np.asarray([], dtype=float)


def _empty_int() -> np.ndarray:
    return np.asarray([], dtype=int)


@dataclass
class _MiniMesh:
    """Rich minimal mesh covering the union of solver-test fields."""

    cell_area_m2: np.ndarray = field(default_factory=_empty_float)
    z_top_m: np.ndarray = field(default_factory=_empty_float)
    z_bottom_m: np.ndarray = field(default_factory=_empty_float)
    hydraulic_conductivity_m_s: np.ndarray = field(default_factory=_empty_float)
    storage_coefficient: np.ndarray = field(default_factory=_empty_float)
    edge_ids: np.ndarray = field(default_factory=_empty_int)
    edge_cell_a: np.ndarray = field(default_factory=_empty_int)
    edge_cell_b: np.ndarray = field(default_factory=_empty_int)
    edge_length_m: np.ndarray = field(default_factory=_empty_float)
    edge_distance_m: np.ndarray = field(default_factory=_empty_float)
    edge_midpoint_distance_to_cell_a_m: np.ndarray = field(default_factory=_empty_float)
    edge_midpoint_distance_to_cell_b_m: np.ndarray = field(default_factory=_empty_float)

    @property
    def n_cells(self) -> int:
        for array in (self.cell_area_m2, self.z_top_m, self.z_bottom_m):
            if array.size != 0:
                return int(array.size)
        return 0

    @property
    def n_edges(self) -> int:
        return int(self.edge_ids.size)


def line_mesh(
    z_bottom: list[float],
    *,
    k_m_s: float = 1.0e-5,
    storage_coefficient: float | None = None,
) -> _MiniMesh:
    """Build a 1D line ``_MiniMesh`` from per-cell bottom elevations.

    Cells sit on a unit grid; the top is 10 m above the bottom. Edges connect
    consecutive cells. Pass ``storage_coefficient`` to populate the transient
    storage field; leave it ``None`` for steady dry-equilibrium meshes.
    """

    n_cells = len(z_bottom)
    n_edges = max(n_cells - 1, 0)
    bottom = np.asarray(z_bottom, dtype=float)
    if storage_coefficient is None:
        storage = _empty_float()
    else:
        storage = np.full(n_cells, float(storage_coefficient), dtype=float)
    return _MiniMesh(
        cell_area_m2=np.ones(n_cells, dtype=float),
        z_bottom_m=bottom,
        z_top_m=bottom + 10.0,
        hydraulic_conductivity_m_s=np.full(n_cells, float(k_m_s), dtype=float),
        storage_coefficient=storage,
        edge_ids=np.arange(n_edges, dtype=int),
        edge_cell_a=np.arange(n_edges, dtype=int),
        edge_cell_b=np.arange(1, n_cells, dtype=int),
        edge_length_m=np.ones(n_edges, dtype=float),
        edge_distance_m=np.ones(n_edges, dtype=float),
        edge_midpoint_distance_to_cell_a_m=0.5 * np.ones(n_edges, dtype=float),
        edge_midpoint_distance_to_cell_b_m=0.5 * np.ones(n_edges, dtype=float),
    )
