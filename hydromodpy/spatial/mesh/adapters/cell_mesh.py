"""The planar cell mesh of a regular grid.

The adapter keeps the cells and the vertex order of the grid as they are, states
the centre rule the solvers use and measures the QA. The triangles of a mesh
bundle are read by ``gmsh_grid.bundle_cell_mesh``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid

__all__ = ["cell_mesh_from_regular_grid"]

_ENGINE_VERSION = "1.0.0"


def cell_mesh_from_regular_grid(grid: RegularGrid, *, crs_wkt: str) -> PlanarCellMesh:
    """Wrap a regular grid: the quads of ``RegularGrid.to_hydro_mesh``, row 0 north."""
    mesh = grid.to_hydro_mesh()
    nrow, ncol = (int(v) for v in grid.shape)
    xmin, ymax = grid.origin
    x = xmin + (np.arange(ncol) + 0.5) * float(grid.dx)
    y = ymax - (np.arange(nrow) + 0.5) * float(grid.dy)
    xx, yy = np.meshgrid(x, y, indexing="xy")
    return build_planar_cell_mesh(
        mesh,
        np.column_stack([xx.ravel(), yy.ravel()]),
        center_kind="cell_center",
        crs_wkt=crs_wkt,
        identity=MeshIdentity("regular", _ENGINE_VERSION, "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
        structured_shape=(nrow, ncol),
        domain_area_m2=nrow * ncol * float(grid.dx) * float(grid.dy),
    )
