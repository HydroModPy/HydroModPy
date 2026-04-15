"""Comparison workflow for the steady Boussinesq hillslope-interception case."""

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
)

from .reference import (
    build_hillslope_topography_values,
    expected_boussinesq_hillslope_profile_at_x,
    find_boussinesq_hillslope_interception_x,
)
from .runtime_boussinesq import run_boussinesq_hillslope_interception_case


CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class BoussinesqHillslopeInterceptionComparison:
    """Arrays and metrics required to validate the hillslope-interception case."""

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    timestep: int
    observable_name: str
    heads: np.ndarray
    x: np.ndarray
    profile_axis: int
    topography_profile: np.ndarray
    analytical_profile: np.ndarray
    numerical_profile: np.ndarray
    dry_zone_mask: np.ndarray
    contact_tolerance_m: float
    analytical_interception_x_m: float
    numerical_interception_x_m: float
    interception_x_error_m: float
    dry_zone_rmse: float
    dry_zone_max_error: float
    row_spread: float
    min_clearance_m: float
    max_clearance_m: float


def _resolve_numerical_interception_x(
    *,
    x: np.ndarray,
    clearance_m: np.ndarray,
    contact_tolerance_m: float,
) -> float:
    """Return the inland start of the toe-side contact block."""
    saturated = np.asarray(clearance_m, dtype=float) >= -float(contact_tolerance_m)
    start_index = len(saturated)
    for idx in range(len(saturated) - 1, -1, -1):
        if saturated[idx]:
            start_index = idx
        elif start_index < len(saturated):
            break
    if start_index >= len(saturated):
        raise ValueError("No toe-side interception block found in the numerical profile.")
    return float(np.asarray(x, dtype=float)[start_index])


def build_boussinesq_hillslope_interception_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> BoussinesqHillslopeInterceptionComparison:
    """Load one completed run and compare it to the analytical interception target."""
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
    dx = (
        float(reference_cfg["xmax"]) - float(reference_cfg["xmin"])
    ) / float(numerical_profile.size)
    x = float(reference_cfg["xmin"]) + (
        (np.arange(numerical_profile.size, dtype=float) + 0.5) * dx
    )

    analytical_profile = expected_boussinesq_hillslope_profile_at_x(
        x_m=x,
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        east_head_m=float(reference_cfg["east_head_m"]),
        recharge_mm_day=float(reference_cfg["recharge_mm_day"]),
        hydraulic_conductivity_m_per_s=float(
            reference_cfg["hydraulic_conductivity_m_per_s"]
        ),
    )
    topography_profile = build_hillslope_topography_values(
        x_m=x,
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        toe_elevation_m=float(reference_cfg["toe_elevation_m"]),
        slope_m_per_m=float(reference_cfg["topography_slope_m_per_m"]),
    )
    analytical_interception_x_m = find_boussinesq_hillslope_interception_x(
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        east_head_m=float(reference_cfg["east_head_m"]),
        recharge_mm_day=float(reference_cfg["recharge_mm_day"]),
        hydraulic_conductivity_m_per_s=float(
            reference_cfg["hydraulic_conductivity_m_per_s"]
        ),
        toe_elevation_m=float(reference_cfg["toe_elevation_m"]),
        slope_m_per_m=float(reference_cfg["topography_slope_m_per_m"]),
        search_samples=int(reference_cfg.get("interception_search_samples", 20001)),
    )
    contact_tolerance_m = float(reference_cfg.get("numerical_contact_tolerance_m", 0.02))
    clearance_m = np.asarray(numerical_profile - topography_profile, dtype=float)
    numerical_interception_x_m = _resolve_numerical_interception_x(
        x=x,
        clearance_m=clearance_m,
        contact_tolerance_m=contact_tolerance_m,
    )

    dry_zone_mask = np.asarray(x < analytical_interception_x_m, dtype=bool)
    if not np.any(dry_zone_mask):
        raise ValueError("Dry-zone mask is empty; the interception point is too close to the divide.")

    return BoussinesqHillslopeInterceptionComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        timestep=timestep,
        observable_name=observable_name,
        heads=np.asarray(heads, dtype=float),
        x=np.asarray(x, dtype=float),
        profile_axis=profile_axis,
        topography_profile=np.asarray(topography_profile, dtype=float),
        analytical_profile=np.asarray(analytical_profile, dtype=float),
        numerical_profile=np.asarray(numerical_profile, dtype=float),
        dry_zone_mask=dry_zone_mask,
        contact_tolerance_m=contact_tolerance_m,
        analytical_interception_x_m=float(analytical_interception_x_m),
        numerical_interception_x_m=float(numerical_interception_x_m),
        interception_x_error_m=abs(
            float(numerical_interception_x_m) - float(analytical_interception_x_m)
        ),
        dry_zone_rmse=rmse(
            np.asarray(numerical_profile[dry_zone_mask], dtype=float),
            np.asarray(analytical_profile[dry_zone_mask], dtype=float),
        ),
        dry_zone_max_error=max_abs_error(
            np.asarray(numerical_profile[dry_zone_mask], dtype=float),
            np.asarray(analytical_profile[dry_zone_mask], dtype=float),
        ),
        row_spread=max_std_along_axis(heads, axis=profile_axis),
        min_clearance_m=float(np.min(clearance_m)),
        max_clearance_m=float(np.max(clearance_m)),
    )


def run_boussinesq_hillslope_interception_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> BoussinesqHillslopeInterceptionComparison:
    """Run the local Boussinesq hillslope case and return the comparison payload."""
    normalized_solver = None if solver is None else str(solver).strip().lower()
    if normalized_solver not in {None, "boussinesq"}:
        raise ValueError("This validation case supports only solver='boussinesq'.")

    metadata = load_case_metadata(CASE_DIR)
    tolerances = load_case_tolerances(CASE_DIR, solver="boussinesq")
    result = run_boussinesq_hillslope_interception_case(
        caller_file=caller_file,
        timeout=timeout,
    )
    return build_boussinesq_hillslope_interception_comparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )
