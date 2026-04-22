"""Comparison workflow for the steady circular-island ocean validation case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hydromodpy.spatial.geographic.synthetic import SyntheticGridConfig, SyntheticTopographyConfig
from hydromodpy.spatial.geographic.synthetic.topography import build_topography_values
from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    load_field,
    max_abs_error,
    rmse,
    run_launcher_validation_case,
)

from .reference import expected_dupuit_circular_island_head
from .runtime_boussinesq import run_boussinesq_dupuit_circular_island_ocean_case


CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class DupuitCircularIslandOceanComparison:
    """All arrays and metrics required to validate or plot the case."""

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    timestep: int
    observable_name: str
    heads: np.ndarray
    dem: np.ndarray
    radius: np.ndarray
    x_centers: np.ndarray
    y_centers: np.ndarray
    land_mask: np.ndarray
    ocean_mask: np.ndarray
    annular_radius: np.ndarray
    annular_counts: np.ndarray
    numerical_profile: np.ndarray
    analytical_profile: np.ndarray
    residual_profile: np.ndarray
    rms_error: float
    max_error: float
    azimuthal_spread: float
    ocean_head_max_error: float
    land_clearance_min: float


def _build_reference_surfaces(
    reference_cfg: dict,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Rebuild the synthetic DEM and radial coordinates from metadata."""
    grid = SyntheticGridConfig(
        length_x=float(reference_cfg["length_x_m"]),
        length_y=float(reference_cfg["length_y_m"]),
        nx=int(reference_cfg["nx"]),
        ny=int(reference_cfg["ny"]),
        xmin=float(reference_cfg["xmin"]),
        ymin=float(reference_cfg["ymin"]),
        crs=str(reference_cfg.get("crs", "EPSG:2154")),
        nodata=-9999.0,
    )
    topography = SyntheticTopographyConfig(
        kind="radial_island",
        base_elevation=float(reference_cfg["ocean_floor_elevation_m"]),
        crest_elevation=float(reference_cfg["crest_elevation_m"]),
        island_radius=float(reference_cfg["island_radius_m"]),
        center_x=float(reference_cfg["center_x_m"]),
        center_y=float(reference_cfg["center_y_m"]),
    )
    dem = build_topography_values(topography=topography, grid=grid)
    x_centers = float(grid.xmin) + (np.arange(int(grid.ncol), dtype=float) + 0.5) * float(grid.dx)
    y_centers = float(grid.ymin) + (np.arange(int(grid.nrow), dtype=float) + 0.5) * float(grid.dy)
    xx, yy = np.meshgrid(x_centers, y_centers)
    radius = np.sqrt(
        (xx - float(reference_cfg["center_x_m"])) ** 2
        + (yy - float(reference_cfg["center_y_m"])) ** 2
    )
    return dem, radius, xx, yy


