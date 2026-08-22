"""Run the steady Dupuit seepage-limit validation case and plot the comparison."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # Allow `python path/to/run_case.py` by exposing the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.steady.dupuit_seepage_limit_1d.comparison import (
    run_seepage_limit_comparison,
)
from validation_cases.analytical.steady.dupuit_seepage_limit_1d.plotting import (
    plot_seepage_limit_comparison,
)
from validation_cases.shared.cli import run_case_main

DEFAULT_FIGURE_NAME = "dupuit_seepage_limit_1d_validation.png"
RUN_DESCRIPTION = "Run the Dupuit seepage-limit validation case and plot the result."


def _build_metric_lines(comparison) -> tuple[str, ...]:
    return (
        f"Closed-form seepage limit: {comparison.analytical_seepage_limit_m:.3f} m",
        f"Mask seepage limit: {comparison.numerical_seepage_limit_m:.3f} m",
        f"Seepage-limit error: {comparison.seepage_limit_error_m:.3f} m",
        f"Head-profile max abs error: {comparison.head_profile_max_error_m:.5f} m",
        f"Seeping cells: {int(comparison.seepage_mask.sum())}",
        f"Total drain outflow: {comparison.drain_outflow_m3_per_s:.6e} m3/s",
    )


def main(argv: list[str] | None = None) -> None:
    run_case_main(
        argv=argv,
        description=RUN_DESCRIPTION,
        default_figure_name=DEFAULT_FIGURE_NAME,
        caller_file=__file__,
        run_comparison=run_seepage_limit_comparison,
        plot_comparison=plot_seepage_limit_comparison,
        build_metric_lines=_build_metric_lines,
    )


if __name__ == "__main__":
    main()
