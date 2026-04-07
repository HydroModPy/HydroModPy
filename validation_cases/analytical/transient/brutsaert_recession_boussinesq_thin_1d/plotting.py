"""Plotting for the thin-aquifer Brutsaert recession validation case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.brutsaert_common import (
    plot_brutsaert_recession_comparison,
)

from .reference import build_parameter_lines


def plot_brutsaert_recession_boussinesq_thin_comparison(
    comparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save and optionally display the thin Brutsaert recession comparison figure."""
    return plot_brutsaert_recession_comparison(
        comparison,
        output_png=output_png,
        title="Brutsaert Recession Validation: Thin Nonlinear Aquifer",
        parameter_lines=build_parameter_lines(comparison.metadata),
        show_plot=show_plot,
        dpi=dpi,
    )


__all__ = ["plot_brutsaert_recession_boussinesq_thin_comparison"]
