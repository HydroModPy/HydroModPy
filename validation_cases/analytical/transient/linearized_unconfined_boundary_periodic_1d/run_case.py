"""Run the 1D linearized unconfined boundary-periodic case and plot the comparison."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.transient.linearized_unconfined_boundary_periodic_1d.comparison import (
    run_linearized_unconfined_boundary_periodic_comparison,
)
from validation_cases.analytical.transient.linearized_unconfined_boundary_periodic_1d.plotting import (
    plot_linearized_unconfined_boundary_periodic_comparison,
)
from validation_cases.shared.cli import run_case_main

DEFAULT_FIGURE_NAME = "linearized_unconfined_boundary_periodic_1d_validation.png"
RUN_DESCRIPTION = "Run the linearized unconfined boundary-periodic (tide) validation case."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Space-time RMSE: {comparison.space_time_rmse:.4f} m",
        f"Space-time max abs error: {comparison.space_time_max_error:.4f} m",
        f"Amplitude ratio max error: {comparison.amplitude_ratio_max_error:.4f}",
        f"Phase lag max error: {comparison.phase_lag_max_error_minutes:.1f} min",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_linearized_unconfined_boundary_periodic_comparison,
        plot_comparison=plot_linearized_unconfined_boundary_periodic_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
