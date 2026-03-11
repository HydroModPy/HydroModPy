"""Plotting helpers for the late-time unconfined pumping 2D case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.common import (
    TransientRadialDrawdownComparison,
    plot_transient_radial_drawdown_comparison,
)


def plot_late_time_unconfined_pumping_comparison(
    comparison: TransientRadialDrawdownComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure comparing numerical and late-time analytical drawdowns."""
    reference_cfg = dict(comparison.metadata.get("reference", {}))
    domain_length_x = float(reference_cfg["xmax"]) - float(reference_cfg["xmin"])
    domain_length_y = float(reference_cfg["ymax"]) - float(reference_cfg["ymin"])
    parameter_lines = (
        f"Lx={domain_length_x:.0f} m   Ly={domain_length_y:.0f} m   "
        f"H0={float(reference_cfg['base_head_m']):.2f} m   "
        f"Q={float(reference_cfg['pumping_rate_m3_day']):.1f} m3/day",
        f"K={float(reference_cfg['hydraulic_conductivity_m_per_s']):.1e} m/s   "
        f"Sy={float(reference_cfg['specific_yield']):.3f}   "
        f"Href={float(reference_cfg['reference_saturated_thickness_m']):.2f} m   "
        f"compare from t={float(reference_cfg['compare_start_day']):.1f} d",
    )
    return plot_transient_radial_drawdown_comparison(
        comparison,
        output_png=output_png,
        title="Late-Time Unconfined Pumping 2D Validation",
        parameter_lines=parameter_lines,
        show_plot=show_plot,
        dpi=dpi,
    )
