"""Plotting helpers for the 1D linearized unconfined boundary-periodic case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.common import (
    TransientHead1DComparison,
    plot_transient_head_1d_comparison,
)


def plot_linearized_unconfined_boundary_periodic_comparison(
    comparison: TransientHead1DComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure comparing the simulated tide with the Ferris solution."""
    reference_cfg = dict(comparison.metadata.get("reference", {}))
    plot_cfg = dict(comparison.metadata.get("plot", {}))
    parameter_lines = (
        f"L={float(reference_cfg['xmax']) - float(reference_cfg['xmin']):.0f} m   "
        f"h0={float(reference_cfg['base_head_m']):.2f} m   "
        f"A={float(reference_cfg['tide_amplitude_m']):.2f} m   "
        f"t0={float(reference_cfg['tide_period_hours']):.0f} h",
        f"K={float(reference_cfg['hydraulic_conductivity_m_per_s']):.1e} m/s   "
        f"Sy={float(reference_cfg['specific_yield']):.3f}   "
        f"Href={float(reference_cfg['reference_saturated_thickness_m']):.2f} m   "
        f"lambda={getattr(comparison, 'damping_length_m', float('nan')):.2f} m",
    )
    return plot_transient_head_1d_comparison(
        comparison,
        output_png=output_png,
        title="Linearized Unconfined 1D Validation - Tidal Boundary (Ferris 1951)",
        parameter_lines=parameter_lines,
        profile_times_days=plot_cfg.get("profile_times_days", (7.0, 7.25, 7.5, 7.75, 8.0)),
        show_plot=show_plot,
        dpi=dpi,
    )
