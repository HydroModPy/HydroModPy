"""Regular cell meshes for the solver unit tests, with the vertices flopy computes.

``from_flopy_structured`` is the independent oracle of the quad connectivity of the
``regular`` engine: a plain Python loop over the vertices a flopy ``StructuredGrid``
computes. ``regular_cell_mesh`` builds the planar mesh of a regular grid from a flopy
``StructuredGrid``: the reference the ``regular`` engine must reproduce to the
bit. ``regular_cell_mesh_of_surface`` gives the grid of a surface support.
Not public API.
"""

from __future__ import annotations

import numpy as np
from flopy.discretization import StructuredGrid

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.spatial.surface import Surface
from tests._helpers.cell_meshes import TEST_CRS_WKT


def from_flopy_structured(sgrid: StructuredGrid) -> HydroMesh:
    """Return the quad ``HydroMesh`` of a flopy ``StructuredGrid``, row 0 north."""
    x_verts = np.asarray(sgrid.xvertices, dtype=float)
    y_verts = np.asarray(sgrid.yvertices, dtype=float)
    ny, nx = x_verts.shape
    vertices = np.column_stack((x_verts.reshape(-1), y_verts.reshape(-1)))
    nrow, ncol = ny - 1, nx - 1
    connectivity = np.empty((nrow * ncol, 4), dtype=int)
    idx = 0
    for j in range(nrow):
        for i in range(ncol):
            n00 = j * nx + i
            n10 = j * nx + (i + 1)
            n11 = (j + 1) * nx + (i + 1)
            n01 = (j + 1) * nx + i
            connectivity[idx] = [n00, n10, n11, n01]
            idx += 1
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(cell_type=CellType.QUADRILATERAL, connectivity=connectivity),),
        structured_shape=(nrow, ncol),
    )


def regular_cell_mesh(
    *,
    xmin: float,
    ymin: float,
    dx: float,
    dy: float,
    nrow: int,
    ncol: int,
) -> PlanarCellMesh:
    """Return the regular mesh of ``nrow x ncol`` cells, row 0 north, origin ``(xmin, ymin)``."""
    grid = StructuredGrid(
        delc=np.full(nrow, dy),
        delr=np.full(ncol, dx),
        xoff=xmin,
        yoff=ymin,
    )
    mesh = from_flopy_structured(grid)
    xs = xmin + (np.arange(ncol) + 0.5) * dx
    ys = ymin + (nrow - np.arange(nrow) - 0.5) * dy
    xx, yy = np.meshgrid(xs, ys, indexing="xy")
    return build_planar_cell_mesh(
        mesh,
        np.column_stack([xx.ravel(), yy.ravel()]),
        center_kind="cell_center",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("regular", "0", "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
        structured_shape=(nrow, ncol),
        domain_area_m2=nrow * ncol * dx * dy,
    )


def regular_cell_mesh_of_surface(
    surface: Surface,
    *,
    nrow: int | None = None,
    ncol: int | None = None,
) -> PlanarCellMesh:
    """Return the regular mesh over the extent of ``surface``, at its shape unless given."""
    support = surface.support
    nrow = int(support.nrows) if nrow is None else nrow
    ncol = int(support.ncols) if ncol is None else ncol
    return regular_cell_mesh(
        xmin=float(support.xmin),
        ymin=float(support.ymin),
        dx=(float(support.xmax) - float(support.xmin)) / ncol,
        dy=(float(support.ymax) - float(support.ymin)) / nrow,
        nrow=nrow,
        ncol=ncol,
    )
