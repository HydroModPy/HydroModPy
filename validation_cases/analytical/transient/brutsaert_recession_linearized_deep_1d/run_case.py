"""Run the deep-aquifer Brutsaert recession validation case and plot it."""

from __future__ import annotations

from pathlib import Path
import sys


if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.transient.brutsaert_recession_linearized_deep_1d.comparison import (
    run_brutsaert_recession_linearized_deep_comparison,
)
from validation_cases.analytical.transient.brutsaert_recession_linearized_deep_1d.plotting import (
    plot_brutsaert_recession_linearized_deep_comparison,
)
from validation_cases.shared.cli import run_case_main


DEFAULT_FIGURE_NAME = "brutsaert_recession_linearized_deep_1d_validation.png"
RUN_DESCRIPTION = "Run the deep-aquifer Brutsaert recession validation case."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Solution: {comparison.solution_name}",
        f"Initial discharge: {comparison.initial_discharge_m3_s:.6e} m3/s",
        f"Characteristic time: {comparison.characteristic_time_days:.2f} d",
        f"Relative RMSE: {comparison.relative_rmse:.4f}",
        f"Relative max abs error: {comparison.relative_max_error:.4f}",
        f"Cross-row head spread: {comparison.row_spread:.2e} m",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_brutsaert_recession_linearized_deep_comparison,
        plot_comparison=plot_brutsaert_recession_linearized_deep_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
