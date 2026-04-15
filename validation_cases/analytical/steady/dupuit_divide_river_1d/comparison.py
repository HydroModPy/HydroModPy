"""Comparison workflow for the steady Dupuit divide-river validation case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    load_field,
    max_abs_error,
    max_std_along_axis,
    mean_along_axis,
    rmse,
    run_launcher_validation_case,
)

from .reference import expected_dupuit_divide_river_profile
from .runtime_boussinesq import run_boussinesq_dupuit_divide_river_case


CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class DupuitDivideRiverComparison:
    """All arrays and metrics required to validate or plot the case."""

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    timestep: int
    observable_name: str
    heads: np.ndarray
    x: np.ndarray
    profile_axis: int
    numerical_profile: np.ndarray
    analytical_profile: np.ndarray
    residual_profile: np.ndarray
    rms_error: float
    max_error: float
    row_spread: float


def build_dupuit_divide_river_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> DupuitDivideRiverComparison:
    """Load one completed run and compare it to the analytical Dupuit profile."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or None
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name)
        if tolerances is None
        else tolerances
    )

    output_cfg = dict(case_metadata.get("output", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    observable_name = str(output_cfg.get("observable_name", "watertable_elevation"))
    expected_shape = tuple(output_cfg.get("expected_shape", ())) or None
    timestep, heads = load_field(
        postprocess_dir=result.postprocess_dir,
        store=result.store,
        sim_id=result.sim_id,
        observable_name=observable_name,
        expected_shape=expected_shape,
    )

    if expected_shape:
        assert tuple(heads.shape) == expected_shape, (
            f"Unexpected shape for {observable_name}: {heads.shape} != {expected_shape}"
        )

    profile_axis = int(reference_cfg.get("profile_axis", 0))
    numerical_profile = mean_along_axis(heads, axis=profile_axis)
    x = np.linspace(
        float(reference_cfg["xmin"]),
        float(reference_cfg["xmax"]),
        numerical_profile.size,
        dtype=float,
    )
    analytical_profile = expected_dupuit_divide_river_profile(
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        ncol=numerical_profile.size,
        river_head=float(reference_cfg["river_head"]),
        recharge_mm_day=float(reference_cfg["recharge_mm_day"]),
        hydraulic_conductivity_m_per_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
    )
    residual_profile = np.asarray(numerical_profile - analytical_profile, dtype=float)

    return DupuitDivideRiverComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        timestep=timestep,
        observable_name=observable_name,
        heads=np.asarray(heads, dtype=float),
        x=x,
        profile_axis=profile_axis,
        numerical_profile=np.asarray(numerical_profile, dtype=float),
        analytical_profile=np.asarray(analytical_profile, dtype=float),
        residual_profile=residual_profile,
        rms_error=rmse(numerical_profile, analytical_profile),
        max_error=max_abs_error(numerical_profile, analytical_profile),
        row_spread=max_std_along_axis(heads, axis=profile_axis),
    )


def run_dupuit_divide_river_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> DupuitDivideRiverComparison:
    """Run the launcher case and return the full comparison payload."""
    metadata = load_case_metadata(CASE_DIR)
    tolerances = load_case_tolerances(CASE_DIR, solver=solver)
    normalized_solver = None if solver is None else str(solver).strip().lower()
    if normalized_solver == "boussinesq":
        result = run_boussinesq_dupuit_divide_river_case(
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
    return build_dupuit_divide_river_comparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )



