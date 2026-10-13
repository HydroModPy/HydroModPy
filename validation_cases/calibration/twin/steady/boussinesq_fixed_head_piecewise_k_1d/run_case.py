"""Run the steady piecewise-K calibration twin benchmark outside pytest."""

from __future__ import annotations

import argparse
from pathlib import Path

from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.shared.solver_variants import TWIN_SOLVERS
from validation_cases.calibration.twin.steady.boussinesq_fixed_head_piecewise_k_1d.experiment import (
    PIECEWISE_K_TWIN_CASES,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the steady piecewise-K calibration twin benchmark.",
    )
    parser.add_argument("--solver", choices=TWIN_SOLVERS, default="modflow6")
    args = parser.parse_args(argv)
    definition = PIECEWISE_K_TWIN_CASES[str(args.solver)]
    benchmark = run_twin_benchmark_case(
        definition,
        caller_file=Path(__file__),
    )
    print(f"[{definition.case_id}] summary={benchmark.summary_path}")
    for result in benchmark.method_results:
        print(
            f"  {result.method_instance_name}: meets_success_target={result.meets_success_target} "
            f"recovered_truth={result.recovered_truth} "
            f"n_eval={result.n_evaluations} cost_best={result.cost_best}"
        )


if __name__ == "__main__":
    main()
