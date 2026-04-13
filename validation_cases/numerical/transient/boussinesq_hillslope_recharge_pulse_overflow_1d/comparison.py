"""Scenario orchestration for the transient hillslope pulse-overflow case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from validation_cases.shared import load_case_metadata

from .diagnostics import (
    SolverOverflowDiagnostics,
    build_hillslope_overflow_diagnostics,
)
from .runtime_boussinesq import (
    CASE_DIR,
    DEFAULT_SOLVER,
    resolve_solver_variant,
    run_boussinesq_hillslope_overflow_case,
)


@dataclass(frozen=True, slots=True)
class HillslopeOverflowScenario:
    """Primary run plus an optional comparison run on the same forcing."""

    metadata: dict
    primary: SolverOverflowDiagnostics
    secondary: SolverOverflowDiagnostics | None = None
    secondary_error: str | None = None
    secondary_solver_name: str | None = None


def run_hillslope_overflow_scenario(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
    compare_solver: str | None = None,
    overflow_threshold_mm_day: float | None = None,
    forcing_preset: str | None = None,
    forcing_scale: float = 1.0,
    east_head_m: float | None = None,
    initial_head_m: float | None = None,
    dt_days: float | None = None,
    runtime_max_iterations: int | None = None,
    runtime_tol_residual_inf: float | None = None,
) -> HillslopeOverflowScenario:
    """Run the primary solver and, optionally, a second solver for visual comparison."""
    metadata = load_case_metadata(CASE_DIR)
    primary_solver = resolve_solver_variant(DEFAULT_SOLVER if solver is None else solver)
    secondary_solver = None
    if compare_solver is not None:
        secondary_solver = resolve_solver_variant(compare_solver)
        if secondary_solver.solver_name == primary_solver.solver_name:
            raise ValueError("compare_solver must differ from solver.")

    primary_result = run_boussinesq_hillslope_overflow_case(
        caller_file=caller_file,
        timeout=timeout,
        solver=primary_solver.solver_name,
        forcing_preset=forcing_preset,
        forcing_scale=float(forcing_scale),
        east_head_m=east_head_m,
        initial_head_m=initial_head_m,
        dt_days=dt_days,
        runtime_max_iterations=runtime_max_iterations,
        runtime_tol_residual_inf=runtime_tol_residual_inf,
    )
    primary = build_hillslope_overflow_diagnostics(
        result=primary_result,
        metadata=metadata,
        overflow_threshold_mm_day=overflow_threshold_mm_day,
    )

    secondary = None
    secondary_error = None
    if secondary_solver is not None:
        try:
            secondary_result = run_boussinesq_hillslope_overflow_case(
                caller_file=caller_file,
                timeout=timeout,
                solver=secondary_solver.solver_name,
                forcing_preset=forcing_preset,
                forcing_scale=float(forcing_scale),
                east_head_m=east_head_m,
                initial_head_m=initial_head_m,
                dt_days=dt_days,
                runtime_max_iterations=runtime_max_iterations,
                runtime_tol_residual_inf=runtime_tol_residual_inf,
            )
        except RuntimeError as exc:
            secondary_error = str(exc)
        else:
            secondary = build_hillslope_overflow_diagnostics(
                result=secondary_result,
                metadata=metadata,
                overflow_threshold_mm_day=overflow_threshold_mm_day,
            )

    return HillslopeOverflowScenario(
        metadata=metadata,
        primary=primary,
        secondary=secondary,
        secondary_error=secondary_error,
        secondary_solver_name=(
            None if secondary_solver is None else secondary_solver.solver_name
        ),
    )


__all__ = [
    "HillslopeOverflowScenario",
    "run_hillslope_overflow_scenario",
]
