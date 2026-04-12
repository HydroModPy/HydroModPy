"""Run the steady Dupuit twin benchmark outside pytest."""

from __future__ import annotations

import argparse
from pathlib import Path

from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_TWIN_CASE,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the steady Dupuit calibration twin benchmark.",
    )
    parser.add_argument(
        "--method",
        action="append",
        default=None,
        help="Optional method name filter. Repeat to select multiple methods.",
    )
    args = parser.parse_args(argv)
    benchmark = run_twin_benchmark_case(
        STEADY_DUPUIT_TWIN_CASE,
        caller_file=Path(__file__),
        method_names=None if args.method is None else tuple(args.method),
    )
    print(f"Benchmark root: {benchmark.benchmark_root}")
    print(f"Summary: {benchmark.summary_path}")
    for result in benchmark.method_results:
        print(
            f"{result.method_name}: meets_success_target={result.meets_success_target} "
            f"recovered_truth={result.recovered_truth} "
            f"cost_best={result.cost_best}"
        )


if __name__ == "__main__":
    main()
