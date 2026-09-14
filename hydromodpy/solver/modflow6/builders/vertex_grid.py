"""Standalone FloPy vertex grid for geometry-to-cell intersection.

Advanced-package builders (LAK, SFR) run *before* the DISV package is registered
on the GWF model, so they rebuild a ``flopy.discretization.VertexGrid`` from the
``SolverMesh`` to intersect polygons / polylines with the planar cells.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


def build_vertex_grid_for_intersection(solver_mesh: SolverMesh):
    """Return a standalone ``flopy.discretization.VertexGrid`` for intersections.

    The DISV vertices already carry absolute model coordinates, hence
    ``xoff = yoff = 0``. ``idomain`` is the CURRENT active domain of the mesh so
    the intersection sees the real footprint.
    """
    from flopy.discretization import VertexGrid

    disv_kwargs = solver_mesh.to_disv_kwargs()
    return VertexGrid(
        vertices=disv_kwargs["vertices"],
        cell2d=disv_kwargs["cell2d"],
        top=np.asarray(solver_mesh.top, dtype=float),
        botm=np.asarray(solver_mesh.botm, dtype=float),
        idomain=solver_mesh.idomain(),
        nlay=int(solver_mesh.nlay),
        ncpl=int(solver_mesh.n_cells),
        xoff=0.0,
        yoff=0.0,
    )


__all__ = ["build_vertex_grid_for_intersection"]
