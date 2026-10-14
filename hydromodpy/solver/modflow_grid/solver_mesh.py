"""Unified solver mesh abstraction for structured and unstructured grids.

``SolverMesh`` is the single grid object that traverses the entire solver
pipeline.  It wraps a ``PlanarCellMesh`` (planar geometry, centres, derived
areas and adjacency, cell families) together with layer elevations, providing
everything the solver needs to build MODFLOW DIS or DISV packages.

All solver code receives a ``SolverMesh`` - never raw FloPy grids or
explicit ``(nlay, nrow, ncol)`` tuples.  The structured/unstructured
distinction is handled internally and exposed via ``is_structured``.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

import numpy as np

from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh


@dataclass(frozen=True)
class SolverMesh:
    """Solver-agnostic 2D+layers mesh.

    The mesh is PRISMATIC (vertically extruded): every layer shares the same
    planar cells, with per-cell ``top`` / ``botm`` elevations. This is the data
    model behind MODFLOW DIS (structured planar) and DISV (any planar topology):
    ``to_dis_kwargs`` and ``to_disv_kwargs`` both export it. It does NOT represent
    a fully unstructured 3D grid (DISU: per-layer-varying footprints, vertical
    refinement, arbitrary node connectivity); that would need a non-prismatic mesh
    type and an explicit connectivity export, added alongside this one.

    Parameters
    ----------
    cell_mesh : PlanarCellMesh
        Planar cells with their centres, derived geometry and families.
    top : ndarray, shape (n_cells,)
        Top elevation per cell.
    botm : ndarray, shape (nlay, n_cells)
        Bottom elevation per cell per layer.
    inactive_mask : ndarray, shape (nlay, n_cells)
        Boolean mask where True = inactive cell.
    """

    cell_mesh: PlanarCellMesh
    top: np.ndarray
    botm: np.ndarray
    inactive_mask: np.ndarray

    def __post_init__(self) -> None:
        n_cells = self.cell_mesh.n_cells
        top = np.asarray(self.top, dtype=float).reshape(-1)
        if top.size != n_cells:
            raise ValueError(f"top must have {n_cells} values, got {top.size}")
        object.__setattr__(self, "top", top)

        botm = np.asarray(self.botm, dtype=float)
        if botm.ndim == 1:
            botm = botm.reshape(1, -1)
        if botm.ndim != 2 or botm.shape[1] != n_cells:
            raise ValueError(f"botm must have shape (nlay, {n_cells}), got {botm.shape}")
        object.__setattr__(self, "botm", botm)

        mask = np.asarray(self.inactive_mask, dtype=bool)
        if mask.shape != botm.shape:
            raise ValueError(f"inactive_mask must have shape {botm.shape}, got {mask.shape}")
        object.__setattr__(self, "inactive_mask", mask)

    # -- Properties -----------------------------------------------------------

    @property
    def planar_mesh(self) -> HydroMesh:
        """The planar ``HydroMesh`` of the cell mesh."""
        return self.cell_mesh.mesh

    @property
    def n_cells(self) -> int:
        """Number of planar cells."""
        return self.cell_mesh.n_cells

    @property
    def nlay(self) -> int:
        """Number of layers."""
        return int(self.botm.shape[0])

    @property
    def is_structured(self) -> bool:
        """True when the planar mesh is a regular quadrilateral grid."""
        return self.cell_mesh.structured_shape is not None

    @property
    def structured_shape(self) -> tuple[int, int] | None:
        """Return (nrow, ncol) if structured, else None."""
        return self.cell_mesh.structured_shape

    @property
    def nrow(self) -> int:
        """Number of rows (raises if not structured)."""
        shape = self.structured_shape
        if shape is None:
            raise ValueError("nrow is only available for structured grids")
        return shape[0]

    @property
    def ncol(self) -> int:
        """Number of columns (raises if not structured)."""
        shape = self.structured_shape
        if shape is None:
            raise ValueError("ncol is only available for structured grids")
        return shape[1]

    # -- Geometry helpers -----------------------------------------------------

    def cell_centroids(self) -> np.ndarray:
        """Return cell centers as ndarray (n_cells, 2).

        These are the ``centers`` of the cell mesh, the one centre rule of every
        consumer: the Voronoi generators written to the DISV file, so LAK
        connection lengths, the watershed DRN mask and PRT release points use
        the centers MODFLOW 6 sees, or the vertex mean on a regular grid and on
        triangles.
        """
        return self.cell_mesh.centers.copy()

    def cell_areas(self) -> np.ndarray:
        """Return area of each planar cell."""
        return self.cell_mesh.geometry.areas.copy()

    def face_adjacency(self) -> list[set[int]]:
        """Return, for each cell, the set of cells that share a face with it.

        Built from the CSR adjacency of the derived geometry, once per mesh;
        each call returns fresh sets the caller may modify.
        """
        return self.cell_mesh.geometry.adjacency_sets()

    @property
    def characteristic_length(self) -> float:
        """Mean cell edge length (sqrt of mean area)."""
        return float(sqrt(float(np.mean(self.cell_areas()))))

    def layer_thicknesses(self) -> np.ndarray:
        """Return thickness per cell per layer, shape (nlay, n_cells)."""
        tops = np.vstack([self.top.reshape(1, -1), self.botm[:-1]])
        return tops - self.botm

    def layer_center_depths(self) -> np.ndarray:
        """Return depth of layer centers below top, shape (nlay, n_cells), never negative."""
        tops = np.vstack([self.top.reshape(1, -1), self.botm[:-1]])
        centers_z = 0.5 * (tops + self.botm)
        return np.maximum(0.0, self.top.reshape(1, -1) - centers_z)

    def idomain(self) -> np.ndarray:
        """Return MODFLOW IDOMAIN, shape (nlay, n_cells): 1 active, 0 inactive."""
        return np.where(self.inactive_mask, 0, 1).astype(int)

    # -- Reshape helpers (structured only) ------------------------------------

    def reshape_to_grid(self, flat_values: np.ndarray) -> np.ndarray:
        """Reshape flat (n_cells,) or (nlay, n_cells) to grid arrays.

        For structured: (n_cells,) -> (nrow, ncol), (nlay, n_cells) -> (nlay, nrow, ncol).
        For unstructured: identity (no reshape).
        Preserves the input dtype (float, bool, int, etc.).
        """
        arr = np.asarray(flat_values)
        if not self.is_structured:
            return arr
        nrow, ncol = self.structured_shape
        if arr.ndim == 1:
            return arr.reshape(nrow, ncol)
        if arr.ndim == 2:
            return arr.reshape(arr.shape[0], nrow, ncol)
        return arr

    def flatten_from_grid(self, grid_values: np.ndarray) -> np.ndarray:
        """Flatten (nrow, ncol) or (nlay, nrow, ncol) to (n_cells,) or (nlay, n_cells).

        For unstructured: identity.
        """
        arr = np.asarray(grid_values)
        if not self.is_structured:
            return arr
        if arr.ndim == 2:
            return arr.reshape(-1)
        if arr.ndim == 3:
            return arr.reshape(arr.shape[0], -1)
        return arr

    def structured_delr_delc(self) -> tuple[np.ndarray, np.ndarray]:
        """Compute delr and delc from structured mesh vertices.

        Returns (delr, delc) where delr is column widths and delc is row heights.
        Both are always positive (absolute cell sizes).
        Raises if not structured.
        """
        if not self.is_structured:
            raise ValueError("delr/delc only available for structured grids")
        nrow, ncol = self.structured_shape
        verts = np.asarray(self.planar_mesh.vertices, dtype=float)
        # Vertices are in row-major order: (nrow+1)*(ncol+1) nodes
        x = verts[:, 0].reshape(nrow + 1, ncol + 1)
        y = verts[:, 1].reshape(nrow + 1, ncol + 1)
        # Use abs() because vertex ordering may go north→south (y decreasing)
        # and MODFLOW expects positive cell widths.
        delr = np.abs(np.diff(x[0, :]))  # column widths from first row
        delc = np.abs(np.diff(y[:, 0]))  # row heights from first column
        return np.asarray(delr, dtype=float), np.asarray(delc, dtype=float)

    # -- Structured-grid compatibility properties ------------------------------
    # These properties allow SolverMesh to be passed where an sgrid-like
    # object is expected.
    # They raise for unstructured meshes.

    @property
    def delr(self) -> np.ndarray:
        """Column widths (structured only). Raises if not structured."""
        return self.structured_delr_delc()[0]

    @property
    def delc(self) -> np.ndarray:
        """Row heights (structured only). Raises if not structured."""
        return self.structured_delr_delc()[1]

    @property
    def xoffset(self) -> float:
        """X origin of the grid."""
        verts = np.asarray(self.planar_mesh.vertices, dtype=float)
        return float(verts[:, 0].min())

    @property
    def yoffset(self) -> float:
        """Y origin of the grid."""
        verts = np.asarray(self.planar_mesh.vertices, dtype=float)
        return float(verts[:, 1].min())

    @property
    def xvertices(self) -> np.ndarray:
        """2D X vertex array shaped (nrow+1, ncol+1). Structured only."""
        if not self.is_structured:
            raise ValueError("xvertices only available for structured grids")
        nrow, ncol = self.structured_shape
        verts = np.asarray(self.planar_mesh.vertices, dtype=float)
        return verts[:, 0].reshape(nrow + 1, ncol + 1)

    @property
    def yvertices(self) -> np.ndarray:
        """2D Y vertex array shaped (nrow+1, ncol+1). Structured only."""
        if not self.is_structured:
            raise ValueError("yvertices only available for structured grids")
        nrow, ncol = self.structured_shape
        verts = np.asarray(self.planar_mesh.vertices, dtype=float)
        return verts[:, 1].reshape(nrow + 1, ncol + 1)

    @property
    def top_grid(self) -> np.ndarray:
        """Top elevation as (nrow, ncol) for structured, (n_cells,) otherwise."""
        return self.reshape_to_grid(self.top)

    @property
    def botm_grid(self) -> np.ndarray:
        """Bottom elevations as (nlay, nrow, ncol) for structured, (nlay, n_cells) otherwise."""
        return self.reshape_to_grid(self.botm)

    # -- DIS export (structured only) -----------------------------------------

    def to_dis_kwargs(self) -> dict[str, Any]:
        """Build FloPy DIS keyword arguments.

        Raises if not structured.
        """
        if not self.is_structured:
            raise ValueError("to_dis_kwargs requires a structured grid")
        nrow, ncol = self.structured_shape
        delr, delc = self.structured_delr_delc()
        return {
            "nlay": self.nlay,
            "nrow": nrow,
            "ncol": ncol,
            "delr": delr,
            "delc": delc,
            "top": self.top.reshape(nrow, ncol),
            "botm": self.botm.reshape(self.nlay, nrow, ncol),
        }

    # -- DISV export (any topology) -------------------------------------------

    def to_disv_kwargs(self) -> dict[str, Any]:
        """Build FloPy DISV keyword arguments for MODFLOW 6."""
        from hydromodpy.spatial.mesh.adapters.flopy_adapter import to_flopy_disv_args

        return to_flopy_disv_args(
            self.planar_mesh,
            top=self.top,
            botm=self.botm,
        )

    # -- Diagnostics ----------------------------------------------------------

    def as_summary(self) -> dict[str, Any]:
        """JSON-serializable summary for diagnostics."""
        return {
            "n_cells": self.n_cells,
            "nlay": self.nlay,
            "is_structured": self.is_structured,
            "structured_shape": (list(self.structured_shape) if self.structured_shape else None),
            "bounds": list(self.planar_mesh.bounds()),
            "top_range": [float(np.nanmin(self.top)), float(np.nanmax(self.top))],
            "botm_range": [float(np.nanmin(self.botm)), float(np.nanmax(self.botm))],
            "n_active_cells": int(np.sum(~self.inactive_mask)),
            "n_inactive_cells": int(np.sum(self.inactive_mask)),
            "cell_types": [ct.value for ct in self.planar_mesh.cell_types],
        }
