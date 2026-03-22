"""Run the steady Boussinesq hillslope-interception case and plot the comparison."""

from __future__ import annotations

from pathlib import Path
import sys


if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.comparison import (
    run_boussinesq_hillslope_interception_comparison,
)
from validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.plotting import (
    plot_boussinesq_hillslope_interception_comparison,
)
from validation_cases.shared.cli import run_case_main


DEFAULT_FIGURE_NAME = "boussinesq_hillslope_interception_1d_validation.png"
RUN_DESCRIPTION = "Run the hillslope-interception validation case and plot the result."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Analytical interception x: {comparison.analytical_interception_x_m:.3f} m",
        f"Numerical interception x: {comparison.numerical_interception_x_m:.3f} m",
        f"Interception x error: {comparison.interception_x_error_m:.3f} m",
        f"Diagnostic dry-zone RMSE: {comparison.dry_zone_rmse:.4f} m",
        f"Diagnostic dry-zone max abs error: {comparison.dry_zone_max_error:.4f} m",
        f"Cross-row head spread: {comparison.row_spread:.2e} m",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_boussinesq_hillslope_interception_comparison,
        plot_comparison=plot_boussinesq_hillslope_interception_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
