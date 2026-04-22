"""Forcing discretization helpers for 2-D Gmsh planar meshes.

This module reuses the structured-grid forcing bridge by exposing Gmsh cell
centroids as a degenerate ``(n_cells, 1)`` pseudo-grid. That keeps temporal
aggregation, unit conversion, and interpolation behavior aligned with the
existing structured MODFLOW path while producing one scalar per planar cell.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
    discretize_fields_on_sgrid,
    discretize_points_on_sgrid,
)


def _pseudo_sgrid_from_planar_mesh(planar_mesh: object) -> object:
    """Expose Gmsh cell centroids through the minimal SGrid-like contract."""
    x_centers, y_centers = planar_mesh.cell_centroids()
    x_centers = np.asarray(x_centers, dtype=float).reshape(-1, 1)
    y_centers = np.asarray(y_centers, dtype=float).reshape(-1, 1)
    return SimpleNamespace(
        nrow=int(planar_mesh.n_cells),
        ncol=1,
        xcellcenters=x_centers,
        ycellcenters=y_centers,
    )


def discretize_fields_on_planar_mesh(
    *,
    load_result: object,
    planar_mesh: object,
    nper: int,
    simulation_window: object | None = None,
    method: str = "nearest",
) -> dict[int, np.ndarray]:
    """Discretize gridded forcing fields to one value per Gmsh cell."""
    pseudo_sgrid = _pseudo_sgrid_from_planar_mesh(planar_mesh)
    arrays_2d = discretize_fields_on_sgrid(
        load_result=load_result,
        sgrid=pseudo_sgrid,
        nper=int(nper),
        simulation_window=simulation_window,
        method=method,
    )
    return {
        int(kper): np.asarray(values, dtype=float).reshape(-1) for kper, values in arrays_2d.items()
    }


def discretize_points_on_planar_mesh(
    *,
    load_result: object,
    planar_mesh: object,
    nper: int,
    simulation_window: object | None = None,
    method: str = "nearest",
    source_unit: str = "mm/day",
) -> dict[int, np.ndarray]:
    """Interpolate located point forcings to one value per Gmsh cell."""
    pseudo_sgrid = _pseudo_sgrid_from_planar_mesh(planar_mesh)
    arrays_2d = discretize_points_on_sgrid(
        load_result=load_result,
        sgrid=pseudo_sgrid,
        nper=int(nper),
        simulation_window=simulation_window,
        method=method,
        source_unit=source_unit,
    )
    return {
        int(kper): np.asarray(values, dtype=float).reshape(-1) for kper, values in arrays_2d.items()
    }


__all__ = [
    "discretize_fields_on_planar_mesh",
    "discretize_points_on_planar_mesh",
]
