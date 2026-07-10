"""MODFLOW 6 adapter for the solver-agnostic surface-conditioning kernel.

This is the thin backend adapter for Stage B (the priority-flood fill). It pulls
the conditioning primitives out of a ``SolverMesh`` (top, active mask, face
adjacency, layer-0 bottom floor, lake-bed control levels), calls the spatial
kernel, and writes the conditioned top back into a new ``SolverMesh``. All the
drainage logic lives in ``hydromodpy.spatial.mesh.surface_conditioning``; this
file only marshals types.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np

from hydromodpy.spatial.mesh.cell_adjacency import build_planar_cell_adjacency
from hydromodpy.spatial.mesh.surface_conditioning import (
    SurfaceConditioningInput,
    condition_surface_top,
)


def condition_solver_mesh_top(
    solver_mesh: Any,
    mesh_support: Any,
    *,
    protected_cells: set[int] | None = None,
    epsilon: float = 1e-3,
) -> tuple[Any, dict[str, float]]:
    """Return a copy of ``solver_mesh`` whose layer-0 top has no closed depression.

    Parameters
    ----------
    solver_mesh :
        The ``SolverMesh`` to condition (frozen; a new one is returned).
    mesh_support :
        Runtime mesh support exposing ``edge_cell_a`` / ``edge_cell_b`` (used to
        prefer the runtime face incidence when it indexes these cells).
    protected_cells :
        Active cells whose top is a fixed base level (marnage lake cells whose top
        is the bathymetric bed). They are pinned at their own top and the fill
        drains into them. Inactive cells are always the outer boundary.
    epsilon :
        Minimal downhill increment (m) so filled cells strictly descend.
    """
    top = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    n_cells = int(top.shape[0])
    active = ~np.asarray(solver_mesh.inactive_mask, dtype=bool)[0]
    planar_mesh = getattr(solver_mesh, "planar_mesh", None)
    adjacency = build_planar_cell_adjacency(planar_mesh, n_cells, mesh_support)

    # A lake bed is a legitimate low: pin it at its carved top so the fill drains
    # into it rather than flooding it to its spill level. Only active cells matter
    # (fixed-area lake cells are already inactive and act as boundary).
    control_cells = {
        int(cid): float(top[int(cid)]) for cid in (protected_cells or ()) if active[int(cid)]
    }
    botm = getattr(solver_mesh, "botm", None)
    botm0 = None if botm is None else np.asarray(botm, dtype=float)[0]

    result = condition_surface_top(
        SurfaceConditioningInput(
            top=top,
            active=active,
            adjacency=adjacency,
            floor=botm0,
            control_cells=control_cells,
        ),
        epsilon=epsilon,
    )
    new_mesh = dataclasses.replace(solver_mesh, top=result.top)
    return new_mesh, result.info
