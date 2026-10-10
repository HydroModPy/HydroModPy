"""Comparison workflow for the steady circular-island ocean validation case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hydromodpy.spatial.geographic.synthetic import RadialIslandTopography, SyntheticGridConfig
from hydromodpy.spatial.geographic.synthetic.topography import build_topography_values
from validation_cases.analytical.steady.boussinesq_circular_island_piecewise_k_2d.runtime_boussinesq import (
    boussinesq_island_cell_heads,
)
from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    load_field_on_expected_grid,
    max_abs_error,
    rmse,
    run_launcher_validation_case,
)
from validation_cases.shared.boussinesq_analytical_runtime import DEFAULT_ENGINE_SOLVER
from validation_cases.shared.loaders import (
    bundle_cell_centers,
    load_cell_polygons,
    load_last_cell_values,
    map_polygons_payload,
    resolve_case_mesh_bundle_dir,
    structured_cell_polygons,
)

from .reference import expected_dupuit_circular_island_head
from .runtime_boussinesq import run_boussinesq_dupuit_circular_island_ocean_case

CASE_DIR = Path(__file__).resolve().parent
# Variants read on their own triangles, the reference at each centroid.
BOUSSINESQ_SOLVERS = frozenset({"boussinesq", DEFAULT_ENGINE_SOLVER})


@dataclass(frozen=True, slots=True)
class DupuitCircularIslandOceanComparison:
    """All arrays and metrics required to validate or plot the case.

    ``heads`` is the head on the structured comparison grid. A run on a mesh
    bundle is projected onto it: a triangle grid by nearest centroid, a Voronoi
    dual by the cell under each grid centre. The radial profile, the azimuthal
    spread and the land freeboard of a Voronoi run are read on its own cells
    instead: each cell centre is a bundle node, so every node ring is compared
    at its exact radius.
    A Boussinesq run is read on its own triangles too, with the reference at
    each centroid; its azimuthal spread is the spread of the head error in a
    bin, since the centroids of one bin sit at different radii.

    ``land_clearance_min`` is the smallest gap between the land surface and the
    simulated head over the island (the freeboard). The analytical solution
    holds only while the water table stays below the land surface.

    Plan-view map of the run, one entry per solver cell, for figures:

    - ``map_cell_polygons``: the cell outline, a list of ``(x, y)`` vertices in
      metres from the island centre, rounded to 0.01 m. A structured grid gives
      one square per cell, row by row from the northern row.
    - ``map_simulated``: the simulated head at the compared (final) time, NaN
      off the island.
    - ``map_reference``: the analytical head at the cell centre, NaN off the island.
    """

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
    land_clearance_min: float
    map_cell_polygons: list[list[tuple[float, float]]]
    map_simulated: np.ndarray
    map_reference: np.ndarray

    @property
    def map_overlay(self) -> dict:
        """The coastline, a circle around the island centre, for the map figure."""
        radius = float(self.metadata["reference"]["island_radius_m"])
        return {"coast_circle": [0.0, 0.0, radius]}


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
    topography = RadialIslandTopography(
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


def _island_dem_at_radius(
    radius: np.ndarray, reference_cfg: dict, solver_name: str | None = None
) -> np.ndarray:
    """Return the land surface the run was given, at the given radii.

    It is the synthetic island of radius ``island_radius_m``, or of the radius
    a variant gives its own topography (``topography_island_radius_m_by_solver``).
    """
    by_solver = reference_cfg.get("topography_island_radius_m_by_solver", {})
    island_radius = float(by_solver.get(solver_name, reference_cfg["island_radius_m"]))
    relief = np.sqrt(np.maximum(0.0, 1.0 - (np.asarray(radius) / island_radius) ** 2))
    return np.where(
        np.asarray(radius) <= island_radius,
        float(reference_cfg["crest_elevation_m"]) * relief,
        float(reference_cfg["ocean_floor_elevation_m"]),
    )


def _value_for_solver(reference_cfg: dict, key: str, solver_name: str | None) -> float:
    """Return ``reference_cfg[key]``, or its ``<key>_by_solver`` override."""
    by_solver = reference_cfg.get(f"{key}_by_solver", {})
    if isinstance(by_solver, dict) and solver_name in by_solver:
        return float(by_solver[solver_name])
    return float(reference_cfg[key])


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


def _reference_head(radius: np.ndarray, reference_cfg: dict) -> np.ndarray:
    return np.asarray(
        expected_dupuit_circular_island_head(
            radius_m=radius,
            island_radius_m=float(reference_cfg["island_radius_m"]),
            recharge_mm_day=float(reference_cfg["recharge_mm_day"]),
            hydraulic_conductivity_m_per_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
            substratum_elevation_m=float(reference_cfg["substratum_elevation_m"]),
            sea_level_m=float(reference_cfg["sea_level_m"]),
        ),
        dtype=float,
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
    expected_shape = tuple(output_cfg.get("expected_shape", ()))
    timestep, heads = load_field_on_expected_grid(
        observable_name=observable_name,
        case_dir=CASE_DIR,
        metadata=case_metadata,
        solver=solver_name,
        expected_shape=expected_shape,
        x_min_m=float(reference_cfg["xmin"]),
        x_max_m=float(reference_cfg["xmin"]) + float(reference_cfg["length_x_m"]),
        y_min_m=float(reference_cfg["ymin"]),
        y_max_m=float(reference_cfg["ymin"]) + float(reference_cfg["length_y_m"]),
        store=result.store,
        sim_id=result.sim_id,
    )

    if expected_shape:
        assert tuple(heads.shape) == expected_shape, (
            f"Unexpected shape for {observable_name}: {heads.shape} != {expected_shape}"
        )

    dem, radius, xx, yy = _build_reference_surfaces(reference_cfg)
    sea_level = float(reference_cfg["sea_level_m"])
    center_x = float(reference_cfg["center_x_m"])
    center_y = float(reference_cfg["center_y_m"])
    land_mask = dem > sea_level
    ocean_mask = dem <= sea_level
    heads = np.asarray(heads, dtype=float)

    bundle_dir = resolve_case_mesh_bundle_dir(CASE_DIR, case_metadata, solver_name)
    native_triangles = solver_name in BOUSSINESQ_SOLVERS
    if bundle_dir is not None:
        cell_heads = load_last_cell_values(
            observable_name=observable_name, store=result.store, sim_id=result.sim_id
        )
        centers, grid_dual = bundle_cell_centers(bundle_dir, cell_heads.size)
        polygons = load_cell_polygons(store=result.store, sim_id=result.sim_id)
    elif native_triangles:
        centers, cell_heads, polygons = boussinesq_island_cell_heads(result)
        grid_dual = "triangle"
    else:
        cell_heads = heads.reshape(-1)
        grid_dual = None
        polygons = structured_cell_polygons(
            x_min=float(reference_cfg["xmin"]),
            x_max=float(reference_cfg["xmin"]) + float(reference_cfg["length_x_m"]),
            y_min=float(reference_cfg["ymin"]),
            y_max=float(reference_cfg["ymin"]) + float(reference_cfg["length_y_m"]),
            nrow=int(heads.shape[0]),
            ncol=int(heads.shape[1]),
        )
        centers = np.asarray([polygon.mean(axis=0) for polygon in polygons], dtype=float)
    # Radii are rounded to the 1 mm precision of the mesh nodes, so a node on
    # the shoreline reads the sea-level DEM of the shoreline and is not land.
    cell_radius = np.round(np.hypot(centers[:, 0] - center_x, centers[:, 1] - center_y), 3)
    cell_dem = _island_dem_at_radius(cell_radius, reference_cfg, solver_name)
    cell_land = cell_dem > sea_level

    if grid_dual == "voronoi" or native_triangles:
        profile_heads, profile_radius, profile_land, profile_dem = (
            cell_heads,
            cell_radius,
            cell_land,
            cell_dem,
        )
    else:
        profile_heads, profile_radius, profile_land, profile_dem = heads, radius, land_mask, dem
    bin_width_m = _value_for_solver(reference_cfg, "radial_bin_width_m", solver_name)
    max_radius_m = _value_for_solver(reference_cfg, "comparison_radius_max_m", solver_name)
    annular_radius, annular_counts, numerical_profile, annular_std = _build_annular_profile(
        heads=profile_heads,
        radius=profile_radius,
        land_mask=profile_land,
        bin_width_m=bin_width_m,
        max_radius_m=max_radius_m,
    )
    analytical_profile = _reference_head(annular_radius, reference_cfg)
    if native_triangles:
        # Mean of the reference over the centroids of each bin, spread of the error.
        _, _, mean_error, annular_std = _build_annular_profile(
            heads=cell_heads - _reference_head(cell_radius, reference_cfg),
            radius=profile_radius,
            land_mask=profile_land,
            bin_width_m=bin_width_m,
            max_radius_m=max_radius_m,
        )
        analytical_profile = numerical_profile - mean_error
    residual_profile = np.asarray(numerical_profile - analytical_profile, dtype=float)

    return DupuitCircularIslandOceanComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        timestep=timestep,
        observable_name=observable_name,
        heads=heads,
        dem=np.asarray(dem, dtype=float),
        radius=np.asarray(radius, dtype=float),
        x_centers=np.asarray(xx, dtype=float),
        y_centers=np.asarray(yy, dtype=float),
        land_mask=np.asarray(land_mask, dtype=bool),
        ocean_mask=np.asarray(ocean_mask, dtype=bool),
        annular_radius=annular_radius,
        annular_counts=annular_counts,
        numerical_profile=numerical_profile,
        analytical_profile=analytical_profile,
        residual_profile=residual_profile,
        rms_error=rmse(numerical_profile, analytical_profile),
        max_error=max_abs_error(numerical_profile, analytical_profile),
        azimuthal_spread=float(np.max(annular_std)) if annular_std.size else 0.0,
        land_clearance_min=float(np.min(profile_dem[profile_land] - profile_heads[profile_land])),
        map_cell_polygons=map_polygons_payload(polygons, origin_x=center_x, origin_y=center_y),
        map_simulated=np.where(cell_land, cell_heads, np.nan),
        map_reference=np.where(cell_land, _reference_head(cell_radius, reference_cfg), np.nan),
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
    if normalized_solver in BOUSSINESQ_SOLVERS:
        result = run_boussinesq_dupuit_circular_island_ocean_case(
            caller_file=caller_file,
            timeout=timeout,
            public_solver_label=normalized_solver,
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
