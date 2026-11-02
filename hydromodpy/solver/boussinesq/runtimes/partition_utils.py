"""Shared robustness helpers for regularized-partition nonlinear runtimes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

import numpy as np

from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)

SolveInputs = TypeVar("SolveInputs", SteadySolveInputs, TransientStepInputs)

_MIN_PARTITION_JACOBIAN_SHIFT = 1.0e-8
_PARTITION_JACOBIAN_SHIFT_FACTOR = 0.2
_SURFACE_TOLERANCE_M = 1.0e-9
_RELEASE_DEPTH_LADDER = (16.0, 8.0, 4.0, 2.0, 1.0)


def solve_by_release_depth_continuation(
    inputs: SolveInputs,
    *,
    direct: RuntimeSolveResult,
    solve: Callable[[SolveInputs], RuntimeSolveResult],
) -> RuntimeSolveResult:
    """Retry a failed solve from a smoother surface closure, back to the depth asked.

    Where the water table reaches the ground over a wide area, the kink of the
    release at the land surface can stop Newton. A larger release depth smooths
    that kink. Each rung starts from the heads of the last one that converged, and
    only the last rung, at the depth the run asks for, can be the answer. So a run
    that converged directly never comes here, and the answer does not depend on the
    ladder. When the last rung fails, the direct failure comes back with its
    diagnostics.
    """
    depth_m = float(inputs.options.regularization_radius)
    guess = inputs.head_initial_guess_m
    result = direct
    for factor in _RELEASE_DEPTH_LADDER:
        options = replace(inputs.options, regularization_radius=depth_m * factor)
        result = solve(replace(inputs, options=options, head_initial_guess_m=guess))
        if result.converged:
            guess = result.head_m
    return result if result.converged else direct


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
    "solve_by_release_depth_continuation",
]
