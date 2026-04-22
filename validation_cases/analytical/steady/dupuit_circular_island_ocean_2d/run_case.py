"""Run the steady circular-island ocean validation case and plot the comparison."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # Allow `python path/to/run_case.py` by exposing the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.comparison import (
    run_dupuit_circular_island_ocean_comparison,
)
from validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.plotting import (
    plot_dupuit_circular_island_ocean_comparison,
)
from validation_cases.shared.cli import run_case_main

DEFAULT_FIGURE_NAME = "dupuit_circular_island_ocean_2d_validation.png"
RUN_DESCRIPTION = "Run the circular-island ocean validation case and plot the result."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Radial head-profile RMSE: {comparison.rms_error:.4f} m",
        f"Radial head-profile max abs error: {comparison.max_error:.4f} m",
        f"Azimuthal spread: {comparison.azimuthal_spread:.4f} m",
        f"Ocean head max abs error: {comparison.ocean_head_max_error:.2e} m",
        f"Minimum land freeboard: {comparison.land_clearance_min:.4f} m",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_dupuit_circular_island_ocean_comparison,
        plot_comparison=plot_dupuit_circular_island_ocean_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