def _build_annular_profile(
    *,
    heads: np.ndarray,
    radius: np.ndarray,
    land_mask: np.ndarray,
    bin_width_m: float,
    max_radius_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Aggregate one 2-D head field into annular mean values."""
    if bin_width_m <= 0.0:
        raise ValueError("radial_bin_width_m must be > 0.")
    if max_radius_m <= 0.0:
        raise ValueError("comparison_radius_max_m must be > 0.")

    edges = np.arange(
        0.0, float(max_radius_m) + float(bin_width_m), float(bin_width_m), dtype=float
    )
    if edges[-1] < float(max_radius_m):
        edges = np.append(edges, float(max_radius_m))

    annular_radius: list[float] = []
    annular_counts: list[int] = []
    annular_head: list[float] = []
    annular_std: list[float] = []

    for idx, (left_edge, right_edge) in enumerate(zip(edges[:-1], edges[1:])):
        ring_mask = land_mask & (radius >= left_edge)
        if idx == len(edges) - 2:
            ring_mask &= radius <= right_edge
        else:
            ring_mask &= radius < right_edge
        if not np.any(ring_mask):
            continue
        ring_radius = np.asarray(radius[ring_mask], dtype=float)
        ring_head = np.asarray(heads[ring_mask], dtype=float)
        annular_radius.append(float(np.mean(ring_radius)))
        annular_counts.append(int(ring_head.size))
        annular_head.append(float(np.mean(ring_head)))
        annular_std.append(float(np.std(ring_head)))

    return (
        np.asarray(annular_radius, dtype=float),
        np.asarray(annular_counts, dtype=int),
        np.asarray(annular_head, dtype=float),
        np.asarray(annular_std, dtype=float),
    )


def build_dupuit_circular_island_ocean_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> DupuitCircularIslandOceanComparison:
    """Load one completed run and compare it to the radial Dupuit profile."""
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

    dem, radius, xx, yy = _build_reference_surfaces(reference_cfg)
    sea_level = float(reference_cfg["sea_level_m"])
    land_mask = dem > sea_level
    ocean_mask = dem <= sea_level
    comparison_radius_max_by_solver = reference_cfg.get("comparison_radius_max_by_solver", {})
    comparison_radius_max_m = float(reference_cfg["comparison_radius_max_m"])
    if (
        isinstance(comparison_radius_max_by_solver, dict)
        and solver_name in comparison_radius_max_by_solver
    ):
        comparison_radius_max_m = float(comparison_radius_max_by_solver[solver_name])
    annular_radius, annular_counts, numerical_profile, annular_std = _build_annular_profile(
        heads=np.asarray(heads, dtype=float),
        radius=radius,
        land_mask=land_mask,
        bin_width_m=float(reference_cfg["radial_bin_width_m"]),
        max_radius_m=comparison_radius_max_m,
    )
    analytical_profile = expected_dupuit_circular_island_head(
        radius_m=annular_radius,
        island_radius_m=float(reference_cfg["island_radius_m"]),
        recharge_mm_day=float(reference_cfg["recharge_mm_day"]),
        hydraulic_conductivity_m_per_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        substratum_elevation_m=float(reference_cfg["substratum_elevation_m"]),
        sea_level_m=sea_level,
    )
    residual_profile = np.asarray(numerical_profile - analytical_profile, dtype=float)

    return DupuitCircularIslandOceanComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        timestep=timestep,
        observable_name=observable_name,
        heads=np.asarray(heads, dtype=float),
        dem=np.asarray(dem, dtype=float),
        radius=np.asarray(radius, dtype=float),
        x_centers=np.asarray(xx, dtype=float),
        y_centers=np.asarray(yy, dtype=float),
        land_mask=np.asarray(land_mask, dtype=bool),
        ocean_mask=np.asarray(ocean_mask, dtype=bool),
        annular_radius=annular_radius,
        annular_counts=annular_counts,
        numerical_profile=numerical_profile,
        analytical_profile=np.asarray(analytical_profile, dtype=float),
        residual_profile=residual_profile,
        rms_error=rmse(numerical_profile, analytical_profile),
        max_error=max_abs_error(numerical_profile, analytical_profile),
        azimuthal_spread=float(np.max(annular_std)) if annular_std.size else 0.0,
        ocean_head_max_error=float(
            np.max(np.abs(np.asarray(heads, dtype=float)[ocean_mask] - sea_level))
        ),
        land_clearance_min=float(
            np.min(
                np.asarray(dem, dtype=float)[land_mask] - np.asarray(heads, dtype=float)[land_mask]
            )
        ),
    )


def run_dupuit_circular_island_ocean_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> DupuitCircularIslandOceanComparison:
    """Run the launcher case and return the full comparison payload."""
    metadata = load_case_metadata(CASE_DIR)
    tolerances = load_case_tolerances(CASE_DIR, solver=solver)
    normalized_solver = None if solver is None else str(solver).strip().lower()
    if normalized_solver == "boussinesq":
        result = run_boussinesq_dupuit_circular_island_ocean_case(
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
    return build_dupuit_circular_island_ocean_comparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )
