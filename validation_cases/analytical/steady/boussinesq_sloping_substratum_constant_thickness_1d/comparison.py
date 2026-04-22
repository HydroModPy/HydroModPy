"""Comparison workflow for the sloping-substratum constant-thickness case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from validation_cases.analytical.steady.boussinesq_sloping_substratum import (
    build_linear_substratum_values,
    build_linear_topography_values,
    build_validation_profile_x_values,
)
from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    load_last_npy_array_on_expected_grid,
    max_abs_error,
    max_std_along_axis,
    mean_along_axis,
    rmse,
    run_launcher_validation_case,
)

from .reference import expected_sloping_substratum_constant_thickness_profile_at_x
from .runtime_boussinesq import run_boussinesq_sloping_substratum_constant_thickness_case

CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class BoussinesqSlopingSubstratumConstantThicknessComparison:
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
    bottom_profile: np.ndarray
    numerical_profile: np.ndarray
    analytical_profile: np.ndarray
    residual_profile: np.ndarray
    numerical_thickness_profile: np.ndarray
    analytical_thickness_profile: np.ndarray
    rms_error: float
    max_error: float
    row_spread: float
    reference_discharge_per_width_m2_s: float


def build_boussinesq_sloping_substratum_constant_thickness_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> BoussinesqSlopingSubstratumConstantThicknessComparison:
    """Load one completed run and compare it to the analytical reference."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or None
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name) if tolerances is None else tolerances
    )

    output_cfg = dict(case_metadata.get("output", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    observable_name = str(output_cfg.get("observable_name", "watertable_elevation"))
    expected_shape = tuple(output_cfg.get("expected_shape", ()))
    timestep, heads = load_last_npy_array_on_expected_grid(
        result.postprocess_dir,
        observable_name,
        case_dir=CASE_DIR,
        metadata=case_metadata,
        solver=solver_name,
        expected_shape=expected_shape,
        x_min_m=float(reference_cfg["xmin"]),
        x_max_m=float(reference_cfg["xmax"]),
        collapse_y_to_x_profile=True,
        store=getattr(result, "store", None),
        sim_id=getattr(result, "sim_id", None),
    )

    profile_axis = int(reference_cfg.get("profile_axis", 0))
    numerical_profile = mean_along_axis(heads, axis=profile_axis)
    x = build_validation_profile_x_values(
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        ncol=numerical_profile.size,
        solver_name=solver_name,
    )
    topography_profile = build_linear_topography_values(
        x_m=x,
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        topography_base_elevation_m=float(reference_cfg["topography_base_elevation_m"]),
        topography_right_to_left_amplitude_m=float(
            reference_cfg["topography_right_to_left_amplitude_m"]
        ),
    )
    bottom_profile = build_linear_substratum_values(
        x_m=x,
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        bottom_base_elevation_m=float(reference_cfg["bottom_base_elevation_m"]),
        bottom_right_to_left_amplitude_m=float(reference_cfg["bottom_right_to_left_amplitude_m"]),
    )
    analytical_profile = expected_sloping_substratum_constant_thickness_profile_at_x(
        x_m=x,
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        bottom_base_elevation_m=float(reference_cfg["bottom_base_elevation_m"]),
        bottom_right_to_left_amplitude_m=float(reference_cfg["bottom_right_to_left_amplitude_m"]),
        saturated_thickness_m=float(reference_cfg["target_saturated_thickness_m"]),
    )
    residual_profile = np.asarray(numerical_profile - analytical_profile, dtype=float)
    analytical_thickness_profile = np.asarray(
        analytical_profile - bottom_profile,
        dtype=float,
    )
    numerical_thickness_profile = np.asarray(
        numerical_profile - bottom_profile,
        dtype=float,
    )
    length_m = float(reference_cfg["xmax"]) - float(reference_cfg["xmin"])
    reference_discharge = (
        float(reference_cfg["hydraulic_conductivity_m_per_s"])
        * float(reference_cfg["target_saturated_thickness_m"])
        * (float(reference_cfg["bottom_right_to_left_amplitude_m"]) / length_m)
    )

    return BoussinesqSlopingSubstratumConstantThicknessComparison(
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
        bottom_profile=np.asarray(bottom_profile, dtype=float),
        numerical_profile=np.asarray(numerical_profile, dtype=float),
        analytical_profile=np.asarray(analytical_profile, dtype=float),
        residual_profile=residual_profile,
        numerical_thickness_profile=numerical_thickness_profile,
        analytical_thickness_profile=analytical_thickness_profile,
        rms_error=rmse(numerical_profile, analytical_profile),
        max_error=max_abs_error(numerical_profile, analytical_profile),
        row_spread=max_std_along_axis(heads, axis=profile_axis),
        reference_discharge_per_width_m2_s=float(reference_discharge),
    )


def run_boussinesq_sloping_substratum_constant_thickness_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> BoussinesqSlopingSubstratumConstantThicknessComparison:
    """Run the case and return the full comparison payload."""
    metadata = load_case_metadata(CASE_DIR)
    tolerances = load_case_tolerances(CASE_DIR, solver=solver)
    normalized_solver = None if solver is None else str(solver).strip().lower()
    if normalized_solver == "boussinesq":
        result = run_boussinesq_sloping_substratum_constant_thickness_case(
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
    return build_boussinesq_sloping_substratum_constant_thickness_comparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )


__all__ = [
    "BoussinesqSlopingSubstratumConstantThicknessComparison",
    "build_boussinesq_sloping_substratum_constant_thickness_comparison",
    "run_boussinesq_sloping_substratum_constant_thickness_comparison",
]
