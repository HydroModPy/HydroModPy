"""Comparison workflow for the 1D linearized unconfined boundary-piecewise case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.common import (
    TransientHead1DComparison,
    build_transient_head_comparison,
    load_transient_profile_outputs,
)
from validation_cases.analytical.transient.linearized_unconfined_1d import build_profile_x
from validation_cases.shared import run_launcher_validation_case

from .reference import expected_linearized_unconfined_boundary_piecewise_profiles


CASE_DIR = Path(__file__).resolve().parent


def build_linearized_unconfined_boundary_piecewise_comparison(
    *,
    result,
    solver: str | None = None,
) -> TransientHead1DComparison:
    """Load one completed run and compare it against the linearized analytical solution."""
    loaded = load_transient_profile_outputs(case_dir=CASE_DIR, result=result, solver=solver)
    metadata = loaded[0]
    reference_cfg = dict(metadata.get("reference", {}))
    period_indices = loaded[3]
    dt_seconds = float(loaded[5])
    x = build_profile_x(
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        ncol=loaded[4].shape[-1],
    )
    period_start_seconds = period_indices.astype(float) * dt_seconds
    eval_times_seconds = (period_indices.astype(float) + 1.0) * dt_seconds
    analytical_profiles = expected_linearized_unconfined_boundary_piecewise_profiles(
        x=x,
        eval_times_seconds=eval_times_seconds,
        period_start_seconds=period_start_seconds,
        west_head_levels_m=reference_cfg["west_head_levels_m"],
        base_head_m=float(reference_cfg["base_head_m"]),
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


def run_linearized_unconfined_boundary_piecewise_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> TransientHead1DComparison:
    """Run the launcher case and return the full comparison payload."""
    result = run_launcher_validation_case(
        case_dir=CASE_DIR,
        test_file=caller_file,
        timeout=timeout,
        solver=solver,
    )
    return build_linearized_unconfined_boundary_piecewise_comparison(result=result, solver=solver)



