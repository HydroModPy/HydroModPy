"""Pure helpers shared by the PETSc mixed-complementarity runtime."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    assemble_steady_residual,
    assemble_transient_residual,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

_MIN_RATE_SCALE_M_S = 1.0e-12
_MIN_HEAD_SCALE_M = 1.0
_FB_JACOBIAN_EPS = 1.0e-12


def _complementarity_scales(
    mesh: BoussinesqMesh,
    *,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    dt_seconds: float | None,
) -> tuple[float, float]:
    """Return simple global scales used to nondimensionalize the NCP residual."""
    aquifer_thickness_m = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    thickness_vector = np.asarray(aquifer_thickness_m, dtype=float).reshape(-1)
    head_scale_m = max(
        float(np.max(thickness_vector)) if thickness_vector.size else 0.0,
        _MIN_HEAD_SCALE_M,
    )

    recharge = np.asarray(
        recharge_rate_m_s if recharge_rate_m_s is not None else 0.0,
        dtype=float,
    ).reshape(-1)
    recharge_scale = float(np.max(np.abs(recharge))) if recharge.size else 0.0

    well_flux_raw = np.asarray(
        well_flux_m3_s if well_flux_m3_s is not None else 0.0,
        dtype=float,
    ).reshape(-1)
    if well_flux_raw.size == 0:
        well_rate = np.zeros(mesh.n_cells, dtype=float)
    elif well_flux_raw.size == 1:
        well_rate = np.full(
            mesh.n_cells,
            float(np.abs(well_flux_raw[0])),
            dtype=float,
        )
    elif well_flux_raw.size == mesh.n_cells:
        well_rate = np.abs(well_flux_raw).astype(float, copy=False)
    else:
        raise ValueError("well_flux_m3_s must be scalar or cell-aligned for the PETSc backend.")
    well_rate = np.divide(
        well_rate,
        mesh.cell_area_m2,
        out=np.zeros(mesh.n_cells, dtype=float),
        where=mesh.cell_area_m2 > 0.0,
    )
    well_scale = float(np.max(well_rate)) if well_rate.size else 0.0

    conductivity = np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float).reshape(-1)
    conductivity_scale = float(np.max(np.abs(conductivity))) if conductivity.size else 0.0
    storage_scale = 0.0
    if dt_seconds is not None and float(dt_seconds) > 0.0:
        storage = np.asarray(mesh.storage_coefficient, dtype=float).reshape(-1)
        storage_scale = (
            float(np.max(np.abs(storage)) if storage.size else 0.0)
            * head_scale_m
            / float(dt_seconds)
        )

    rate_scale_m_s = max(
        recharge_scale,
        well_scale,
        conductivity_scale,
        storage_scale,
        _MIN_RATE_SCALE_M_S,
    )
    return head_scale_m, rate_scale_m_s


def _fischer_burmeister_residual_and_derivatives(
    q_ex_rate_m_s: np.ndarray,
    surface_gap_m: np.ndarray,
    *,
    head_scale_m: float,
    rate_scale_m_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the NCP residual and its diagonal derivatives."""
    a = np.asarray(q_ex_rate_m_s, dtype=float) / float(rate_scale_m_s)
    b = np.asarray(surface_gap_m, dtype=float) / float(head_scale_m)
    radius = np.hypot(a, b)
    denominator = np.maximum(radius, _FB_JACOBIAN_EPS)
    residual = radius - a - b
    dphi_dq = (a / denominator - 1.0) / float(rate_scale_m_s)
    dphi_dh = (1.0 - b / denominator) / float(head_scale_m)
    return residual, dphi_dh, dphi_dq


