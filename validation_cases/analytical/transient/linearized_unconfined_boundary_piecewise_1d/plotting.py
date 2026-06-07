"""Plotting helpers for the 1D linearized unconfined boundary-piecewise case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.common import (
    TransientHead1DComparison,
    plot_transient_head_1d_comparison,
)


def plot_linearized_unconfined_boundary_piecewise_comparison(
    comparison: TransientHead1DComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure comparing numerical and analytical boundary-piecewise responses."""
    reference_cfg = dict(comparison.metadata.get("reference", {}))
    plot_cfg = dict(comparison.metadata.get("plot", {}))
    west_levels = [float(value) for value in reference_cfg["west_head_levels_m"]]
    parameter_lines = (
        f"L={float(reference_cfg['xmax']) - float(reference_cfg['xmin']):.0f} m   "
        f"H0={float(reference_cfg['base_head_m']):.2f} m   "
        f"h_w range=[{min(west_levels):.2f}, {max(west_levels):.2f}] m",
        f"K={float(reference_cfg['hydraulic_conductivity_m_per_s']):.1e} m/s   "
        f"Sy={float(reference_cfg['specific_yield']):.3f}   "
        f"Href={float(reference_cfg['reference_saturated_thickness_m']):.2f} m   "
        f"t_end={comparison.final_elapsed_days:.1f} d",
    )
    return plot_transient_head_1d_comparison(
        comparison,
        output_png=output_png,
        title="Linearized Unconfined 1D Validation - Boundary Piecewise",
        parameter_lines=parameter_lines,
        profile_times_days=plot_cfg.get("profile_times_days", (1.0, 3.0, 5.0, 7.0, 9.0, 12.0)),
        show_plot=show_plot,
        dpi=dpi,
    )
