"""Comparison workflow for the late-time unconfined pumping 2D validation case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from validation_cases.analytical.transient.common import (
    SECONDS_PER_DAY,
    TransientRadialDrawdownComparison,
    build_uniform_axis_centers,
    extract_radial_monitor_series,
    load_transient_profile_outputs,
)
from validation_cases.shared import (
    load_case_metadata,
    load_case_tolerances,
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

from .reference import expected_late_time_unconfined_pumping_drawdown
from .runtime_boussinesq import (
    boussinesq_sampled_centroids,
    run_boussinesq_late_time_unconfined_pumping_case,
)

CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class LateTimeUnconfinedPumpingComparison(TransientRadialDrawdownComparison):
    """Radial drawdown comparison, with a plan-view map of the final head.

    A run on a mesh bundle is projected onto the structured grid before the
    monitor points are read: a triangle grid by nearest centroid, a Voronoi
    dual by the cell under each grid centre.

    Plan-view map at the final output time, one entry per solver cell, for figures:

    - ``map_cell_polygons``: the cell outline, a list of ``(x, y)`` vertices in
      metres from the well, rounded to 0.01 m. A structured grid gives one
      square per cell, row by row from the northern row.
    - ``map_simulated``: the simulated head.
    - ``map_reference``: the head of the reference at the cell centre, NaN in
      the well cell, where the reference is singular.
    - ``map_overlay``: the well, at the origin of the map.
    """

    map_cell_polygons: list[list[tuple[float, float]]]
    map_simulated: np.ndarray
    map_reference: np.ndarray
    map_overlay: dict


def _sampled_cell_radii(
    *,
    result,
    solver: str | None,
    metadata: dict,
    observable_name: str,
    points_xy: np.ndarray,
    center_xy: tuple[float, float],
) -> np.ndarray | None:
    """Radius of the solver cell each monitor point reads, on a mesh bundle.

    The projection gives a structured cell the value of the solver cell with the
    nearest centre. That centre lies off the monitor point, by 1 to 18 m on the
    Voronoi dual of this case and up to 30 m on the triangles of the Boussinesq
    runtime, so the reference is read at its radius. Returns None on a
    structured grid, where the point is the cell centre.
    """
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or solver
    if solver_name in {"boussinesq", DEFAULT_ENGINE_SOLVER}:
        held = boussinesq_sampled_centroids(result, points_xy)
        return np.hypot(held[:, 0] - center_xy[0], held[:, 1] - center_xy[1])
    bundle_dir = resolve_case_mesh_bundle_dir(CASE_DIR, metadata, solver_name)
    if bundle_dir is None:
        return None
    from scipy.spatial import cKDTree

    n_cells = load_last_cell_values(
        observable_name=observable_name, store=result.store, sim_id=result.sim_id
    ).size
    centers, _ = bundle_cell_centers(bundle_dir, n_cells)
    _, nearest = cKDTree(np.asarray(centers, dtype=float)).query(points_xy)
    held = np.asarray(centers, dtype=float)[nearest]
    return np.hypot(held[:, 0] - center_xy[0], held[:, 1] - center_xy[1])


def _final_head_map(
    *,
    result,
    solver: str | None,
    metadata: dict,
    observable_name: str,
    final_heads: np.ndarray,
    final_day: float,
) -> tuple[list[list[tuple[float, float]]], np.ndarray, np.ndarray]:
    """Return the cell polygons, the simulated head and the reference head at the final time."""
    reference_cfg = dict(metadata.get("reference", {}))
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or solver
    bundle_dir = resolve_case_mesh_bundle_dir(CASE_DIR, metadata, solver_name)
    if bundle_dir is not None:
        simulated = load_last_cell_values(
            observable_name=observable_name, store=result.store, sim_id=result.sim_id
        )
        centers, _ = bundle_cell_centers(bundle_dir, simulated.size)
        polygons = load_cell_polygons(store=result.store, sim_id=result.sim_id)
    else:
        simulated = np.asarray(final_heads, dtype=float).reshape(-1)
        polygons = structured_cell_polygons(
            x_min=float(reference_cfg["xmin"]),
            x_max=float(reference_cfg["xmax"]),
            y_min=float(reference_cfg["ymin"]),
            y_max=float(reference_cfg["ymax"]),
            nrow=int(final_heads.shape[0]),
            ncol=int(final_heads.shape[1]),
        )
        centers = np.asarray([polygon.mean(axis=0) for polygon in polygons], dtype=float)
    center_x = float(reference_cfg["center_x_m"])
    center_y = float(reference_cfg["center_y_m"])
    radius = np.round(np.hypot(centers[:, 0] - center_x, centers[:, 1] - center_y), 3)
    off_well = radius > 0.0
    reference = np.full(radius.shape, np.nan, dtype=float)
    reference[off_well] = (
        float(reference_cfg["base_head_m"])
        - (
            expected_late_time_unconfined_pumping_drawdown(
                eval_times_days=[final_day],
                monitor_radii_m=radius[off_well],
                pumping_rate_m3_day=float(reference_cfg["pumping_rate_m3_day"]),
                hydraulic_conductivity_m_per_s=float(
                    reference_cfg["hydraulic_conductivity_m_per_s"]
                ),
                reference_saturated_thickness_m=float(
                    reference_cfg["reference_saturated_thickness_m"]
                ),
                specific_yield=float(reference_cfg["specific_yield"]),
            )[0]
        )
    )
    return (
        map_polygons_payload(polygons, origin_x=center_x, origin_y=center_y),
        simulated,
        reference,
    )


def build_late_time_unconfined_pumping_comparison(
    *,
    result,
    solver: str | None = None,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> LateTimeUnconfinedPumpingComparison:
    """Load one completed run and compare the late-time drawdown to the reference."""
    loaded = load_transient_profile_outputs(
        case_dir=CASE_DIR,
        result=result,
        metadata=metadata,
        tolerances=tolerances,
        solver=solver,
    )
    metadata = loaded.metadata
    tolerances = loaded.tolerances
    observable_name = loaded.observable_name
    period_indices_all = np.asarray(loaded.period_indices, dtype=int)
    heads_all = np.asarray(loaded.heads, dtype=float)
    dt_seconds = float(loaded.dt_seconds)
    reference_cfg = dict(metadata.get("reference", {}))
    plot_cfg = dict(metadata.get("plot", {}))

    elapsed_seconds_all = (
        np.asarray(loaded.elapsed_seconds, dtype=float)
        if loaded.elapsed_seconds is not None
        else (period_indices_all.astype(float) + 1.0) * float(dt_seconds)
    )
    elapsed_days_all = elapsed_seconds_all / SECONDS_PER_DAY
    compare_start_day = float(reference_cfg.get("compare_start_day", 0.0))
    compare_mask = elapsed_days_all >= compare_start_day
    if not np.any(compare_mask):
        raise ValueError(
            f"No time steps remain after compare_start_day={compare_start_day:.3f} day."
        )

    period_indices = np.asarray(period_indices_all[compare_mask], dtype=int)
    heads = np.asarray(heads_all[compare_mask], dtype=float)
    elapsed_seconds = np.asarray(elapsed_seconds_all[compare_mask], dtype=float)
    elapsed_days = np.asarray(elapsed_days_all[compare_mask], dtype=float)

    x_centers = build_uniform_axis_centers(
        minimum=float(reference_cfg["xmin"]),
        maximum=float(reference_cfg["xmax"]),
        count=heads.shape[-1],
    )
    y_centers = build_uniform_axis_centers(
        minimum=float(reference_cfg["ymin"]),
        maximum=float(reference_cfg["ymax"]),
        count=heads.shape[-2],
    )
    monitor_radii_m, azimuth_labels, sample_indices, sampled_heads = extract_radial_monitor_series(
        heads=heads,
        x_centers=x_centers,
        y_centers=y_centers,
        center_x=float(reference_cfg["center_x_m"]),
        center_y=float(reference_cfg["center_y_m"]),
        monitor_offsets_cells=plot_cfg.get("monitor_offsets_cells", (3, 5, 8, 12)),
    )

    base_head_m = float(reference_cfg["base_head_m"])
    numerical_drawdown_by_azimuth = base_head_m - sampled_heads
    numerical_drawdown_mean = numerical_drawdown_by_azimuth.mean(axis=2)
    center_xy = (float(reference_cfg["center_x_m"]), float(reference_cfg["center_y_m"]))
    points = sample_indices.reshape(-1, 2)
    held_radii = _sampled_cell_radii(
        result=result,
        solver=solver,
        metadata=metadata,
        observable_name=observable_name,
        points_xy=np.column_stack([x_centers[points[:, 1]], y_centers[points[:, 0]]]),
        center_xy=center_xy,
    )
    reference_kwargs = dict(
        pumping_rate_m3_day=float(reference_cfg["pumping_rate_m3_day"]),
        hydraulic_conductivity_m_per_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        reference_saturated_thickness_m=float(reference_cfg["reference_saturated_thickness_m"]),
        specific_yield=float(reference_cfg["specific_yield"]),
    )
    if held_radii is None:
        analytical_drawdown = expected_late_time_unconfined_pumping_drawdown(
            eval_times_days=elapsed_days, monitor_radii_m=monitor_radii_m, **reference_kwargs
        )
    else:
        # The mean over the four azimuths of the reference at each cell read,
        # the same mean the simulated drawdown takes.
        per_point = expected_late_time_unconfined_pumping_drawdown(
            eval_times_days=elapsed_days, monitor_radii_m=held_radii, **reference_kwargs
        )
        analytical_drawdown = per_point.reshape(elapsed_days.size, *sample_indices.shape[:2]).mean(
            axis=2
        )
    residual_drawdown = np.asarray(numerical_drawdown_mean - analytical_drawdown, dtype=float)
    map_cell_polygons, map_simulated, map_reference = _final_head_map(
        result=result,
        solver=solver,
        metadata=metadata,
        observable_name=observable_name,
        final_heads=heads[-1],
        final_day=float(elapsed_days[-1]),
    )

    return LateTimeUnconfinedPumpingComparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
        observable_name=observable_name,
        period_indices=period_indices,
        elapsed_seconds=elapsed_seconds,
        elapsed_days=elapsed_days,
        x_centers=x_centers,
        y_centers=y_centers,
        base_head_m=base_head_m,
        monitor_radii_m=monitor_radii_m,
        azimuth_labels=azimuth_labels,
        sample_indices=sample_indices,
        numerical_drawdown_mean=numerical_drawdown_mean,
        analytical_drawdown=analytical_drawdown,
        numerical_drawdown_by_azimuth=numerical_drawdown_by_azimuth,
        residual_drawdown=residual_drawdown,
        space_time_rmse=rmse(numerical_drawdown_mean, analytical_drawdown),
        space_time_max_error=max_abs_error(numerical_drawdown_mean, analytical_drawdown),
        final_time_rmse=rmse(numerical_drawdown_mean[-1], analytical_drawdown[-1]),
        final_time_max_error=max_abs_error(numerical_drawdown_mean[-1], analytical_drawdown[-1]),
        azimuthal_spread=float(np.max(np.std(numerical_drawdown_by_azimuth, axis=2))),
        map_cell_polygons=map_cell_polygons,
        map_simulated=map_simulated,
        map_reference=map_reference,
        map_overlay={"well": [0.0, 0.0]},
    )


def run_late_time_unconfined_pumping_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> LateTimeUnconfinedPumpingComparison:
    """Run the launcher case and return the full radial-drawdown comparison payload."""
    normalized_solver = None if solver is None else str(solver).strip().lower()
    preloaded_metadata = None
    preloaded_tolerances = None
    if normalized_solver in {"boussinesq", DEFAULT_ENGINE_SOLVER}:
        preloaded_metadata = load_case_metadata(CASE_DIR)
        preloaded_tolerances = load_case_tolerances(CASE_DIR, solver=solver)
        result = run_boussinesq_late_time_unconfined_pumping_case(
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
    return build_late_time_unconfined_pumping_comparison(
        result=result,
        solver=solver,
        metadata=preloaded_metadata,
        tolerances=preloaded_tolerances,
    )
