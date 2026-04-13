"""Shared robustness helpers for regularized-partition nonlinear runtimes."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

_MIN_PARTITION_JACOBIAN_SHIFT = 1.0e-8
_PARTITION_JACOBIAN_SHIFT_FACTOR = 0.2
_SURFACE_TOLERANCE_M = 1.0e-9


def interiorize_regularized_partition_initial_guess(
    mesh: BoussinesqMesh,
    head_initial_guess_m: np.ndarray,
) -> np.ndarray:
    """Move exact top/bottom initial heads to the aquifer interior.

    The regularized-partition Jacobian is piecewise and can become singular
    when the steady initial guess sits exactly on the top or bottom surfaces
    over large dry or fully saturated regions. For steady solves, moving only
    those exact-surface values to the cell midpoint gives a much better Newton
    starting point without changing already-interior guesses.
    """
    head = np.asarray(head_initial_guess_m, dtype=float).reshape(-1).copy()
    z_top = np.asarray(mesh.z_top_m, dtype=float).reshape(-1)
    z_bottom = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)
    midpoint = 0.5 * (z_top + z_bottom)
    on_surface = (head >= (z_top - _SURFACE_TOLERANCE_M)) | (
        head <= (z_bottom + _SURFACE_TOLERANCE_M)
    )
    head[on_surface] = midpoint[on_surface]
    return head


def regularized_partition_jacobian_shift(
    diagonal_values: np.ndarray,
    *,
    residual_norm_inf: float,
    initial_residual_norm_inf: float,
) -> float:
    """Return one adaptive diagonal shift for partition Jacobians.

    The shift acts as a lightweight pseudo-transient regularization on large
    real meshes, keeping Newton systems solvable while letting the shift decay
    as the residual decreases.
    """
    diagonal = np.abs(np.asarray(diagonal_values, dtype=float).reshape(-1))
    positive_diagonal = diagonal[diagonal > 0.0]
    if positive_diagonal.size == 0:
        return float(_MIN_PARTITION_JACOBIAN_SHIFT)

    residual_scale = float(residual_norm_inf) / max(
        float(initial_residual_norm_inf),
        _MIN_PARTITION_JACOBIAN_SHIFT,
    )
    residual_scale = min(max(residual_scale, 0.0), 1.0)
    return max(
        float(_MIN_PARTITION_JACOBIAN_SHIFT),
        float(_PARTITION_JACOBIAN_SHIFT_FACTOR)
        * float(np.median(positive_diagonal))
        * float(residual_scale),
    )


__all__ = [
    "interiorize_regularized_partition_initial_guess",
    "regularized_partition_jacobian_shift",
]
