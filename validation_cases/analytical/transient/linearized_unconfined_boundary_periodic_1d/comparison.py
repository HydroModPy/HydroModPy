"""Comparison workflow for the 1D linearized unconfined boundary-periodic case (Ferris tide)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from validation_cases.analytical.transient.common import (
    TransientHead1DComparison,
    TransientProfileOutputs,
    build_transient_head_comparison,
    load_transient_profile_outputs,
)
from validation_cases.shared import (
    load_case_metadata,
    load_case_tolerances,
    load_time_series_fields,
    run_launcher_validation_case,
)
from validation_cases.shared.boussinesq_analytical_runtime import DEFAULT_ENGINE_SOLVER
from validation_cases.shared.loaders import (
    bundle_cell_centers,
    load_cell_polygons,
    resolve_case_mesh_bundle_dir,
)
from validation_cases.shared.strip_geometry import (
    StripGeometry,
    column_centres,
    strip_geometry_for_run,
)

from .reference import damping_length_m, ferris_tidal_profiles, fit_tidal_harmonic
from .runtime_boussinesq import run_boussinesq_linearized_unconfined_boundary_periodic_case

CASE_DIR = Path(__file__).resolve().parent
VORONOI_SOLVER = "modflow6_voronoi"
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True, slots=True)
class TidalPropagationComparison(TransientHead1DComparison):
    """Head profiles over the compared tides, with the tidal harmonic of each column.

    The profile matrices keep the outputs from ``compare_start_day`` on, once
    the start-up transient has died. Over those whole tides, a least-squares
    fit gives the amplitude and the phase of the tide in each column:

    - ``amplitude_ratio_simulated`` / ``amplitude_ratio_reference``: the
      amplitude of each column over the tide amplitude ``A``.
    - ``phase_lag_simulated_hours`` / ``phase_lag_reference_hours``: the lag
      of each column behind the sea tide ``cos(2 pi t / t0)``, in hours.
    - ``harmonic_columns``: the columns read for both errors. They sit at
      least one column width from the sea, where the reference keeps at least
      ``harmonic_min_ratio`` of the tide amplitude. The sea column is left
      out: it holds the mean tide of each period, not a computed head.

    A straight line through the harmonic columns gives the two lengths of
    the Ferris method: ``ln(amplitude)`` falls by one over the decay length,
    and the phase lag grows by one radian over the lag length. Both equal
    ``sqrt(t0 T / (pi S))``. The intercepts take up what the sea column
    imposes, so the slopes measure the propagation alone.
    """

    damping_length_m: float
    sea_x: float
    amplitude_ratio_simulated: np.ndarray
    amplitude_ratio_reference: np.ndarray
    phase_lag_simulated_hours: np.ndarray
    phase_lag_reference_hours: np.ndarray
    harmonic_columns: np.ndarray
    decay_length_simulated_m: float
    decay_length_reference_m: float
    lag_length_simulated_m: float
    lag_length_reference_m: float
    decay_length_relative_error: float
    lag_length_relative_error: float


def _voronoi_strip_outputs(
    *,
    result,
    metadata: dict,
    tolerances: dict,
    observable_name: str,
    bundle_dir: Path,
) -> tuple[TransientProfileOutputs, StripGeometry]:
    """Load a Voronoi-dual strip run as area-weighted column profiles.

    A Voronoi dual has one cell per bundle node, centred on the node, and a
    side head sits on the nodes of the face. The cells are binned by node
    abscissa into the columns of the structured grid, weighted by area.
    """
    reference_cfg = dict(metadata.get("reference", {}))
    output_cfg = dict(metadata.get("output", {}))
    nrow, ncol = (int(value) for value in output_cfg["expected_spatial_shape"])
    xmin = float(reference_cfg["xmin"])
    xmax = float(reference_cfg["xmax"])

    period_indices, history = load_time_series_fields(
        store=result.store, sim_id=result.sim_id, observable_name=observable_name
    )
    history = np.asarray(history, dtype=float).reshape(np.asarray(history).shape[0], -1)
    centers, kind = bundle_cell_centers(bundle_dir, history.shape[1])
    if kind != "voronoi":
        raise ValueError(f"Expected a Voronoi dual of {bundle_dir}, got {kind} cells.")
    polygons = load_cell_polygons(store=result.store, sim_id=result.sim_id)
    area = np.asarray(
        [
            0.5 * abs(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1)))
            for p in polygons
        ],
        dtype=float,
    )
    node_x = centers[:, 0]
    atol = 1.0e-9 * max(xmax - xmin, 1.0)
    west_x = float(np.mean(node_x[np.isclose(node_x, xmin, rtol=0.0, atol=atol)]))
    east_x = float(np.mean(node_x[np.isclose(node_x, xmax, rtol=0.0, atol=atol)]))
    dx = (xmax - xmin) / ncol
    column = np.clip(((node_x - xmin) / dx).astype(int), 0, ncol - 1)
    geometry = StripGeometry(
        xmin=xmin,
        xmax=xmax,
        x=column_centres(xmin=xmin, xmax=xmax, ncol=ncol),
        west_x=west_x,
        east_x=east_x,
        surface_west_x=xmin,
        surface_east_x=xmax,
        mean_cell_area=float(np.mean(area)),
        cell_x=node_x,
        cell_column=column,
        cell_weight=area,
    )
    profiles = geometry.profile(lambda _points: history)
    heads = np.repeat(profiles[:, None, :], nrow, axis=1)
    dt_seconds = float(metadata["time"]["dt_seconds"])
    indices = np.asarray(period_indices, dtype=float)
    expected_periods = int(output_cfg.get("expected_periods", 0))
    if expected_periods > 0 and heads.shape[0] != expected_periods:
        raise AssertionError(
            f"Unexpected number of periods for {observable_name}: "
            f"{heads.shape[0]} != {expected_periods}"
        )
    loaded = TransientProfileOutputs(
        metadata=metadata,
        tolerances=tolerances,
        observable_name=observable_name,
        period_indices=indices,
        heads=heads,
        dt_seconds=dt_seconds,
        elapsed_seconds=(indices + 1.0) * dt_seconds,
    )
    return loaded, geometry


def _compared_tides(loaded: TransientProfileOutputs, compare_start_seconds: float):
    """Keep the outputs from ``compare_start_seconds`` on."""
    keep = np.asarray(loaded.elapsed_seconds, dtype=float) > float(compare_start_seconds) + 1.0e-6
    if not np.any(keep):
        raise ValueError("No output remains after the compare start.")
    return replace(
        loaded,
        period_indices=np.asarray(loaded.period_indices)[keep],
        heads=np.asarray(loaded.heads)[keep],
        elapsed_seconds=np.asarray(loaded.elapsed_seconds)[keep],
    )


def build_linearized_unconfined_boundary_periodic_comparison(
    *,
    result,
    solver: str | None = None,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> TidalPropagationComparison:
    """Load one completed run and compare its tides with the Ferris solution."""
    metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    tolerances = load_case_tolerances(CASE_DIR, solver=solver) if tolerances is None else tolerances
    reference_cfg = dict(metadata.get("reference", {}))
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or str(solver or "")
    observable_name = str(metadata.get("output", {}).get("observable_name", "watertable_elevation"))

    if solver_name == VORONOI_SOLVER:
        bundle_dir = resolve_case_mesh_bundle_dir(CASE_DIR, metadata, solver_name)
        loaded, geometry = _voronoi_strip_outputs(
            result=result,
            metadata=metadata,
            tolerances=tolerances,
            observable_name=observable_name,
            bundle_dir=bundle_dir,
        )
    else:
        loaded = load_transient_profile_outputs(
            case_dir=CASE_DIR,
            result=result,
            metadata=metadata,
            tolerances=tolerances,
            solver=solver,
        )
        geometry = strip_geometry_for_run(
            result,
            ncol=loaded.heads.shape[-1],
            xmin=float(reference_cfg["xmin"]),
            xmax=float(reference_cfg["xmax"]),
            area_weighted=True,
        )

    tide_period_seconds = float(reference_cfg["tide_period_hours"]) * SECONDS_PER_HOUR
    loaded = _compared_tides(loaded, float(reference_cfg["compare_start_day"]) * SECONDS_PER_DAY)
    lam = damping_length_m(
        hydraulic_conductivity_m_per_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        reference_saturated_thickness_m=float(reference_cfg["reference_saturated_thickness_m"]),
        specific_yield=float(reference_cfg["specific_yield"]),
        tide_period_seconds=tide_period_seconds,
    )
    eval_times = np.asarray(loaded.elapsed_seconds, dtype=float)
    analytical_profiles = geometry.profile(
        lambda points: ferris_tidal_profiles(
            x=points - geometry.west_x,
            eval_times_seconds=eval_times,
            mean_sea_level_m=float(reference_cfg["base_head_m"]),
            tide_amplitude_m=float(reference_cfg["tide_amplitude_m"]),
            tide_period_seconds=tide_period_seconds,
            damping_length=lam,
        ),
        within=(geometry.west_x, geometry.east_x),
    )
    comparison = build_transient_head_comparison(
        result=result,
        case_dir=CASE_DIR,
        analytical_profiles=analytical_profiles,
        loaded_outputs=loaded,
    )

    amp_sim, phase_sim = fit_tidal_harmonic(
        times_seconds=eval_times,
        values=comparison.numerical_profiles,
        tide_period_seconds=tide_period_seconds,
    )
    amp_ref, phase_ref = fit_tidal_harmonic(
        times_seconds=eval_times,
        values=comparison.analytical_profiles,
        tide_period_seconds=tide_period_seconds,
    )
    hours_per_radian = tide_period_seconds / (2.0 * np.pi) / SECONDS_PER_HOUR
    tide_amplitude_m = float(reference_cfg["tide_amplitude_m"])
    ratio_sim = amp_sim / tide_amplitude_m
    ratio_ref = amp_ref / tide_amplitude_m
    lag_sim = np.unwrap(phase_sim) * hours_per_radian
    lag_ref = np.unwrap(phase_ref) * hours_per_radian
    column_width = float(geometry.x[1] - geometry.x[0])
    columns = np.flatnonzero(
        (ratio_ref >= float(reference_cfg["harmonic_min_ratio"]))
        & (geometry.x - geometry.west_x >= column_width - 1.0e-9)
    )

    distance = geometry.x[columns] - geometry.west_x
    decay_sim = _length_from_slope(distance, -np.log(ratio_sim[columns]))
    decay_ref = _length_from_slope(distance, -np.log(ratio_ref[columns]))
    lag_sim_m = _length_from_slope(distance, lag_sim[columns] / hours_per_radian)
    lag_ref_m = _length_from_slope(distance, lag_ref[columns] / hours_per_radian)

    base = {name: getattr(comparison, name) for name in TransientHead1DComparison.__slots__}
    base["x"] = geometry.x
    return TidalPropagationComparison(
        **base,
        damping_length_m=lam,
        sea_x=float(geometry.west_x),
        amplitude_ratio_simulated=ratio_sim,
        amplitude_ratio_reference=ratio_ref,
        phase_lag_simulated_hours=lag_sim,
        phase_lag_reference_hours=lag_ref,
        harmonic_columns=columns,
        decay_length_simulated_m=decay_sim,
        decay_length_reference_m=decay_ref,
        lag_length_simulated_m=lag_sim_m,
        lag_length_reference_m=lag_ref_m,
        decay_length_relative_error=abs(decay_sim / decay_ref - 1.0),
        lag_length_relative_error=abs(lag_sim_m / lag_ref_m - 1.0),
    )


def _length_from_slope(distance: np.ndarray, growth: np.ndarray) -> float:
    """Return the inverse slope of a least-squares line through ``(distance, growth)``."""
    slope = np.polyfit(np.asarray(distance, dtype=float), np.asarray(growth, dtype=float), 1)[0]
    return float(1.0 / slope)


def run_linearized_unconfined_boundary_periodic_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> TidalPropagationComparison:
    """Run the launcher case and return the tidal comparison payload."""
    normalized_solver = None if solver is None else str(solver).strip().lower()
    if normalized_solver in {"boussinesq", DEFAULT_ENGINE_SOLVER}:
        result = run_boussinesq_linearized_unconfined_boundary_periodic_case(
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
    return build_linearized_unconfined_boundary_periodic_comparison(result=result, solver=solver)
