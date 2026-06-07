"""Run the transient hillslope recharge-step interception case and plot it."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.transient.boussinesq_hillslope_recharge_step_interception_1d.comparison import (
    run_boussinesq_hillslope_recharge_step_interception_comparison,
)
from validation_cases.analytical.transient.boussinesq_hillslope_recharge_step_interception_1d.plotting import (
    plot_boussinesq_hillslope_recharge_step_interception_comparison,
)
from validation_cases.shared.cli import run_case_main

DEFAULT_FIGURE_NAME = "boussinesq_hillslope_recharge_step_interception_1d_validation.png"
RUN_DESCRIPTION = "Run the transient hillslope recharge-step interception validation case."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Analytical onset time: {comparison.analytical_onset_time_days:.1f} d",
        f"Numerical onset time: {comparison.numerical_onset_time_days:.1f} d",
        f"Onset-time error: {comparison.onset_time_error_days:.1f} d",
        f"Interception-trajectory RMSE: {comparison.trajectory_rmse_m:.2f} m",
        f"Interception-trajectory max abs error: {comparison.trajectory_max_error_m:.2f} m",
        f"Trajectory reversal: {comparison.trajectory_reversal_m:.2e} m",
        f"Cross-row head spread: {comparison.row_spread:.2e} m",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_boussinesq_hillslope_recharge_step_interception_comparison,
        plot_comparison=plot_boussinesq_hillslope_recharge_step_interception_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
