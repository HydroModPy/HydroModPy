"""Cell centroids and areas of one sealed run.

A sealed run carries its grid in the ``mesh/`` group of ``fields.zarr``
(vertices and faces, face ``i`` is cell ``i`` of every field array). Nothing
here reads a TOML, a scratch folder or the project index.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison.runtime.run_source import RunSource, open_run_source
from hydromodpy.results.run.contracts import cell_centers, polygon_areas


@dataclass(frozen=True, slots=True)
class CellCentroidTable:
    """Minimal cell-centroid lookup of one run."""

    cell_ids: np.ndarray
    x: np.ndarray
    y: np.ndarray
    area_m2: np.ndarray | None = None
    structured_shape: tuple[int, int] | None = None
    """``(nrow, ncol)`` when the run stored its mesh as a regular grid (rows north
    first), read from the ``mesh/`` group of ``fields.zarr``; ``None`` otherwise."""

    def nearest_cell_id(self, *, x: float, y: float) -> int:
        """Return the cell id whose centroid is closest to ``(x, y)``."""
        distances = np.hypot(self.x - float(x), self.y - float(y))
        if distances.size == 0 or not np.any(np.isfinite(distances)):
            raise ValueError("The mesh of the run has no finite centroid")
        return int(self.cell_ids[int(np.nanargmin(distances))])

    def area_for_cell_id(self, cell_id: int) -> float | None:
        """Return the area for one cell id when the mesh gives it."""
        if self.area_m2 is None or self.area_m2.size != self.cell_ids.size:
            return None
        matches = np.flatnonzero(self.cell_ids == int(cell_id))
        if matches.size == 0:
            return None
        area = float(self.area_m2[int(matches[0])])
        if not np.isfinite(area) or area <= 0.0:
            return None
        return area


def cells_from_run_mesh(store: RunSource, sim_id: str) -> CellCentroidTable | None:
    """Build the cell table from the mesh the run stored in its own ``fields.zarr``.

    Face ``i`` is cell ``i`` of the field arrays. Returns ``None`` when the run
    stored no mesh (a lumped run).
    """
    try:
        sz = store.open_zarr(sim_id)
    except FileNotFoundError:
        # A lumped run has no fields store, so no grid to read.
        return None
    try:
        mesh = sz.root.get("mesh")
        if mesh is None or "vertices" not in mesh or "face_node_connectivity" not in mesh:
            return None
        vertices = np.asarray(mesh["vertices"][:], dtype=float)
        faces = np.asarray(mesh["face_node_connectivity"][:], dtype=np.int64)
        face_x = mesh["face_x"][:] if "face_x" in mesh else None
        face_y = mesh["face_y"][:] if "face_y" in mesh else None
        raw_shape = mesh.attrs.get("structured_shape")
    finally:
        sz.close()
    if vertices.ndim != 2 or faces.ndim != 2 or faces.shape[0] == 0:
        return None
    centers = cell_centers(vertices, faces, face_x, face_y)
    return CellCentroidTable(
        cell_ids=np.arange(faces.shape[0], dtype=int),
        x=centers[:, 0],
        y=centers[:, 1],
        area_m2=polygon_areas(vertices, faces),
        structured_shape=None if raw_shape is None else (int(raw_shape[0]), int(raw_shape[1])),
    )


def resolve_run_cells(
    store: RunSource | None,
    sim_id: str | None,
    *,
    expected_size: int | None = None,
) -> CellCentroidTable | None:
    """Return the cells of one run, or None when the run stored no mesh.

    ``expected_size`` refuses a grid whose cell count is not the field's.
    """
    if store is None or sim_id is None:
        return None
    cells = cells_from_run_mesh(store, sim_id)
    if cells is None or (expected_size is not None and cells.cell_ids.size != expected_size):
        return None
    return cells


def resolve_summary_cells(summary: Mapping[str, Any]) -> CellCentroidTable | None:
    """Load the cells of the run a simulation summary names by ``run_dir``."""
    source = open_run_source(summary)
    if source is None:
        return None
    with source:
        return resolve_run_cells(source, source.sim_id)


__all__ = (
    "CellCentroidTable",
    "cells_from_run_mesh",
    "resolve_run_cells",
    "resolve_summary_cells",
)
