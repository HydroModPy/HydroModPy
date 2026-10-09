"""Plotting for the deep-aquifer Brutsaert recession validation case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.brutsaert_common import (
    plot_brutsaert_recession_comparison,
)


def plot_brutsaert_recession_linearized_deep_comparison(
    comparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save and optionally display the deep Brutsaert recession comparison figure."""
    return plot_brutsaert_recession_comparison(
        comparison,
        output_png=output_png,
        title="Brutsaert Recession Validation: Deep Linearized Aquifer",
        show_plot=show_plot,
        dpi=dpi,
    )


__all__ = ["plot_brutsaert_recession_linearized_deep_comparison"]
