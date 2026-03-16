"""Unified solver mesh abstraction for structured and unstructured grids.

``SolverMesh`` is the single grid object that traverses the entire solver
pipeline.  It wraps a 2D ``HydroMesh`` (planar geometry) together with
layer elevations, providing everything the solver needs to build MODFLOW
DIS or DISV packages.

All solver code receives a ``SolverMesh`` — never raw FloPy grids or
explicit ``(nlay, nrow, ncol)`` tuples.  The structured/unstructured
distinction is handled internally and exposed via ``is_structured``.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

import numpy as np

from hydromodpy.mesh import CellBlock, CellType, HydroMesh


@dataclass(frozen=True)
class SolverMesh:
    """Solver-agnostic 2D+layers mesh.

    Parameters
    ----------
    planar_mesh : HydroMesh
        2D mesh with vertices and cell connectivity.
    top : ndarray, shape (n_cells,)
        Top elevation per cell.
    botm : ndarray, shape (nlay, n_cells)
        Bottom elevation per cell per layer.
    inactive_mask : ndarray, shape (nlay, n_cells)
        Boolean mask where True = inactive cell.
    """

    planar_mesh: HydroMesh
    top: np.ndarray
    botm: np.ndarray
    inactive_mask: np.ndarray

    def __post_init__(self) -> None:
        if self.planar_mesh.ndim != 2:
            raise ValueError("SolverMesh requires a 2D planar mesh")
        top = np.asarray(self.top, dtype=float).reshape(-1)
        if top.size != self.planar_mesh.n_cells:
            raise ValueError(
                f"top must have {self.planar_mesh.n_cells} values, got {top.size}"
            )
        object.__setattr__(self, "top", top)

        botm = np.asarray(self.botm, dtype=float)
        if botm.ndim == 1:
            botm = botm.reshape(1, -1)
        if botm.ndim != 2 or botm.shape[1] != self.planar_mesh.n_cells:
            raise ValueError(
                f"botm must have shape (nlay, {self.planar_mesh.n_cells}), "
                f"got {botm.shape}"
            )
        object.__setattr__(self, "botm", botm)

        mask = np.asarray(self.inactive_mask, dtype=bool)
        if mask.shape != botm.shape:
            raise ValueError(
                f"inactive_mask must have shape {botm.shape}, got {mask.shape}"
            )
        object.__setattr__(self, "inactive_mask", mask)

    # -- Properties -----------------------------------------------------------

    @property
    def n_cells(self) -> int:
        """Number of planar cells."""
        return self.planar_mesh.n_cells

    @property
    def nlay(self) -> int:
        """Number of layers."""
        return int(self.botm.shape[0])

    @property
    def is_structured(self) -> bool:
        """True when the planar mesh is a regular quadrilateral grid."""
        return self.planar_mesh.is_structured

    @property
    def structured_shape(self) -> tuple[int, int] | None:
        """Return (nrow, ncol) if structured, else None."""
        return self.planar_mesh.structured_shape

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
        """Return cell centroids as ndarray (n_cells, 2)."""
        conn = self.planar_mesh.flat_connectivity
        verts = np.asarray(self.planar_mesh.vertices, dtype=float)
        centroids = np.zeros((self.n_cells, 2), dtype=float)
        for ic in range(self.n_cells):
            nodes = conn[ic]
            centroids[ic, 0] = float(verts[nodes, 0].mean())
            centroids[ic, 1] = float(verts[nodes, 1].mean())
        return centroids

    def cell_areas(self) -> np.ndarray:
        """Return area of each planar cell."""
        conn = self.planar_mesh.flat_connectivity
        verts = np.asarray(self.planar_mesh.vertices, dtype=float)
        areas = np.zeros(self.n_cells, dtype=float)
        for ic in range(self.n_cells):
            nodes = conn[ic]
            poly = verts[nodes]
            # Shoelace formula
            x = poly[:, 0]
            y = poly[:, 1]
            areas[ic] = abs(float(
                0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
            ))
        return areas

    @property
    def characteristic_length(self) -> float:
        """Mean cell edge length (sqrt of mean area)."""
        return float(sqrt(float(np.mean(self.cell_areas()))))

    def layer_thicknesses(self) -> np.ndarray:
        """Return thickness per cell per layer, shape (nlay, n_cells)."""
        tops = np.vstack([self.top.reshape(1, -1), self.botm[:-1]])
        return tops - self.botm

    def layer_center_depths(self) -> np.ndarray:
        """Return depth of layer centers below top, shape (nlay, n_cells)."""
        tops = np.vstack([self.top.reshape(1, -1), self.botm[:-1]])
        centers_z = 0.5 * (tops + self.botm)
        return self.top.reshape(1, -1) - centers_z

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
    # object is expected (e.g. sgrid_fieldparam_discretization, sgrid_mesh_adapter).
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
        from hydromodpy.mesh.adapters.flopy_adapter import to_flopy_disv_args

        return to_flopy_disv_args(
            self.planar_mesh,
            top=self.top,
            botm=self.botm,
        )

    # -- Constructors ---------------------------------------------------------

    @classmethod
    def from_sgrid(
        cls,
        sgrid: object,
        *,
        zbot: np.ndarray,
        inactive_mask: np.ndarray,
    ) -> "SolverMesh":
        """Build from a FloPy StructuredGrid.

        Parameters
        ----------
        sgrid : flopy.discretization.StructuredGrid
            Structured grid with delr, delc, top, botm, nrow, ncol.
        zbot : ndarray, shape (nlay, nrow, ncol)
            Layer bottom elevations.
        inactive_mask : ndarray, shape (nlay, nrow, ncol) or (nrow, ncol)
            Inactive cell mask.
        """
        from hydromodpy.mesh.adapters.flopy_adapter import from_flopy_structured

        planar_mesh = from_flopy_structured(sgrid)
        top = np.asarray(getattr(sgrid, "top"), dtype=float).reshape(-1)
        botm = np.asarray(zbot, dtype=float)
        if botm.ndim == 3:
            botm = botm.reshape(botm.shape[0], -1)

        mask = np.asarray(inactive_mask, dtype=bool)
        if mask.ndim == 2:
            # 2D mask → broadcast to all layers
            mask_flat = mask.reshape(-1)
            mask = np.tile(mask_flat, (botm.shape[0], 1))
        elif mask.ndim == 3:
            mask = mask.reshape(mask.shape[0], -1)

        return cls(
            planar_mesh=planar_mesh,
            top=top,
            botm=botm,
            inactive_mask=mask,
        )

    @classmethod
    def from_extruded_mesh(
        cls,
        mesh_3d: object,
        *,
        inactive_mask: np.ndarray | None = None,
    ) -> "SolverMesh":
        """Build from an ExtrudedPrismMesh3D.

        Parameters
        ----------
        mesh_3d : ExtrudedPrismMesh3D
            3D mesh built by vertical extrusion of a 2D planar mesh.
        inactive_mask : ndarray, optional
            If None, all cells are active.
        """
        planar_mesh = mesh_3d.planar_mesh.to_hydro_mesh()
        z_interfaces = np.asarray(mesh_3d.z_interfaces, dtype=float).reshape(-1)
        n_cells_2d = planar_mesh.n_cells
        nlay = len(z_interfaces) - 1

        # Build top and botm from z_interfaces (uniform layering across cells)
        top = np.full(n_cells_2d, float(z_interfaces[0]), dtype=float)
        botm = np.zeros((nlay, n_cells_2d), dtype=float)
        for ilay in range(nlay):
            botm[ilay, :] = float(z_interfaces[ilay + 1])

        if inactive_mask is None:
            mask = np.zeros((nlay, n_cells_2d), dtype=bool)
        else:
            mask = np.asarray(inactive_mask, dtype=bool)
            if mask.ndim == 1:
                mask = np.tile(mask.reshape(1, -1), (nlay, 1))
            elif mask.ndim == 2 and mask.shape != (nlay, n_cells_2d):
                mask = mask.reshape(nlay, n_cells_2d)

        return cls(
            planar_mesh=planar_mesh,
            top=top,
            botm=botm,
            inactive_mask=mask,
        )

    @classmethod
    def from_structured_arrays(
        cls,
        *,
        nrow: int,
        ncol: int,
        top: np.ndarray,
        botm: np.ndarray,
        dx: float = 1.0,
        dy: float = 1.0,
        xoff: float = 0.0,
        yoff: float = 0.0,
        inactive_mask: np.ndarray | None = None,
    ) -> "SolverMesh":
        """Build a structured SolverMesh from elevation arrays.

        Parameters
        ----------
        nrow, ncol : int
            Grid dimensions.
        top : ndarray, shape (nrow, ncol) or (n_cells,)
            Top elevation per cell.
        botm : ndarray, shape (nlay, nrow, ncol) or (nlay, n_cells)
            Bottom elevation per cell per layer.
        dx, dy : float
            Cell sizes.
        xoff, yoff : float
            Grid origin offsets.
        inactive_mask : ndarray, optional
            Boolean mask; if None all cells are active.
        """
        top_flat = np.asarray(top, dtype=float).reshape(-1)
        botm_arr = np.asarray(botm, dtype=float)
        if botm_arr.ndim == 3:
            nlay = botm_arr.shape[0]
            botm_flat = botm_arr.reshape(nlay, -1)
        elif botm_arr.ndim == 2:
            nlay = botm_arr.shape[0]
            botm_flat = botm_arr
        elif botm_arr.ndim == 1:
            nlay = 1
            botm_flat = botm_arr.reshape(1, -1)
        else:
            raise ValueError(f"botm must be 1D, 2D, or 3D, got ndim={botm_arr.ndim}")

        n_cells = nrow * ncol
        if top_flat.size != n_cells:
            raise ValueError(f"top must have {n_cells} values, got {top_flat.size}")

        # Build structured planar mesh vertices (nrow+1)*(ncol+1) nodes.
        x_edges = xoff + np.arange(ncol + 1) * dx
        y_edges = yoff + np.arange(nrow + 1) * dy
        xx, yy = np.meshgrid(x_edges, y_edges, indexing="xy")
        vertices = np.column_stack([xx.ravel(), yy.ravel()])

        # Quad connectivity: row-major cells.
        connectivity = np.empty((n_cells, 4), dtype=int)
        for r in range(nrow):
            for c in range(ncol):
                ic = r * ncol + c
                n0 = r * (ncol + 1) + c
                connectivity[ic] = [n0, n0 + 1, n0 + ncol + 2, n0 + ncol + 1]

        planar_mesh = HydroMesh(
            vertices=vertices,
            cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
            structured_shape=(nrow, ncol),
        )

        if inactive_mask is None:
            mask = np.zeros((nlay, n_cells), dtype=bool)
        else:
            mask = np.asarray(inactive_mask, dtype=bool)
            if mask.ndim == 2 and mask.shape == (nrow, ncol):
                mask = np.tile(mask.reshape(-1), (nlay, 1))
            elif mask.ndim == 3:
                mask = mask.reshape(mask.shape[0], -1)

        return cls(
            planar_mesh=planar_mesh,
            top=top_flat,
            botm=botm_flat,
            inactive_mask=mask,
        )

    # -- Diagnostics ----------------------------------------------------------

    def as_summary(self) -> dict[str, Any]:
        """JSON-serializable summary for diagnostics."""
        return {
            "n_cells": self.n_cells,
            "nlay": self.nlay,
            "is_structured": self.is_structured,
            "structured_shape": (
                list(self.structured_shape) if self.structured_shape else None
            ),
            "bounds": list(self.planar_mesh.bounds()),
            "top_range": [float(np.nanmin(self.top)), float(np.nanmax(self.top))],
            "botm_range": [float(np.nanmin(self.botm)), float(np.nanmax(self.botm))],
            "n_active_cells": int(np.sum(~self.inactive_mask)),
            "n_inactive_cells": int(np.sum(self.inactive_mask)),
            "cell_types": [ct.value for ct in self.planar_mesh.cell_types],
        }
