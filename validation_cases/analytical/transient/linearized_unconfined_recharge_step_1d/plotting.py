"""Plotting helpers for the 1D linearized unconfined recharge-step case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.common import (
    TransientHead1DComparison,
    plot_transient_head_1d_comparison,
)


def plot_linearized_unconfined_recharge_step_comparison(
    comparison: TransientHead1DComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure comparing numerical and analytical recharge-step responses."""
    reference_cfg = dict(comparison.metadata.get("reference", {}))
    plot_cfg = dict(comparison.metadata.get("plot", {}))
    domain_length = float(reference_cfg["xmax"]) - float(reference_cfg["xmin"])
    parameter_lines = (
        f"L={domain_length:.0f} m   H0={float(reference_cfg['base_head_m']):.2f} m   "
        f"R={float(reference_cfg['recharge_mm_day']):.2f} mm/day",
        f"K={float(reference_cfg['hydraulic_conductivity_m_per_s']):.1e} m/s   "
        f"Sy={float(reference_cfg['specific_yield']):.3f}   "
        f"Href={float(reference_cfg['reference_saturated_thickness_m']):.2f} m   "
        f"t_end={comparison.final_elapsed_days:.1f} d",
    )
    return plot_transient_head_1d_comparison(
        comparison,
        output_png=output_png,
        title="Linearized Unconfined 1D Validation - Recharge Step",
        parameter_lines=parameter_lines,
        profile_times_days=plot_cfg.get("profile_times_days", (0.5, 2.0, 7.0, 20.0, 30.0)),
        show_plot=show_plot,
        dpi=dpi,
    )
