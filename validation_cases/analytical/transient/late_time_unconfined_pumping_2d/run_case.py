"""Run the late-time unconfined pumping 2D validation case and plot it."""

from __future__ import annotations

from pathlib import Path
import sys


if __package__ is None or __package__ == "":
    # Allow `python path/to/run_case.py` by exposing the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.transient.late_time_unconfined_pumping_2d.comparison import (
    run_late_time_unconfined_pumping_comparison,
)
from validation_cases.analytical.transient.late_time_unconfined_pumping_2d.plotting import (
    plot_late_time_unconfined_pumping_comparison,
)
from validation_cases.shared.cli import run_case_main


DEFAULT_FIGURE_NAME = "late_time_unconfined_pumping_2d_validation.png"
RUN_DESCRIPTION = "Run the late-time unconfined pumping 2D validation case."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Space-time RMSE: {comparison.space_time_rmse:.4f} m",
        f"Space-time max abs error: {comparison.space_time_max_error:.4f} m",
        f"Final-time RMSE: {comparison.final_time_rmse:.4f} m",
        f"Azimuthal spread: {comparison.azimuthal_spread:.2e} m",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_late_time_unconfined_pumping_comparison,
        plot_comparison=plot_late_time_unconfined_pumping_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
