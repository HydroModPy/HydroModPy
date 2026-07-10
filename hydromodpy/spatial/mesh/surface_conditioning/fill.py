"""Priority-flood epsilon fill on a mesh face graph (Barnes 2014).

Sampling a DEM at irregular cell generators reintroduces local minima the raster
depression-fill removed: two adjacent coarse cells can each sit below their
neighbours, so the mesh graph gains sinks the surface has not. This raises every
active cell no more than needed to keep a strictly descending path to a base
level. Base levels are the idomain boundary ring and the control cells (lake
beds, thalwegs), which are pinned and never raised; only ``top`` moves up, so the
aquifer bottom stays put and the fill just thickens layer 0 at the pits.

This is solver-agnostic: it operates on the primitives of ``SurfaceConditioningInput``
and never touches a ``SolverMesh`` or flopy. Each backend adapter builds the input
and writes ``result.top`` back into its own discretization.
"""

from __future__ import annotations

import heapq

import numpy as np

from hydromodpy.spatial.mesh.surface_conditioning.contract import (
    SurfaceConditioningInput,
    SurfaceConditioningResult,
)

_RAISE_TOL_M = 1e-6


def condition_surface_top(
    inp: SurfaceConditioningInput,
    *,
    epsilon: float = 1e-3,
) -> SurfaceConditioningResult:
    """Return a conditioned top with no closed depression on the active graph.

    Parameters
    ----------
    inp :
        The conditioning primitives (top, active mask, adjacency, optional floor
        and control cells).
    epsilon :
        Minimal downhill increment (m) added along each filled path so filled
        cells strictly descend instead of forming flats.
    """
    top = np.asarray(inp.top, dtype=float).reshape(-1)
    n_cells = int(top.shape[0])
    active = np.asarray(inp.active, dtype=bool).reshape(-1)
    adjacency = inp.adjacency
    control = {int(cid): float(elev) for cid, elev in dict(inp.control_cells or {}).items()}

    filled = top.copy()
    # Control cells anchor at their fixed base level (a lake bed can sit far below
    # its sampled top; the fill must drain INTO it, never raise it).
    for cid, elev in control.items():
        filled[cid] = elev

    visited = np.zeros(n_cells, dtype=bool)
    heap: list[tuple[float, int, int]] = []
    order = 0
    # Seeds = the base level: active cells touching the inactive domain (the
    # outlet/boundary ring) plus the control cells. Their filled elevation is
    # their own base level; they are never raised.
    for cell in range(n_cells):
        if not active[cell]:
            continue
        touches_boundary = any((not active[nb]) for nb in adjacency[cell])
        if touches_boundary or cell in control:
            visited[cell] = True
            heapq.heappush(heap, (float(filled[cell]), order, cell))
            order += 1
    # Priority flood: always grow from the lowest known spill elevation, raising
    # each newly reached cell to max(its own top, current spill + epsilon).
    while heap:
        spill, _, cell = heapq.heappop(heap)
        for nb in adjacency[cell]:
            if not active[nb] or visited[nb]:
                continue
            raised_to = top[nb] if top[nb] > spill + epsilon else spill + epsilon
            filled[nb] = raised_to
            visited[nb] = True
            heapq.heappush(heap, (float(raised_to), order, nb))
            order += 1

    # Re-pin control cells to their exact base level (the flood may have queued
    # them from a lower spill; their level is a hard constraint, not a target).
    for cid, elev in control.items():
        filled[cid] = elev

    delta = filled - top
    raised_mask = delta > _RAISE_TOL_M
    floor_violations = 0
    if inp.floor is not None:
        floor = np.asarray(inp.floor, dtype=float).reshape(-1)
        valid = active & np.isfinite(floor)
        floor_violations = int(np.count_nonzero(valid & (filled < floor - _RAISE_TOL_M)))
    info = {
        "cells_raised": int(raised_mask.sum()),
        "max_raise_m": float(delta.max(initial=0.0)),
        "mean_raise_m": float(delta[raised_mask].mean()) if raised_mask.any() else 0.0,
        "unreached_active": int((active & ~visited).sum()),
        "floor_violations": float(floor_violations),
    }
    return SurfaceConditioningResult(top=filled, raised=raised_mask, info=info)
