"""Obstacle-specific math for the PETSc VI head-only formulation."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly import BoussinesqAssembly
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtimes.execution_common import residual_norm_inf


def prescribed_head_cells(
    prescribed_head_m_by_cell: np.ndarray | None,
) -> np.ndarray | None:
    """Return the canonical prescribed-head cell vector, if provided."""
    if prescribed_head_m_by_cell is None:
        return None
    return np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)


def clip_head_to_bounds(
    head_m: np.ndarray,
    *,
    lower: np.ndarray,
    upper: np.ndarray,
) -> np.ndarray:
    """Return one initial head guess inside the PETSc variable bounds."""
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    if head.size != np.asarray(lower).size:
        raise ValueError(
            f"head_m length must match bounds ({int(head.size)} != {int(np.asarray(lower).size)})."
        )
    return np.clip(head, np.asarray(lower, dtype=float), np.asarray(upper, dtype=float))


def obstacle_tolerance(tol_state_update_inf: float) -> float:
    """Return the tolerance used to classify active obstacle cells."""
    return max(1.0e-9, 10.0 * float(tol_state_update_inf))


def reconstruct_obstacle_reactions(
    *,
    mesh: BoussinesqMesh,
    assembly: BoussinesqAssembly,
    head_m: np.ndarray,
    physical_lower_m: np.ndarray,
    physical_upper_m: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> tuple[BoussinesqAssembly, dict[str, Any]]:
    """Reconstruct non-negative obstacle reactions from the raw balance residual."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    raw_residual = np.asarray(assembly.flow_residual_m3_s, dtype=float).reshape(-1)
    free_mask = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    surface_active = free_mask & (head >= np.asarray(physical_upper_m, dtype=float) - float(tol_h))
    bottom_active = free_mask & (head <= np.asarray(physical_lower_m, dtype=float) + float(tol_h))
    interior_free = free_mask & ~(surface_active | bottom_active)
    surface_reaction = np.where(surface_active, np.maximum(-raw_residual, 0.0), 0.0)
    bottom_reaction = np.where(bottom_active, np.maximum(raw_residual, 0.0), 0.0)
    area = np.asarray(mesh.cell_area_m2, dtype=float).reshape(-1)
    q_ex = np.divide(
        surface_reaction,
        area,
        out=np.zeros(int(mesh.n_cells), dtype=float),
        where=area > 0.0,
    )
    q_dry = np.divide(
        bottom_reaction,
        area,
        out=np.zeros(int(mesh.n_cells), dtype=float),
        where=area > 0.0,
    )
    correction = surface_reaction - bottom_reaction
    corrected_flow = raw_residual + correction
    corrected_residual = np.asarray(assembly.residual_m3_s, dtype=float).reshape(-1).copy()
    corrected_solver = np.asarray(assembly.solver_residual, dtype=float).reshape(-1).copy()
    corrected_residual[free_mask] = corrected_residual[free_mask] + correction[free_mask]
    corrected_solver[free_mask] = corrected_solver[free_mask] + correction[free_mask]
    diagnostics = {
        "surface_active_cells": int(np.count_nonzero(surface_active)),
        "bottom_active_cells": int(np.count_nonzero(bottom_active)),
        "free_cells": int(np.count_nonzero(interior_free)),
        "surface_reaction_total_m3_s": float(np.sum(surface_reaction)),
        "bottom_reaction_total_m3_s": float(np.sum(bottom_reaction)),
        "surface_reaction_wrong_sign_m3_s": float(
            np.max(np.where(surface_active, np.maximum(raw_residual, 0.0), 0.0))
        ),
        "bottom_reaction_wrong_sign_m3_s": float(
            np.max(np.where(bottom_active, np.maximum(-raw_residual, 0.0), 0.0))
        ),
    }
    reacted_assembly = replace(
        assembly,
        saturation_excess_rate_m_s=q_ex,
        dry_deficit_rate_m_s=q_dry,
        flow_residual_m3_s=corrected_flow,
        residual_m3_s=corrected_residual,
        solver_residual=corrected_solver,
    )
    return reacted_assembly, diagnostics


def projected_vi_residual(
    *,
    residual: np.ndarray,
    head_m: np.ndarray,
    lower_m: np.ndarray,
    upper_m: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> np.ndarray:
    """Return the residual left after applying bound complementarity signs.

    PETSc SNESVI accepts ``F >= 0`` on a lower active bound and ``F <= 0`` on
    an upper active bound. This helper mirrors that convention for the
    HydroModPy residual sign.
    """
    values = np.asarray(residual, dtype=float).reshape(-1)
    head = np.asarray(head_m, dtype=float).reshape(-1)
    lower = np.asarray(lower_m, dtype=float).reshape(-1)
    upper = np.asarray(upper_m, dtype=float).reshape(-1)
    projected = values.copy()
    prescribed = np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    free = ~prescribed
    lower_active = free & (head <= lower + float(tol_h))
    upper_active = free & (head >= upper - float(tol_h))
    interior = free & ~(lower_active | upper_active)
    projected[interior] = values[interior]
    projected[lower_active] = np.minimum(values[lower_active], 0.0)
    projected[upper_active] = np.maximum(values[upper_active], 0.0)
    return projected


def free_residual_norm(
    *,
    residual: np.ndarray,
    head_m: np.ndarray,
    lower_m: np.ndarray,
    upper_m: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> float:
    """Return the free-cell raw balance norm, excluding active obstacles."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    lower = np.asarray(lower_m, dtype=float).reshape(-1)
    upper = np.asarray(upper_m, dtype=float).reshape(-1)
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    interior = free & (head > lower + float(tol_h)) & (head < upper - float(tol_h))
    if not np.any(interior):
        return 0.0
    return residual_norm_inf(np.asarray(residual, dtype=float).reshape(-1)[interior])
