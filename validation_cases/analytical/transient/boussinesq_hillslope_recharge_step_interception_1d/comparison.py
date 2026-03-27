"""Comparison workflow for the transient hillslope recharge-step interception case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    load_npy_time_series_arrays,
    max_abs_error,
    max_std_along_axis,
    rmse,
)

from .reference import (
    SECONDS_PER_DAY,
    build_hillslope_topography_values,
    build_interception_trajectory_from_profiles,
    expected_linearized_hillslope_recharge_step_profiles,
    first_inland_interception_time_seconds,
)
from .runtime_boussinesq import (
    run_boussinesq_hillslope_recharge_step_interception_case,
)


CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class BoussinesqTransientHillslopeInterceptionComparison:
    """Arrays and metrics required to validate the transient interception case."""

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    observable_name: str
    period_indices: np.ndarray
    elapsed_seconds: np.ndarray
    elapsed_days: np.ndarray
    heads: np.ndarray
    x: np.ndarray
    topography_profile: np.ndarray
    numerical_profiles: np.ndarray
    analytical_profiles: np.ndarray
    numerical_interception_x_by_time: np.ndarray
    analytical_interception_x_by_time: np.ndarray
    inland_contact_threshold_x_m: float
    numerical_onset_time_days: float
    analytical_onset_time_days: float
    onset_time_error_days: float
    trajectory_rmse_m: float
    trajectory_max_error_m: float
    trajectory_reversal_m: float
    row_spread: float
    max_positive_clearance_m: float

    @property
    def final_elapsed_days(self) -> float:
        return float(self.elapsed_days[-1])


def _load_outputs(*, result: ValidationRunResult, metadata: dict) -> tuple[str, np.ndarray, np.ndarray]:
    output_cfg = dict(metadata.get("output", {}))
    observable_name = str(output_cfg.get("observable_name", "watertable_elevation"))
    period_indices, heads = load_npy_time_series_arrays(
        result.postprocess_dir,
        observable_name,
    )

    expected_periods = int(output_cfg.get("expected_periods", 0))
    if expected_periods > 0:
        assert heads.shape[0] == expected_periods, (
            f"Unexpected number of periods for {observable_name}: "
            f"{heads.shape[0]} != {expected_periods}"
        )

    expected_spatial_shape = tuple(output_cfg.get("expected_spatial_shape", ()))
    if expected_spatial_shape:
        assert tuple(heads.shape[1:]) == expected_spatial_shape, (
            f"Unexpected spatial shape for {observable_name}: "
            f"{tuple(heads.shape[1:])} != {expected_spatial_shape}"
        )
    return observable_name, period_indices, np.asarray(heads, dtype=float)


def build_boussinesq_hillslope_recharge_step_interception_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> BoussinesqTransientHillslopeInterceptionComparison:
    """Load one completed run and compare it to the linearized onset approximation."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or None
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name)
        if tolerances is None
        else tolerances
    )
    observable_name, period_indices, heads = _load_outputs(
        result=result,
        metadata=case_metadata,
    )

    reference_cfg = dict(case_metadata.get("reference", {}))
    time_cfg = dict(case_metadata.get("time", {}))
    dt_seconds = float(time_cfg["dt_seconds"])
    elapsed_seconds = period_indices.astype(float) * dt_seconds
    elapsed_days = elapsed_seconds / SECONDS_PER_DAY

    ncol = int(heads.shape[-1])
    dx = (float(reference_cfg["xmax"]) - float(reference_cfg["xmin"])) / float(ncol)
    x = float(reference_cfg["xmin"]) + ((np.arange(ncol, dtype=float) + 0.5) * dx)
    topography_profile = build_hillslope_topography_values(
        x_m=x,
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        toe_elevation_m=float(reference_cfg["toe_elevation_m"]),
        slope_m_per_m=float(reference_cfg["topography_slope_m_per_m"]),
    )
    numerical_profiles = np.asarray(np.mean(heads, axis=1), dtype=float)
    analytical_profiles = expected_linearized_hillslope_recharge_step_profiles(
        x_m=x,
        eval_times_seconds=elapsed_seconds,
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        base_head_m=float(reference_cfg["base_head_m"]),
        recharge_mm_day=float(reference_cfg["recharge_mm_day"]),
        hydraulic_conductivity_m_per_s=float(
            reference_cfg["hydraulic_conductivity_m_per_s"]
        ),
        reference_saturated_thickness_m=float(
            reference_cfg["reference_saturated_thickness_m"]
        ),
        specific_yield=float(reference_cfg["specific_yield"]),
        n_terms=int(reference_cfg.get("n_terms", 400)),
    )

    contact_tolerance_m = float(reference_cfg.get("numerical_contact_tolerance_m", 0.05))
    numerical_interception_x_by_time = build_interception_trajectory_from_profiles(
        x_m=x,
        profiles_m=numerical_profiles,
        topography_profile_m=topography_profile,
        contact_tolerance_m=contact_tolerance_m,
    )
    analytical_interception_x_by_time = build_interception_trajectory_from_profiles(
        x_m=x,
        profiles_m=analytical_profiles,
        topography_profile_m=topography_profile,
        contact_tolerance_m=contact_tolerance_m,
    )

    inland_contact_threshold_x_m = float(reference_cfg["inland_contact_threshold_x_m"])
    numerical_onset_time_seconds = first_inland_interception_time_seconds(
        interception_x_by_time_m=numerical_interception_x_by_time,
        elapsed_seconds=elapsed_seconds,
        inland_contact_threshold_x_m=inland_contact_threshold_x_m,
    )
    analytical_onset_time_seconds = first_inland_interception_time_seconds(
        interception_x_by_time_m=analytical_interception_x_by_time,
        elapsed_seconds=elapsed_seconds,
        inland_contact_threshold_x_m=inland_contact_threshold_x_m,
    )
    if not np.isfinite(numerical_onset_time_seconds):
        raise ValueError("The numerical trajectory never reaches inland interception.")
    if not np.isfinite(analytical_onset_time_seconds):
        raise ValueError("The analytical approximation never reaches inland interception.")

    finite_mask = np.isfinite(numerical_interception_x_by_time) & np.isfinite(
        analytical_interception_x_by_time
    )
    if not np.any(finite_mask):
        raise ValueError("No overlapping finite interception trajectory could be compared.")
    numerical_traj = np.asarray(numerical_interception_x_by_time[finite_mask], dtype=float)
    analytical_traj = np.asarray(analytical_interception_x_by_time[finite_mask], dtype=float)
    reversal_values = np.diff(numerical_traj)
    trajectory_reversal_m = (
        float(np.max(np.maximum(reversal_values, 0.0)))
        if reversal_values.size
        else 0.0
    )
    max_positive_clearance_m = float(
        np.max(numerical_profiles - topography_profile[None, :])
    )

    return BoussinesqTransientHillslopeInterceptionComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        observable_name=observable_name,
        period_indices=period_indices,
        elapsed_seconds=elapsed_seconds,
        elapsed_days=elapsed_days,
        heads=heads,
        x=np.asarray(x, dtype=float),
        topography_profile=np.asarray(topography_profile, dtype=float),
        numerical_profiles=np.asarray(numerical_profiles, dtype=float),
        analytical_profiles=np.asarray(analytical_profiles, dtype=float),
        numerical_interception_x_by_time=np.asarray(
            numerical_interception_x_by_time,
            dtype=float,
        ),
        analytical_interception_x_by_time=np.asarray(
            analytical_interception_x_by_time,
            dtype=float,
        ),
        inland_contact_threshold_x_m=inland_contact_threshold_x_m,
        numerical_onset_time_days=float(numerical_onset_time_seconds / SECONDS_PER_DAY),
        analytical_onset_time_days=float(analytical_onset_time_seconds / SECONDS_PER_DAY),
        onset_time_error_days=abs(
            float(numerical_onset_time_seconds - analytical_onset_time_seconds)
            / SECONDS_PER_DAY
        ),
        trajectory_rmse_m=rmse(numerical_traj, analytical_traj),
        trajectory_max_error_m=max_abs_error(numerical_traj, analytical_traj),
        trajectory_reversal_m=trajectory_reversal_m,
        row_spread=max_std_along_axis(heads, axis=1),
        max_positive_clearance_m=max_positive_clearance_m,
    )


def run_boussinesq_hillslope_recharge_step_interception_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> BoussinesqTransientHillslopeInterceptionComparison:
    """Run the local Boussinesq recharge-step interception case and compare it."""
    normalized_solver = None if solver is None else str(solver).strip().lower()
    if normalized_solver not in {None, "boussinesq"}:
        raise ValueError("This validation case supports only solver='boussinesq'.")

    metadata = load_case_metadata(CASE_DIR)
    tolerances = load_case_tolerances(CASE_DIR, solver="boussinesq")
    result = run_boussinesq_hillslope_recharge_step_interception_case(
        caller_file=caller_file,
        timeout=timeout,
    )
    return build_boussinesq_hillslope_recharge_step_interception_comparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )


__all__ = [
    "BoussinesqTransientHillslopeInterceptionComparison",
    "build_boussinesq_hillslope_recharge_step_interception_comparison",
    "run_boussinesq_hillslope_recharge_step_interception_comparison",
]
