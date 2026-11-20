"""Run the 2D recharge mound validation case and plot it."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.transient.hantush_recharge_mound_2d.comparison import (
    run_hantush_recharge_mound_comparison,
)
from validation_cases.analytical.transient.hantush_recharge_mound_2d.plotting import (
    plot_hantush_recharge_mound_comparison,
)
from validation_cases.shared.cli import run_case_main

DEFAULT_FIGURE_NAME = "hantush_recharge_mound_2d_validation.png"
RUN_DESCRIPTION = "Run the Hantush recharge mound 2D validation case."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Transect space-time RMSE: {comparison.space_time_rmse:.4f} m",
        f"Transect space-time max abs error: {comparison.space_time_max_error:.4f} m",
        f"Centre rise max abs error: {comparison.centre_max_error:.4f} m",
        f"Final map max abs error: {comparison.map_max_error:.4f} m",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_hantush_recharge_mound_comparison,
        plot_comparison=plot_hantush_recharge_mound_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
