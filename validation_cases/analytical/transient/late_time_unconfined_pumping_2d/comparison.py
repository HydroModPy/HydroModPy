"""Comparison workflow for the late-time unconfined pumping 2D validation case."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from validation_cases.analytical.transient.common import (
    SECONDS_PER_DAY,
    TransientRadialDrawdownComparison,
    build_uniform_axis_centers,
    extract_radial_monitor_series,
    load_transient_profile_outputs,
)
from validation_cases.shared import max_abs_error, rmse, run_launcher_validation_case

from .reference import expected_late_time_unconfined_pumping_drawdown


CASE_DIR = Path(__file__).resolve().parent


def build_late_time_unconfined_pumping_comparison(
    *,
    result,
) -> TransientRadialDrawdownComparison:
    """Load one completed run and compare the late-time drawdown to the reference."""
    loaded = load_transient_profile_outputs(case_dir=CASE_DIR, result=result)
    metadata, tolerances, observable_name, period_indices_all, heads_all, dt_seconds = loaded
    reference_cfg = dict(metadata.get("reference", {}))
    plot_cfg = dict(metadata.get("plot", {}))

    elapsed_seconds_all = (period_indices_all.astype(float) + 1.0) * float(dt_seconds)
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
    analytical_drawdown = expected_late_time_unconfined_pumping_drawdown(
        eval_times_days=elapsed_days,
        monitor_radii_m=monitor_radii_m,
        pumping_rate_m3_day=float(reference_cfg["pumping_rate_m3_day"]),
        hydraulic_conductivity_m_per_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        reference_saturated_thickness_m=float(reference_cfg["reference_saturated_thickness_m"]),
        specific_yield=float(reference_cfg["specific_yield"]),
    )
    residual_drawdown = np.asarray(numerical_drawdown_mean - analytical_drawdown, dtype=float)

    return TransientRadialDrawdownComparison(
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
    )


def run_late_time_unconfined_pumping_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> TransientRadialDrawdownComparison:
    """Run the launcher case and return the full radial-drawdown comparison payload."""
    result = run_launcher_validation_case(
        case_dir=CASE_DIR,
        test_file=caller_file,
        timeout=timeout,
    )
    return build_late_time_unconfined_pumping_comparison(result=result)
