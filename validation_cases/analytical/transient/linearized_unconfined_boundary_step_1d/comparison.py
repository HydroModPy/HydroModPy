"""Comparison workflow for the 1D linearized unconfined boundary-step case."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from validation_cases.analytical.transient.common import (
    TransientHead1DComparison,
    build_transient_head_comparison,
    load_transient_profile_outputs,
)
from validation_cases.analytical.transient.linearized_unconfined_1d import build_profile_x
from validation_cases.shared import run_launcher_validation_case

from .reference import expected_linearized_unconfined_boundary_step_profiles
from .runtime_boussinesq import (
    run_boussinesq_linearized_unconfined_boundary_step_case,
)

CASE_DIR = Path(__file__).resolve().parent


def build_linearized_unconfined_boundary_step_comparison(
    *,
    result,
    solver: str | None = None,
) -> TransientHead1DComparison:
    """Load one completed run and compare it against the linearized analytical solution."""
    loaded = load_transient_profile_outputs(case_dir=CASE_DIR, result=result, solver=solver)
    metadata = loaded.metadata
    reference_cfg = dict(metadata.get("reference", {}))
    period_indices = np.asarray(loaded.period_indices, dtype=float)
    dt_seconds = float(loaded.dt_seconds)
    elapsed_seconds = (
        np.asarray(loaded.elapsed_seconds, dtype=float)
        if loaded.elapsed_seconds is not None
        else (period_indices + 1.0) * dt_seconds
    )
    x = build_profile_x(
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        ncol=loaded.heads.shape[-1],
    )
    period_start_seconds = np.maximum(elapsed_seconds - dt_seconds, 0.0)
    eval_times_seconds = elapsed_seconds
    analytical_profiles = expected_linearized_unconfined_boundary_step_profiles(
        x=x,
        eval_times_seconds=eval_times_seconds,
        period_start_seconds=period_start_seconds,
        base_head_m=float(reference_cfg["base_head_m"]),
        west_head_m=float(reference_cfg["west_head_m"]),
        hydraulic_conductivity_m_per_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        reference_saturated_thickness_m=float(reference_cfg["reference_saturated_thickness_m"]),
        specific_yield=float(reference_cfg["specific_yield"]),
        n_terms=int(reference_cfg.get("n_terms", 400)),
    )
    return build_transient_head_comparison(
        result=result,
        case_dir=CASE_DIR,
        analytical_profiles=analytical_profiles,
        loaded_outputs=loaded,
    )


def run_linearized_unconfined_boundary_step_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> TransientHead1DComparison:
    """Run the launcher case and return the full comparison payload."""
    normalized_solver = None if solver is None else str(solver).strip().lower()
    if normalized_solver == "boussinesq":
        result = run_boussinesq_linearized_unconfined_boundary_step_case(
            caller_file=caller_file,
            timeout=timeout,
        )
    else:
        result = run_launcher_validation_case(
            case_dir=CASE_DIR,
            test_file=caller_file,
            timeout=timeout,
            solver=solver,
        )
    return build_linearized_unconfined_boundary_step_comparison(result=result, solver=solver)
