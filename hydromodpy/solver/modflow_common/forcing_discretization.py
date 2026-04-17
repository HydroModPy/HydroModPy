"""Shared discretization helpers for heterogeneous MODFLOW forcing sources."""

from __future__ import annotations

import numpy as np


def has_spatially_distributed_source(load_result: object | None) -> bool:
    """Return whether one forcing source exposes gridded fields or located points."""
    if load_result is None:
        return False
    return bool(
        getattr(load_result, "has_fields", False)
        or getattr(load_result, "has_points", False)
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
        from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
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
        nrow = int(getattr(solver_mesh, "nrow"))
        ncol = int(getattr(solver_mesh, "ncol"))
        return {
            kper: np.zeros((nrow, ncol), dtype=float)
            for kper in range(int(nper))
        }

    from hydromodpy.solver.utils.mesh.gmsh_grid.planar_forcing_discretization import (
        discretize_fields_on_planar_mesh,
        discretize_points_on_planar_mesh,
    )

    resolved_planar_mesh = planar_mesh
    if resolved_planar_mesh is None:
        from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import (
            GmshPlanarMesh2D,
        )

        resolved_planar_mesh = GmshPlanarMesh2D.from_hydro_mesh(
            solver_mesh.planar_mesh
        )

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
    return {
        kper: np.zeros(n_cells, dtype=float)
        for kper in range(int(nper))
    }


__all__ = [
    "discretize_spatially_distributed_source",
    "has_spatially_distributed_source",
]
