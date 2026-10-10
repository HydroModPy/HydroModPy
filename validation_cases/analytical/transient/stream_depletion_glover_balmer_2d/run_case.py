"""Run the stream depletion 2D validation case and plot it."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # Allow `python path/to/run_case.py` by exposing the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.transient.stream_depletion_glover_balmer_2d.comparison import (
    run_stream_depletion_comparison,
)
from validation_cases.analytical.transient.stream_depletion_glover_balmer_2d.plotting import (
    plot_stream_depletion_comparison,
)
from validation_cases.shared.cli import run_case_main

DEFAULT_FIGURE_NAME = "stream_depletion_glover_balmer_2d_validation.png"
RUN_DESCRIPTION = "Run the stream depletion 2D validation case."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Stream depletion max abs error: {comparison.depletion_max_error:.5f}",
        f"Stream depletion final error: {comparison.depletion_final_error:.5f}",
        f"Drawdown space-time RMSE: {comparison.space_time_rmse:.5f} m",
        f"Drawdown space-time max abs error: {comparison.space_time_max_error:.5f} m",
        f"Drawdown final RMSE: {comparison.final_time_rmse:.5f} m",
        f"Well drawdown over saturated thickness: {comparison.well_drawdown_fraction:.4f}",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_stream_depletion_comparison,
        plot_comparison=plot_stream_depletion_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
