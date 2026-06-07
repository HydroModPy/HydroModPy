"""Run the steady Dupuit uniform-recharge validation case and plot the comparison."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # Allow `python path/to/run_case.py` by exposing the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.steady.dupuit_uniform_recharge_1d.comparison import (
    run_dupuit_uniform_recharge_comparison,
)
from validation_cases.analytical.steady.dupuit_uniform_recharge_1d.plotting import (
    plot_dupuit_uniform_recharge_comparison,
)
from validation_cases.shared.cli import run_case_main

DEFAULT_FIGURE_NAME = "dupuit_uniform_recharge_1d_validation.png"
RUN_DESCRIPTION = "Run the Dupuit uniform-recharge validation case and plot the result."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Head-profile RMSE: {comparison.rms_error:.4f} m",
        f"Head-profile max abs error: {comparison.max_error:.4f} m",
        f"Cross-row head spread: {comparison.row_spread:.2e} m",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_dupuit_uniform_recharge_comparison,
        plot_comparison=plot_dupuit_uniform_recharge_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
