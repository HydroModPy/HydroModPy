"""Shared discretization helpers for heterogeneous MODFLOW forcing sources."""

from __future__ import annotations

import numpy as np


def has_spatially_distributed_source(load_result: object | None) -> bool:
    """Return whether one forcing source exposes gridded fields or located points."""
    if load_result is None:
        return False
    return bool(
        getattr(load_result, "has_fields", False) or getattr(load_result, "has_points", False)
    )


def discretize_spatially_distributed_source(
    load_result: object,
    *,
    solver_mesh: object,
    nper: int,
    simulation_window: object | None = None,
    method: str = "nearest",
    planar_mesh: object | None = None,
) -> dict[int, np.ndarray]:
    """Discretize one heterogeneous source onto the current solver support.

    Structured solver meshes receive one ``(nrow, ncol)`` array per stress
    period. Unstructured planar meshes receive one flat ``(ncpl,)`` vector.
    """
    if bool(getattr(solver_mesh, "is_structured", False)):
        from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
            discretize_fields_on_sgrid,
            discretize_points_on_sgrid,
        )

        if getattr(load_result, "has_fields", False):
            return discretize_fields_on_sgrid(
                load_result=load_result,
                sgrid=solver_mesh,
                nper=int(nper),
                simulation_window=simulation_window,
                method=method,
            )
        if getattr(load_result, "has_points", False):
            return discretize_points_on_sgrid(
                load_result=load_result,
                sgrid=solver_mesh,
                nper=int(nper),
                simulation_window=simulation_window,
                method=method,
            )
        nrow = int(solver_mesh.nrow)
        ncol = int(solver_mesh.ncol)
        return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(int(nper))}

    from hydromodpy.spatial.mesh.gmsh_grid.planar_forcing_discretization import (
        discretize_fields_on_planar_mesh,
        discretize_points_on_planar_mesh,
    )

    resolved_planar_mesh = planar_mesh
    if resolved_planar_mesh is None:
        from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import (
            GmshPlanarMesh2D,
        )

        resolved_planar_mesh = GmshPlanarMesh2D.from_hydro_mesh(solver_mesh.planar_mesh)

    if getattr(load_result, "has_fields", False):
        return discretize_fields_on_planar_mesh(
            load_result=load_result,
            planar_mesh=resolved_planar_mesh,
            nper=int(nper),
            simulation_window=simulation_window,
            method=method,
        )
    if getattr(load_result, "has_points", False):
        return discretize_points_on_planar_mesh(
            load_result=load_result,
            planar_mesh=resolved_planar_mesh,
            nper=int(nper),
            simulation_window=simulation_window,
            method=method,
        )
    n_cells = int(getattr(solver_mesh, "n_cells", 0))
    return {kper: np.zeros(n_cells, dtype=float) for kper in range(int(nper))}


def broadcast_to_stress_periods(
    values: np.ndarray | float,
    *,
    nper: int,
    shape: tuple[int, ...] | None = None,
) -> dict[int, np.ndarray]:
    """Expand a steady scalar or constant array to a per-stress-period dict.

    Used by RCH/EVT translators when the user supplies a single uniform
    forcing value and the MODFLOW API expects one payload per stress
    period.
    """
    arr = np.asarray(values, dtype=float)
    if shape is not None and arr.ndim == 0:
        arr = np.full(shape, float(arr))
    arr = np.array(arr, dtype=float, copy=True)
    return {kper: arr.copy() for kper in range(int(nper))}


def stress_period_axes(nper: int) -> list[int]:
    """Return the list of stress-period indices ``[0, ..., nper-1]``."""
    return list(range(int(nper)))


__all__ = [
    "broadcast_to_stress_periods",
    "discretize_spatially_distributed_source",
    "has_spatially_distributed_source",
    "stress_period_axes",
]
