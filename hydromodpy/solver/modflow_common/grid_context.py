"""Runtime spatial-grid context for MODFLOW-family solvers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.core.grid_reference import GridReference
from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.spatial.surface import Surface


def grid_reference_from_solver_mesh(
    solver_mesh: SolverMesh,
    *,
    crs: str | None = None,
    nodata: float = -9999.0,
) -> GridReference:
    """Build a GridReference from a SolverMesh."""
    mesh_bounds = solver_mesh.planar_mesh.bounds()
    xmin, ymin = float(mesh_bounds[0]), float(mesh_bounds[1])
    xmax, ymax = float(mesh_bounds[2]), float(mesh_bounds[3])
    return GridReference(
        n_cells=solver_mesh.n_cells,
        bounds=(xmin, ymin, xmax, ymax),
        crs=crs,
        nodata=float(nodata),
        structured_shape=solver_mesh.structured_shape,
        cell_size_hint=float(solver_mesh.characteristic_length),
    )


@dataclass(slots=True)
class SolverGridContext:
    """Runtime bundle for one solver grid (structured or unstructured)."""

    grid: GridReference
    solver_mesh: SolverMesh
    top_surface: Surface
    bottom_surface: Surface
    template_raster_path: str | None = None

    @property
    def top_elevation(self) -> np.ndarray:
        """Top elevation as flat (n_cells,) array."""
        return np.asarray(self.solver_mesh.top, dtype=float)

    @property
    def bottom_layer(self) -> np.ndarray:
        """Bottom elevation of deepest layer as flat (n_cells,) array."""
        return np.asarray(self.solver_mesh.botm[-1], dtype=float)

    @property
    def nlay(self) -> int:
        return self.solver_mesh.nlay

    @property
    def n_cells(self) -> int:
        return self.solver_mesh.n_cells

    @property
    def is_structured(self) -> bool:
        return self.solver_mesh.is_structured

    @property
    def nrow(self) -> int:
        return self.solver_mesh.nrow

    @property
    def ncol(self) -> int:
        return self.solver_mesh.ncol
