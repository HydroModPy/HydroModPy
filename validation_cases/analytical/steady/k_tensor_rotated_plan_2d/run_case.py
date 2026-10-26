"""Run the plan-view K tensor case and plot the comparison."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.steady.k_tensor_rotated_plan_2d.comparison import (
    run_rotated_plan_comparison,
)
from validation_cases.analytical.steady.k_tensor_rotated_plan_2d.plotting import (
    plot_rotated_plan_comparison,
)
from validation_cases.shared.cli import run_case_main


def _metric_lines(comparison) -> tuple[str, ...]:
    fit = comparison.fit
    return (
        f"ANGLE1: {comparison.angle1_deg:+.1f} deg",
        f"dh/dy over dh/dx: {fit.gradient_ratio_numerical:.10f} "
        f"(exact {comparison.tensor.gradient_ratio:.10f})",
        f"Gradient direction relative error: {fit.gradient_ratio_error:.3e}",
        f"Head max abs error: {fit.head_max_error:.3e} m",
        f"End flow relative error: {fit.flow_error:.3e}",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description="Run the plan-view K tensor case and plot the result.",
        default_figure_name="k_tensor_rotated_plan_2d_validation.png",
        caller_file=__file__,
        run_comparison=run_rotated_plan_comparison,
        plot_comparison=plot_rotated_plan_comparison,
        build_metric_lines=_metric_lines,
    )


if __name__ == "__main__":
    main()