def _stack_state(head_m: np.ndarray, q_ex_rate_m_s: np.ndarray) -> np.ndarray:
    """Pack the mixed unknown ``(h, q_ex)`` into one contiguous vector."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    q_ex = np.asarray(q_ex_rate_m_s, dtype=float).reshape(-1)
    if head.size != q_ex.size:
        raise ValueError("head and q_ex vectors must have the same size.")
    return np.concatenate((head, q_ex)).astype(float, copy=False)


def _split_state(state: np.ndarray, *, n_cells: int) -> tuple[np.ndarray, np.ndarray]:
    """Unpack one contiguous mixed vector into ``(h, q_ex)``."""
    vector = np.asarray(state, dtype=float).reshape(-1)
    if vector.size != 2 * int(n_cells):
        raise ValueError(
            f"Mixed PETSc state must have length {2 * int(n_cells)}; got {int(vector.size)}."
        )
    return (
        vector[:n_cells].astype(float, copy=False),
        vector[n_cells:].astype(float, copy=False),
    )


def _prescribed_head_vector(
    prescribed_head_m_by_cell: np.ndarray | None,
    *,
    n_cells: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the canonical prescribed-head vector and its active mask."""
    prescribed_head = np.asarray(
        prescribed_head_m_by_cell
        if prescribed_head_m_by_cell is not None
        else np.full(n_cells, np.nan, dtype=float),
        dtype=float,
    ).reshape(-1)
    return prescribed_head, np.isfinite(prescribed_head)


def _apply_prescribed_head_constraints(
    head_m: np.ndarray,
    q_ex_rate_m_s: np.ndarray,
    *,
    prescribed_head: np.ndarray,
    prescribed_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Enforce prescribed heads on one mixed state."""
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    q_ex = np.asarray(q_ex_rate_m_s, dtype=float).reshape(-1).copy()
    head[prescribed_mask] = prescribed_head[prescribed_mask]
    q_ex[prescribed_mask] = 0.0
    return head, q_ex


def _initial_steady_q_ex_guess(
    mesh: BoussinesqMesh,
    *,
    head_initial_guess_m: np.ndarray,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> np.ndarray:
    """Return one positive steady warm start for the algebraic overflow rate."""
    guess = np.maximum(
        np.asarray(
            assemble_steady_residual(
                mesh,
                head_m=head_initial_guess_m,
                recharge_rate_m_s=recharge_rate_m_s,
                well_flux_m3_s=well_flux_m3_s,
                prescribed_head_m_by_cell=prescribed_head_m_by_cell,
                drainage_conductance_m2_s=drainage_conductance_m2_s,
                regularization_radius=float(regularization_radius),
            ).saturation_excess_rate_m_s,
            dtype=float,
        ),
        0.0,
    )
    if prescribed_head_m_by_cell is not None:
        prescribed_mask = np.isfinite(
            np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)
        )
        guess[np.asarray(prescribed_mask, dtype=bool)] = 0.0
    return guess


def _initial_transient_q_ex_guess(
    mesh: BoussinesqMesh,
    *,
    head_initial_guess_m: np.ndarray,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> np.ndarray:
    """Return a robust transient warm start for the algebraic overflow rate."""
    recharge = np.asarray(
        recharge_rate_m_s if recharge_rate_m_s is not None else 0.0,
        dtype=float,
    ).reshape(-1)
    well_flux = np.asarray(
        well_flux_m3_s if well_flux_m3_s is not None else 0.0,
        dtype=float,
    ).reshape(-1)
    has_positive_surface_loading = bool(np.any(recharge > 0.0)) or bool(np.any(well_flux < 0.0))
    if not has_positive_surface_loading:
        return np.zeros(mesh.n_cells, dtype=float)
    guess = np.maximum(
        np.asarray(
            assemble_transient_residual(
                mesh,
                head_m=head_initial_guess_m,
                head_prev_m=head_prev_m,
                dt_seconds=float(dt_seconds),
                recharge_rate_m_s=recharge_rate_m_s,
                well_flux_m3_s=well_flux_m3_s,
                prescribed_head_m_by_cell=prescribed_head_m_by_cell,
                drainage_conductance_m2_s=drainage_conductance_m2_s,
                regularization_radius=float(regularization_radius),
            ).saturation_excess_rate_m_s,
            dtype=float,
        ),
        0.0,
    )
    if prescribed_head_m_by_cell is not None:
        prescribed_mask = np.isfinite(
            np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)
        )
        guess[np.asarray(prescribed_mask, dtype=bool)] = 0.0
    return guess


__all__ = [
    "_apply_prescribed_head_constraints",
    "_complementarity_scales",
    "_fischer_burmeister_residual_and_derivatives",
    "_initial_steady_q_ex_guess",
    "_initial_transient_q_ex_guess",
    "_prescribed_head_vector",
    "_split_state",
    "_stack_state",
]
