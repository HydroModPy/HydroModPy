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
    run_launcher_validation_case,
)
from validation_cases.shared.boussinesq_analytical_runtime import DEFAULT_ENGINE_SOLVER
from validation_cases.shared.loaders import run_dual_cell_centers
from validation_cases.shared.strip_geometry import strip_geometry_for_run

from .reference import (
    build_hillslope_topography_values,
    expected_hillslope_seepage_profile_at_x,
    hillslope_contact_x,
    hillslope_seepage_emergence_x,
)
from .runtime_boussinesq import run_boussinesq_hillslope_interception_case

CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class BoussinesqHillslopeInterceptionComparison:
    """Arrays and metrics required to validate the hillslope-interception case.

    The reference is the exact free-boundary solution with a seepage face.
    On a MODFLOW run the land surface is a drain, so the head may stand above it
    by the head the drain needs to pass the recharge: ``max_clearance_m`` is that
    excess, small but not zero. On an unstructured mesh the reference is averaged
    over the same x bins as the model.
    ``analytical_interception_x_m`` is where its head comes within the contact
    tolerance of the surface, read like the model; ``analytical_emergence_x_m``
    is the tangent point itself. The profile metrics cover every column.
    """

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
    analytical_emergence_x_m: float
    analytical_interception_x_m: float
    numerical_interception_x_m: float
    interception_x_error_m: float
    profile_rmse: float
    profile_max_error: float
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
        load_case_tolerances(CASE_DIR, solver=solver_name) if tolerances is None else tolerances
    )

    output_cfg = dict(case_metadata.get("output", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    observable_name = str(output_cfg.get("observable_name", "watertable_elevation"))
    expected_shape = tuple(output_cfg.get("expected_shape", ())) or None
    timestep, heads = load_field(
        store=result.store,
        sim_id=result.sim_id,
        observable_name=observable_name,
        expected_shape=expected_shape,
        cell_centers=run_dual_cell_centers(result, case_metadata),
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

    contact_tolerance_m = float(reference_cfg.get("numerical_contact_tolerance_m", 0.02))
    profile_kwargs = {
        "xmin": float(reference_cfg["xmin"]),
        "xmax": float(reference_cfg["xmax"]),
        "east_head_m": float(reference_cfg["east_head_m"]),
        "toe_elevation_m": float(reference_cfg["toe_elevation_m"]),
        "slope_m_per_m": float(reference_cfg["topography_slope_m_per_m"]),
        "bottom_elevation_m": float(reference_cfg["bottom_elevation_m"]),
        "recharge_mm_day": float(reference_cfg["recharge_mm_day"]),
        "hydraulic_conductivity_m_per_s": float(reference_cfg["hydraulic_conductivity_m_per_s"]),
    }
    # The surface is flat past the center of the end columns: no point is read beyond.
    surface_span = (geometry.surface_west_x, geometry.surface_east_x)
    analytical_profile = geometry.profile(
        lambda points: expected_hillslope_seepage_profile_at_x(x_m=points, **profile_kwargs),
        within=surface_span,
    )
    topography_profile = geometry.profile(
        lambda points: build_hillslope_topography_values(
            x_m=points,
            xmin=float(reference_cfg["xmin"]),
            xmax=float(reference_cfg["xmax"]),
            toe_elevation_m=float(reference_cfg["toe_elevation_m"]),
            slope_m_per_m=float(reference_cfg["topography_slope_m_per_m"]),
        ),
        within=surface_span,
    )
    analytical_emergence_x_m = hillslope_seepage_emergence_x(
        **{key: value for key, value in profile_kwargs.items() if key != "east_head_m"}
    )
    analytical_interception_x_m = hillslope_contact_x(
        contact_tolerance_m=contact_tolerance_m,
        search_samples=int(reference_cfg.get("interception_search_samples", 20001)),
        **profile_kwargs,
    )
    clearance_m = np.asarray(numerical_profile - topography_profile, dtype=float)
    numerical_interception_x_m = _resolve_numerical_interception_x(
        x=x,
        clearance_m=clearance_m,
        contact_tolerance_m=contact_tolerance_m,
    )

    dry_zone_mask = np.asarray(x < analytical_emergence_x_m, dtype=bool)
    if not np.any(dry_zone_mask):
        raise ValueError(
            "Dry-zone mask is empty; the interception point is too close to the divide."
        )

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
        analytical_emergence_x_m=float(analytical_emergence_x_m),
        analytical_interception_x_m=float(analytical_interception_x_m),
        numerical_interception_x_m=float(numerical_interception_x_m),
        interception_x_error_m=abs(
            float(numerical_interception_x_m) - float(analytical_interception_x_m)
        ),
        profile_rmse=rmse(numerical_profile, analytical_profile),
        profile_max_error=max_abs_error(numerical_profile, analytical_profile),
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
    """Run one variant of the hillslope case and return the comparison payload.

    A Boussinesq variant runs the in-house runtime. Any other solver runs the
    launcher case with a drain at the land surface.
    """
    normalized_solver = None if solver is None else str(solver).strip().lower()
    metadata = load_case_metadata(CASE_DIR)
    if normalized_solver in {None, "boussinesq", DEFAULT_ENGINE_SOLVER}:
        solver_label = normalized_solver or "boussinesq"
        result = run_boussinesq_hillslope_interception_case(
            caller_file=caller_file,
            timeout=timeout,
            public_solver_label=solver_label,
        )
    else:
        solver_label = normalized_solver
        result = run_launcher_validation_case(
            case_dir=CASE_DIR,
            test_file=caller_file,
            timeout=timeout,
            solver=solver_label,
        )
    return build_boussinesq_hillslope_interception_comparison(
        result=result,
        metadata=metadata,
        tolerances=load_case_tolerances(CASE_DIR, solver=solver_label),
    )
