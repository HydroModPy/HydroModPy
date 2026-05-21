"""PETSc SNESVI configuration and solver diagnostics."""

from __future__ import annotations

import os
from typing import Any

_DEFAULT_PC_FACTOR_SHIFT_AMOUNT = 1.0e-10


def configure_vi_snes(
    PETSc,
    snes,
    *,
    tol_residual_inf: float,
    max_iterations: int,
) -> None:
    """Apply experimental PETSc VI defaults while keeping options overrideable."""
    snes.setType("vinewtonrsls")
    max_iteration_count = int(max_iterations)
    snes.setTolerances(
        atol=float(tol_residual_inf),
        rtol=0.0,
        stol=0.0,
        max_it=max_iteration_count,
    )
    snes.setMaxFunctionEvaluations(max(10000, max_iteration_count * 20))
    ksp = snes.getKSP()
    if ksp is not None:
        ksp.setType("preonly")
        ksp.setTolerances(rtol=1.0e-12, atol=0.0, max_it=1)
        pc = ksp.getPC()
        if pc is not None:
            pc.setType("lu")
            pc.setFactorShift(
                PETSc.Mat.FactorShiftType.NONZERO,
                _DEFAULT_PC_FACTOR_SHIFT_AMOUNT,
            )
            pc.setFromOptions()
        ksp.setFromOptions()
    snes.setFromOptions()


def accept_failed_snes_by_projected_tolerance(
    *,
    converged_reason: int,
    residual_norm_inf_value: float,
    tol_residual_inf: float,
    max_violation_lower_m: float,
    max_violation_upper_m: float,
    tol_h: float,
) -> bool:
    """Accept a failed PETSc SNESVI stop only when the VI policy is satisfied."""
    return (
        int(converged_reason) <= 0
        and float(residual_norm_inf_value) <= float(tol_residual_inf)
        and float(max_violation_lower_m) <= float(tol_h)
        and float(max_violation_upper_m) <= float(tol_h)
    )


def petsc_solver_configuration(snes) -> dict[str, Any]:
    """Return PETSc SNES/KSP/PC option values when petsc4py exposes them."""
    values: dict[str, Any] = {"petsc_options": os.environ.get("PETSC_OPTIONS")}
    try:
        values["snes_type"] = snes.getType()
    except Exception:
        values["snes_type"] = None
    try:
        ksp = snes.getKSP()
    except Exception:
        ksp = None
    if ksp is None:
        values.update(
            {
                "ksp_type": None,
                "pc_type": None,
                "pc_factor_shift_type": None,
                "pc_factor_shift_amount": None,
            }
        )
        return values
    try:
        values["ksp_type"] = ksp.getType()
    except Exception:
        values["ksp_type"] = None
    try:
        pc = ksp.getPC()
    except Exception:
        pc = None
    if pc is None:
        values["pc_type"] = None
        values["pc_factor_shift_type"] = None
        values["pc_factor_shift_amount"] = None
        return values
    try:
        values["pc_type"] = pc.getType()
    except Exception:
        values["pc_type"] = None
    try:
        values["pc_factor_shift_type"] = str(pc.getFactorShiftType())
    except Exception:
        values["pc_factor_shift_type"] = None
    try:
        values["pc_factor_shift_amount"] = float(pc.getFactorShiftAmount())
    except Exception:
        values["pc_factor_shift_amount"] = None
    return values


def linear_iteration_count(snes) -> int:
    """Return PETSc linear iterations when available."""
    try:
        return int(snes.getLinearSolveIterations())
    except Exception:
        pass
    try:
        ksp = snes.getKSP()
        if ksp is not None:
            return int(ksp.getIterationNumber())
    except Exception:
        pass
    return 0


def linear_converged_reason(snes) -> int:
    """Return PETSc KSP converged reason when available."""
    try:
        ksp = snes.getKSP()
        if ksp is not None:
            return int(ksp.getConvergedReason())
    except Exception:
        pass
    return 0


def ksp_reason_label(reason: int) -> str:
    """Return one readable label for common PETSc KSP reasons."""
    labels = {
        2: "KSP_CONVERGED_RTOL_NORMAL",
        3: "KSP_CONVERGED_ATOL_NORMAL",
        4: "KSP_CONVERGED_RTOL",
        5: "KSP_CONVERGED_ATOL",
        6: "KSP_CONVERGED_ITS",
        7: "KSP_CONVERGED_CG_NEG_CURVE",
        8: "KSP_CONVERGED_CG_CONSTRAINED",
        9: "KSP_CONVERGED_STEP_LENGTH",
        -2: "KSP_DIVERGED_NULL",
        -3: "KSP_DIVERGED_ITS",
        -4: "KSP_DIVERGED_DTOL",
        -5: "KSP_DIVERGED_BREAKDOWN",
        -6: "KSP_DIVERGED_BREAKDOWN_BICG",
        -7: "KSP_DIVERGED_NONSYMMETRIC",
        -8: "KSP_DIVERGED_INDEFINITE_PC",
        -9: "KSP_DIVERGED_NANORINF",
        -10: "KSP_DIVERGED_INDEFINITE_MAT",
        -11: "KSP_DIVERGED_PC_FAILED",
        0: "KSP_CONVERGED_ITERATING",
    }
    return labels.get(int(reason), f"KSP_REASON_{int(reason)}")
