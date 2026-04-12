"""Run calibration twin benchmarks outside pytest."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_TWIN_CASE,
)
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_TWIN_CASE,
)


_CASE_REGISTRY = {
    STEADY_DUPUIT_TWIN_CASE.case_id: STEADY_DUPUIT_TWIN_CASE,
    TRANSIENT_RECHARGE_STEP_TWIN_CASE.case_id: TRANSIENT_RECHARGE_STEP_TWIN_CASE,
}


def _suite_output_root(benchmarks) -> Path | None:
    """Return the common parent directory used by one benchmark suite."""
    roots = [item.benchmark_root.parent for item in benchmarks]
    if not roots:
        return None
    first = roots[0]
    if all(root == first for root in roots):
        return first
    return None


def _write_suite_summary(benchmarks) -> tuple[Path, Path] | None:
    """Persist one aggregate JSON+CSV summary across selected benchmark cases."""
    output_root = _suite_output_root(benchmarks)
    if output_root is None:
        return None

    json_path = output_root / "benchmark_suite_summary.json"
    csv_path = output_root / "benchmark_suite_summary.csv"

    payload = {
        "role": "calibration_twin_benchmark_suite",
        "case_count": len(benchmarks),
        "cases": [item.to_mapping() for item in benchmarks],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    rows: list[dict[str, object]] = []
    for benchmark in benchmarks:
        for result in benchmark.method_results:
            row = {
                "case_id": benchmark.definition.case_id,
                "solver_name": benchmark.definition.solver_name,
                "regime": benchmark.definition.regime,
                "method_name": result.method_name,
                "recovered_truth": result.recovered_truth,
                "truth_in_distribution": result.truth_in_distribution,
                "n_evaluations": result.n_evaluations,
                "iteration_count": result.iteration_count,
                "cost_best": result.cost_best,
                "model_distribution_sample_count": (
                    result.model_distribution_sample_count
                ),
                "benchmark_root": str(benchmark.benchmark_root),
                "calibration_root": str(result.calibration_root),
            }
            for name, value in result.param_abs_error.items():
                row[f"param_abs_error__{name}"] = value
            for name, value in result.params_best.items():
                row[f"params_best__{name}"] = value
            rows.append(row)

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run one or more calibration twin benchmarks.",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=None,
        help="Optional case id filter. Repeat to select multiple cases.",
    )
    parser.add_argument(
        "--method",
        action="append",
        default=None,
        help="Optional method name filter. Repeat to select multiple methods.",
    )
    args = parser.parse_args(argv)

    selected_case_ids = (
        tuple(_CASE_REGISTRY)
        if args.case is None
        else tuple(str(item).strip() for item in args.case)
    )
    benchmarks = []
    for case_id in selected_case_ids:
        if case_id not in _CASE_REGISTRY:
            raise KeyError(f"Unknown calibration twin benchmark '{case_id}'.")
        benchmark = run_twin_benchmark_case(
            _CASE_REGISTRY[case_id],
            caller_file=Path(__file__),
            method_names=None if args.method is None else tuple(args.method),
        )
        benchmarks.append(benchmark)
        print(f"[{case_id}] summary={benchmark.summary_path}")
        for result in benchmark.method_results:
            print(
                f"  {result.method_name}: recovered_truth={result.recovered_truth} "
                f"n_eval={result.n_evaluations} cost_best={result.cost_best}"
            )
    suite_paths = _write_suite_summary(benchmarks)
    if suite_paths is not None:
        json_path, csv_path = suite_paths
        print(f"[suite] json={json_path}")
        print(f"[suite] csv={csv_path}")


if __name__ == "__main__":
    main()
