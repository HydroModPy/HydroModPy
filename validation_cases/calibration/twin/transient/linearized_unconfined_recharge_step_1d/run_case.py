"""Run the transient recharge-step twin benchmark outside pytest."""

from __future__ import annotations

import argparse
from pathlib import Path

from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.shared.solver_variants import TWIN_SOLVERS
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASES,
    TRANSIENT_RECHARGE_STEP_NOISY_TWIN_CASE,
    TRANSIENT_RECHARGE_STEP_TWIN_CASES,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the transient recharge-step calibration twin benchmark.",
    )
    parser.add_argument(
        "--case",
        choices=("standard", "noisy", "flux_only_noisy"),
        default="standard",
        help="Twin-benchmark variant to run.",
    )
    parser.add_argument(
        "--method",
        action="append",
        default=None,
        help="Optional method name filter. Repeat to select multiple methods.",
    )
    parser.add_argument(
        "--solver",
        choices=TWIN_SOLVERS,
        default="modflow6",
        help="Solver column of the standard and flux_only_noisy variants.",
    )
    args = parser.parse_args(argv)
    if args.solver != "modflow6" and args.case == "noisy":
        parser.error("--solver other than modflow6 needs --case standard or flux_only_noisy")
    definition = {
        "standard": TRANSIENT_RECHARGE_STEP_TWIN_CASES[str(args.solver)],
        "noisy": TRANSIENT_RECHARGE_STEP_NOISY_TWIN_CASE,
        "flux_only_noisy": TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASES[str(args.solver)],
    }[str(args.case)]
    benchmark = run_twin_benchmark_case(
        definition,
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
