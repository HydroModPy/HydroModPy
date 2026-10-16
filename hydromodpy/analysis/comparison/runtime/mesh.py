"""Cell centroids, areas and elevations of one sealed run.

A sealed run carries its grid twice at most: ``mesh/`` in ``fields.zarr``
(vertices and faces, face ``i`` is cell ``i`` of every field array) and, when
the mesh was not reproducible, the exchange bundle the run copied into its own
``mesh/`` folder (it adds storage and elevations). Both live in the run
directory; nothing here reads a TOML, a scratch folder or the project index.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison.runtime.run_source import RunSource, open_run_source
from hydromodpy.core.logging import get_logger
from hydromodpy.results.run.contracts import cell_centers, polygon_areas

logger = get_logger(__name__)

RUN_MESH_BUNDLE_RELPATH = Path("mesh") / "mesh_catchment_bundle"
"""Exchange bundle a run copies into its own directory when its mesh is not reproducible."""


@dataclass(frozen=True, slots=True)
class CellCentroidTable:
    """Minimal cell-centroid lookup of one run."""

    cell_ids: np.ndarray
    x: np.ndarray
    y: np.ndarray
    area_m2: np.ndarray | None = None
    storage_coefficient: np.ndarray | None = None
    z_top: np.ndarray | None = None
    z_bottom: np.ndarray | None = None
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

    def storage_for_cell_id(self, cell_id: int) -> float | None:
        """Return the storage coefficient for one cell id when available."""
        if self.storage_coefficient is None or self.storage_coefficient.size != self.cell_ids.size:
            return None
        matches = np.flatnonzero(self.cell_ids == int(cell_id))
        if matches.size == 0:
            return None
        storage = float(self.storage_coefficient[int(matches[0])])
        if not np.isfinite(storage):
            return None
        return storage

    def vertical_bounds_for_cell_id(self, cell_id: int) -> tuple[float, float] | None:
        """Return ``(top, bottom)`` elevations for one cell id when available."""
        if (
            self.z_top is None
            or self.z_bottom is None
            or self.z_top.size != self.cell_ids.size
            or self.z_bottom.size != self.cell_ids.size
        ):
            return None
        matches = np.flatnonzero(self.cell_ids == int(cell_id))
        if matches.size == 0:
            return None
        index = int(matches[0])
        top = float(self.z_top[index])
        bottom = float(self.z_bottom[index])
        if not (np.isfinite(top) and np.isfinite(bottom)):
            return None
        return top, bottom


def _finite_or_none(values: list[float], size: int) -> np.ndarray | None:
    array = np.asarray(values, dtype=float)
    if array.size != size or not np.any(np.isfinite(array)):
        return None
    return array


def bundle_cells_from_dir(bundle_dir: Path) -> CellCentroidTable | None:
    """Read ``cells.csv`` of a mesh exchange bundle, or None when it is absent."""
    cells_path = bundle_dir / "cells.csv"
    if not cells_path.exists():
        return None

    cell_ids: list[int] = []
    xs: list[float] = []
    ys: list[float] = []
    areas: list[float] = []
    storage_coefficients: list[float] = []
    z_tops: list[float] = []
    z_bottoms: list[float] = []
    with cells_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                cell_id = int(row["cell_id"])
                x = float(row["centroid_x"])
                y = float(row["centroid_y"])
            except (KeyError, TypeError, ValueError):
                # A malformed line names no cell; the others still describe the grid.
                continue
            cell_ids.append(cell_id)
            xs.append(x)
            ys.append(y)
            areas.append(_csv_float(row.get("area_m2")))
            storage_coefficients.append(_csv_float(row.get("storage_coefficient")))
            z_tops.append(
                _csv_float(row.get("z_top_centroid") or row.get("z_top_mean") or row.get("z_top"))
            )
            z_bottoms.append(
                _csv_float(
                    row.get("z_bottom_centroid") or row.get("z_bottom_mean") or row.get("z_bottom")
                )
            )

    if not cell_ids:
        return None
    size = len(cell_ids)
    return CellCentroidTable(
        cell_ids=np.asarray(cell_ids, dtype=int),
        x=np.asarray(xs, dtype=float),
        y=np.asarray(ys, dtype=float),
        area_m2=_finite_or_none(areas, size),
        storage_coefficient=_finite_or_none(storage_coefficients, size),
        z_top=_finite_or_none(z_tops, size),
        z_bottom=_finite_or_none(z_bottoms, size),
    )


def _csv_float(value: Any) -> float:
    if value in (None, ""):
        return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


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


def _fits(cells: CellCentroidTable | None, expected_size: int | None) -> bool:
    return cells is not None and (expected_size is None or cells.cell_ids.size == expected_size)


def resolve_bundle_cells(
    run_folder: Path,
    *,
    expected_size: int | None = None,
    store: RunSource | None = None,
    sim_id: str | None = None,
) -> CellCentroidTable | None:
    """Load the cell centroids of one run directory.

    The bundle the run copied into ``mesh/`` comes first: it also carries
    storage and elevations. The mesh stored in ``fields.zarr`` comes next.
    ``expected_size`` refuses a grid whose cell count is not the field's.
    """
    bundle_cells = bundle_cells_from_dir(Path(run_folder) / RUN_MESH_BUNDLE_RELPATH)
    if _fits(bundle_cells, expected_size):
        return bundle_cells
    if store is not None and sim_id is not None:
        stored_cells = cells_from_run_mesh(store, sim_id)
        if _fits(stored_cells, expected_size):
            return stored_cells
    return None


def resolve_summary_cells(summary: Mapping[str, Any]) -> CellCentroidTable | None:
    """Load the cells of the run a simulation summary names by ``run_dir``."""
    source = open_run_source(summary)
    if source is None:
        return None
    with source:
        return resolve_bundle_cells(source.run_dir, store=source, sim_id=source.sim_id)


__all__ = (
    "RUN_MESH_BUNDLE_RELPATH",
    "CellCentroidTable",
    "bundle_cells_from_dir",
    "cells_from_run_mesh",
    "resolve_bundle_cells",
    "resolve_summary_cells",
)
