"""Plotting helpers for the 1D linearized unconfined periodic-recharge case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.common import (
    TransientHead1DComparison,
    plot_transient_head_1d_comparison,
)


def plot_linearized_unconfined_recharge_periodic_comparison(
    comparison: TransientHead1DComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure comparing numerical and analytical periodic-recharge responses."""
    reference_cfg = dict(comparison.metadata.get("reference", {}))
    plot_cfg = dict(comparison.metadata.get("plot", {}))
    domain_length = float(reference_cfg["xmax"]) - float(reference_cfg["xmin"])
    parameter_lines = (
        f"L={domain_length:.0f} m   H0={float(reference_cfg['base_head_m']):.2f} m   "
        f"Rmean={float(reference_cfg['mean_recharge_mm_day']):.2f} mm/day   "
        f"Ramp={float(reference_cfg['amplitude_mm_day']):.2f} mm/day",
        f"K={float(reference_cfg['hydraulic_conductivity_m_per_s']):.1e} m/s   "
        f"Sy={float(reference_cfg['specific_yield']):.3f}   "
        f"Href={float(reference_cfg['reference_saturated_thickness_m']):.2f} m   "
        f"P={float(reference_cfg['period_days']):.1f} d   "
        f"t_end={comparison.final_elapsed_days:.1f} d",
    )
    return plot_transient_head_1d_comparison(
        comparison,
        output_png=output_png,
        title="Linearized Unconfined 1D Validation - Periodic Recharge",
        parameter_lines=parameter_lines,
        profile_times_days=plot_cfg.get("profile_times_days", (30.0, 32.0, 35.0, 38.0, 40.0)),
        show_plot=show_plot,
        dpi=dpi,
    )
