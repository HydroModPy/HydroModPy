"""Run the deep-aquifer 1D linearized unconfined recharge-step validation case."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.transient.linearized_unconfined_recharge_step_deep_1d.comparison import (
    run_linearized_unconfined_recharge_step_deep_comparison,
)
from validation_cases.analytical.transient.linearized_unconfined_recharge_step_deep_1d.plotting import (
    plot_linearized_unconfined_recharge_step_deep_comparison,
)
from validation_cases.shared.cli import run_case_main

DEFAULT_FIGURE_NAME = "linearized_unconfined_recharge_step_deep_1d_validation.png"
RUN_DESCRIPTION = "Run the deep-aquifer 1D linearized unconfined recharge-step validation case."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Space-time RMSE: {comparison.space_time_rmse:.4f} m",
        f"Space-time max abs error: {comparison.space_time_max_error:.4f} m",
        f"Final-profile RMSE: {comparison.final_profile_rmse:.4f} m",
        f"Cross-row head spread: {comparison.row_spread:.2e} m",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_linearized_unconfined_recharge_step_deep_comparison,
        plot_comparison=plot_linearized_unconfined_recharge_step_deep_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
