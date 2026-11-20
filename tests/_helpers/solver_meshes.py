"""Solver meshes for the unit tests, built from a hand-made planar mesh.

``solver_mesh_from`` wraps a ``HydroMesh`` into the ``PlanarCellMesh`` a
``SolverMesh`` holds and adds the vertical part. The centers are the generators
a caller gives (a Voronoi mesh), the vertex means otherwise. Not public API.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.mesh.planar.hydro_mesh import HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import MeshIdentity, build_planar_cell_mesh
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import regular_mesh
from tests._helpers.regular_cell_meshes import from_flopy_structured


def solver_mesh_from(
    planar: HydroMesh,
    top: np.ndarray,
    botm: np.ndarray,
    inactive_mask: np.ndarray,
    *,
    centers: np.ndarray | None = None,
) -> SolverMesh:
    """Return the solver mesh of ``planar`` with the given tops, bottoms and mask.

    ``centers`` are the generators of a Voronoi mesh, its cell centers.
    """
    generated = centers is not None
    if centers is None:
        centers = np.column_stack(planar.cell_centroids())
    cell_mesh = build_planar_cell_mesh(
        planar,
        np.asarray(centers, dtype=float),
        center_kind="generator" if generated else "vertex_mean",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("test", "0", "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
        structured_shape=planar.structured_shape,
    )
    return SolverMesh(
        cell_mesh=cell_mesh, top=top, botm=botm, idomain=np.where(inactive_mask, 0, 1)
    )


def solver_mesh_from_sgrid(
    sgrid: object, *, zbot: np.ndarray, inactive_mask: np.ndarray
) -> SolverMesh:
    """Return the solver mesh of a flopy ``StructuredGrid``, the way a flopy round trip built it."""
    botm = np.asarray(zbot, dtype=float)
    if botm.ndim == 3:
        botm = botm.reshape(botm.shape[0], -1)
    mask = np.asarray(inactive_mask, dtype=bool)
    if mask.ndim == 2:
        mask = np.tile(mask.reshape(-1), (botm.shape[0], 1))
    elif mask.ndim == 3:
        mask = mask.reshape(mask.shape[0], -1)
    return solver_mesh_from(
        from_flopy_structured(sgrid),
        np.asarray(sgrid.top, dtype=float).reshape(-1),
        botm,
        mask,
    )


_LOCAL_CRS_WKT = (
    'LOCAL_CS["array grid",LOCAL_DATUM["local origin",0],UNIT["metre",1],'
    'AXIS["X",EAST],AXIS["Y",NORTH]]'
)
"""CRS of a grid defined by arrays alone: a local frame in meters."""


def solver_mesh_from_structured_arrays(
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
) -> SolverMesh:
    """Build a regular-grid SolverMesh from elevation arrays.

    The mesh carries no ``boundary:*`` family, so ``side_cells`` is empty. Tests of
    the side boundary conditions use ``RegularMeshEngine`` instead.

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
        Western and southern edges of the grid. Row 0 is the northern row.
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

    # Row 0 at the north like MODFLOW and flopy; ``yoff`` is the southern edge.
    cell_mesh = regular_mesh(nrow, ncol, dx=dx, dy=dy, xmin=xoff, ymin=yoff, crs_wkt=_LOCAL_CRS_WKT)

    if inactive_mask is None:
        mask = np.zeros((nlay, n_cells), dtype=bool)
    else:
        mask = np.asarray(inactive_mask, dtype=bool)
        if mask.ndim == 2 and mask.shape == (nrow, ncol):
            mask = np.tile(mask.reshape(-1), (nlay, 1))
        elif mask.ndim == 3:
            mask = mask.reshape(mask.shape[0], -1)

    return SolverMesh(
        cell_mesh=cell_mesh,
        top=top_flat,
        botm=botm_flat,
        idomain=np.where(mask, 0, 1),
    )
