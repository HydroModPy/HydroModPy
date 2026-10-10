"""Comparison workflow for the steady hillslope-drainage linearized case."""

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
from validation_cases.shared.strip_geometry import strip_geometry_for_run

from .reference import (
    build_linear_topography_values,
    expected_linearized_unconfined_hillslope_drainage_profile_at_x,
)

CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class LinearizedUnconfinedHillslopeDrainageComparison:
    """All arrays and scalar diagnostics required by the validation case."""

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    solver: str
    timestep: int
    observable_name: str
    heads: np.ndarray
    x: np.ndarray
    profile_axis: int
    topography_profile: np.ndarray
    numerical_profile: np.ndarray
    analytical_profile: np.ndarray
    residual_profile: np.ndarray
    rms_error: float
    max_error: float
    row_spread: float
    min_numerical_clearance_m: float
    min_analytical_clearance_m: float


def build_linearized_unconfined_hillslope_drainage_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> LinearizedUnconfinedHillslopeDrainageComparison:
    """Load one completed run and compare it against the analytical profile."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or None
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name) if tolerances is None else tolerances
    )

    output_cfg = dict(case_metadata.get("output", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    observable_name = str(output_cfg.get("observable_name", "watertable_elevation"))
    expected_shape_by_solver = output_cfg.get("expected_shape_by_solver", {})
    if isinstance(expected_shape_by_solver, dict) and solver_name in expected_shape_by_solver:
        expected_shape = tuple(expected_shape_by_solver[solver_name])
    else:
        expected_shape = tuple(output_cfg.get("expected_shape", ()))
    timestep, heads = load_field(
        store=result.store,
        sim_id=result.sim_id,
        observable_name=observable_name,
        expected_shape=expected_shape or None,
    )

    if expected_shape:
        assert tuple(heads.shape) == expected_shape, (
            f"Unexpected shape for {observable_name}: {heads.shape} != {expected_shape}"
        )

    profile_axis = int(reference_cfg.get("profile_axis", 0))
    numerical_profile = mean_along_axis(heads, axis=profile_axis)
    geometry = strip_geometry_for_run(
        result,
        ncol=numerical_profile.size,
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
    )
    x = geometry.x
    # Each drain takes C = K * cell_area / b, so the leakance per unit area is
    # K / b on every mesh, whatever the cell sizes.
    hydraulic_conductivity = float(reference_cfg["hydraulic_conductivity_m_per_s"])
    drainage_leakance = hydraulic_conductivity / float(reference_cfg["drain_bed_thickness_m"])
    topography = {
        "topography_base_elevation_m": float(reference_cfg["topography_base_elevation_m"]),
        "topography_right_to_left_amplitude_m": float(
            reference_cfg["topography_right_to_left_amplitude_m"]
        ),
    }
    topography_profile = geometry.profile(
        lambda points: build_linear_topography_values(
            x_m=points,
            xmin=geometry.surface_west_x,
            xmax=geometry.surface_east_x,
            **topography,
        )
    )
    analytical_profile = geometry.profile(
        lambda points: expected_linearized_unconfined_hillslope_drainage_profile_at_x(
            x_m=points,
            surface_west_x=geometry.surface_west_x,
            surface_east_x=geometry.surface_east_x,
            west_x=geometry.west_x,
            east_x=geometry.east_x,
            west_head_m=float(reference_cfg["west_head_m"]),
            east_head_m=float(reference_cfg["east_head_m"]),
            drainage_leakance_per_s=drainage_leakance,
            hydraulic_conductivity_m_per_s=hydraulic_conductivity,
            reference_saturated_thickness_m=float(reference_cfg["reference_saturated_thickness_m"]),
            **topography,
        ),
        within=(geometry.west_x, geometry.east_x),
    )
    residual_profile = np.asarray(numerical_profile - analytical_profile, dtype=float)
    numerical_clearance = np.asarray(numerical_profile - topography_profile, dtype=float)
    analytical_clearance = np.asarray(analytical_profile - topography_profile, dtype=float)

    return LinearizedUnconfinedHillslopeDrainageComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        solver=str(getattr(result, "solver_name", "")),
        timestep=timestep,
        observable_name=observable_name,
        heads=np.asarray(heads, dtype=float),
        x=x,
        profile_axis=profile_axis,
        topography_profile=np.asarray(topography_profile, dtype=float),
        numerical_profile=np.asarray(numerical_profile, dtype=float),
        analytical_profile=np.asarray(analytical_profile, dtype=float),
        residual_profile=residual_profile,
        rms_error=rmse(numerical_profile, analytical_profile),
        max_error=max_abs_error(numerical_profile, analytical_profile),
        row_spread=max_std_along_axis(heads, axis=profile_axis),
        min_numerical_clearance_m=float(np.min(numerical_clearance)),
        min_analytical_clearance_m=float(np.min(analytical_clearance)),
    )


def run_linearized_unconfined_hillslope_drainage_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> LinearizedUnconfinedHillslopeDrainageComparison:
    """Run the case and return the full comparison payload."""
    metadata = load_case_metadata(CASE_DIR)
    tolerances = load_case_tolerances(CASE_DIR, solver=solver)
    result = run_launcher_validation_case(
        case_dir=CASE_DIR,
        test_file=caller_file,
        timeout=timeout,
        solver=solver,
    )
    return build_linearized_unconfined_hillslope_drainage_comparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )
