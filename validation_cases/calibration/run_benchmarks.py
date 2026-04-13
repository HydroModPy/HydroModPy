"""Run calibration twin benchmarks outside pytest."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import median

from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.steady.boussinesq_fixed_head_piecewise_k_1d.experiment import (
    PIECEWISE_K_TWIN_CASE,
)
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_MESH_PERTURBED_TWIN_CASE,
    STEADY_DUPUIT_NOISY_TWIN_CASE,
    STEADY_DUPUIT_POSTERIOR_TWIN_CASE,
    STEADY_DUPUIT_TWIN_CASE,
)
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_NOISY_TWIN_CASE,
    TRANSIENT_RECHARGE_STEP_TWIN_CASE,
)


_CASE_REGISTRY = {
    STEADY_DUPUIT_TWIN_CASE.case_id: STEADY_DUPUIT_TWIN_CASE,
    STEADY_DUPUIT_POSTERIOR_TWIN_CASE.case_id: STEADY_DUPUIT_POSTERIOR_TWIN_CASE,
    STEADY_DUPUIT_MESH_PERTURBED_TWIN_CASE.case_id: STEADY_DUPUIT_MESH_PERTURBED_TWIN_CASE,
    STEADY_DUPUIT_NOISY_TWIN_CASE.case_id: STEADY_DUPUIT_NOISY_TWIN_CASE,
    TRANSIENT_RECHARGE_STEP_TWIN_CASE.case_id: TRANSIENT_RECHARGE_STEP_TWIN_CASE,
    TRANSIENT_RECHARGE_STEP_NOISY_TWIN_CASE.case_id: TRANSIENT_RECHARGE_STEP_NOISY_TWIN_CASE,
    PIECEWISE_K_TWIN_CASE.case_id: PIECEWISE_K_TWIN_CASE,
}


def iter_registered_case_definitions(
    *,
    fast_only: bool = False,
    slow_only: bool = False,
):
    """Yield registered benchmark cases with optional fast/slow filtering."""
    if fast_only and slow_only:
        raise ValueError("fast_only and slow_only cannot both be true")
    definitions = tuple(_CASE_REGISTRY.values())
    if fast_only:
        definitions = tuple(item for item in definitions if bool(item.fast))
    if slow_only:
        definitions = tuple(item for item in definitions if not bool(item.fast))
    return definitions


def _suite_output_root(benchmarks) -> Path | None:
    """Return the common parent directory used by one benchmark suite."""
    roots = [item.benchmark_root.parent for item in benchmarks]
    if not roots:
        return None
    first = roots[0]
    if all(root == first for root in roots):
        return first
    return None


def _safe_mean(values: list[float]) -> float | None:
    """Return the arithmetic mean of a non-empty numeric list."""
    if not values:
        return None
    return float(sum(values) / len(values))


def _safe_std(values: list[float]) -> float | None:
    """Return the population standard deviation of a numeric list."""
    if not values:
        return None
    if len(values) == 1:
        return 0.0
    mean_value = float(sum(values) / len(values))
    variance = sum((float(value) - mean_value) ** 2 for value in values) / len(values)
    return float(math.sqrt(variance))


def _safe_median(values: list[float]) -> float | None:
    """Return the median of a numeric list."""
    if not values:
        return None
    return float(median(values))


def _normalize_json_float(value: float) -> float:
    """Round one finite float for stable human-facing JSON/CSV output."""
    if not math.isfinite(value):
        return value
    return float(f"{value:.15g}")


def _json_value(value):
    """Normalize one value for CSV/JSON aggregate serialization."""
    if isinstance(value, float):
        return _normalize_json_float(value)
    if isinstance(value, dict):
        return json.dumps(
            {str(key): _json_value(item) for key, item in value.items()},
            sort_keys=True,
            ensure_ascii=True,
            default=str,
        )
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _materialize_suite_rows(benchmarks) -> list[dict[str, object]]:
    """Return flattened benchmark rows suitable for CSV, plotting, and reports."""
    rows: list[dict[str, object]] = []
    for benchmark in benchmarks:
        for result in benchmark.method_results:
            row = {
                "case_id": benchmark.definition.case_id,
                "solver_name": benchmark.definition.solver_name,
                "regime": benchmark.definition.regime,
                "method_name": result.method_name,
                "method_instance_name": result.method_instance_name,
                "success_metric": result.success_metric,
                "recovered_truth": result.recovered_truth,
                "meets_success_target": result.meets_success_target,
                "truth_in_distribution": result.truth_in_distribution,
                "n_evaluations": result.n_evaluations,
                "iteration_count": result.iteration_count,
                "repeat_index": result.repeat_index,
                "seed": result.seed,
                "requested_evaluation_budget": result.requested_evaluation_budget,
                "effective_method_kwargs": dict(result.effective_method_kwargs),
                "cost_best": result.cost_best,
                "calibration_time_seconds": result.calibration_time_seconds,
                "time_per_evaluation_seconds": result.time_per_evaluation_seconds,
                "failed_iteration_count": result.failed_iteration_count,
                "candidate_run_count": result.candidate_run_count,
                "objective_cache_hit_count": result.objective_cache_hit_count,
                "objective_cache_hit_rate": result.objective_cache_hit_rate,
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
            for name, value in result.truth_distribution_min_abs_error.items():
                row[f"truth_distribution_min_abs_error__{name}"] = value
            for name, value in result.block_raw_cost_best.items():
                row[f"block_raw_cost_best__{name}"] = value
            for name, value in result.block_normalized_cost_best.items():
                row[f"block_normalized_cost_best__{name}"] = value
            for name, value in result.block_reference_scale.items():
                row[f"block_reference_scale__{name}"] = value
            for name, value in result.block_n_values.items():
                row[f"block_n_values__{name}"] = value
            rows.append(row)
    return rows


def _materialize_method_stat_rows(benchmarks) -> list[dict[str, object]]:
    """Return aggregate benchmark statistics grouped by case and method."""
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for benchmark in benchmarks:
        for result in benchmark.method_results:
            key = (benchmark.definition.case_id, result.method_name)
            grouped.setdefault(key, []).append(
                {
                    "benchmark": benchmark,
                    "result": result,
                }
            )

    rows: list[dict[str, object]] = []
    for (case_id, method_name), items in sorted(grouped.items()):
        benchmark = items[0]["benchmark"]
        results = [item["result"] for item in items]
        tolerances = {
            str(name): float(value)
            for name, value in benchmark.definition.parameter_abs_tolerances.items()
        }
        success_count = sum(1 for item in results if item.recovered_truth)
        target_success_count = sum(
            1 for item in results if item.meets_success_target
        )
        truth_distribution_count = sum(
            1 for item in results if item.truth_in_distribution is True
        )
        finite_costs = [
            float(item.cost_best)
            for item in results
            if item.cost_best is not None and math.isfinite(float(item.cost_best))
        ]
        evaluation_counts = [float(item.n_evaluations) for item in results]
        iteration_counts = [float(item.iteration_count) for item in results]
        calibration_times = [
            float(item.calibration_time_seconds)
            for item in results
            if item.calibration_time_seconds is not None
        ]
        time_per_eval_values = [
            float(item.time_per_evaluation_seconds)
            for item in results
            if item.time_per_evaluation_seconds is not None
        ]
        failed_iterations = [float(item.failed_iteration_count) for item in results]
        cache_hit_rates = [
            float(item.objective_cache_hit_rate)
            for item in results
            if item.objective_cache_hit_rate is not None
        ]

        row: dict[str, object] = {
            "case_id": case_id,
            "solver_name": benchmark.definition.solver_name,
            "regime": benchmark.definition.regime,
            "method_name": method_name,
            "success_metric": results[0].success_metric,
            "requested_evaluation_budget": results[0].requested_evaluation_budget,
            "repeat_count": len(results),
            "success_rate": float(success_count / len(results)),
            "best_fit_rate": float(success_count / len(results)),
            "target_success_rate": float(target_success_count / len(results)),
            "truth_in_distribution_rate": float(truth_distribution_count / len(results)),
            "mean_cost_best": _safe_mean(finite_costs),
            "median_cost_best": _safe_median(finite_costs),
            "std_cost_best": _safe_std(finite_costs),
            "min_cost_best": (None if not finite_costs else min(finite_costs)),
            "max_cost_best": (None if not finite_costs else max(finite_costs)),
            "mean_n_evaluations": _safe_mean(evaluation_counts),
            "mean_iteration_count": _safe_mean(iteration_counts),
            "mean_calibration_time_seconds": _safe_mean(calibration_times),
            "std_calibration_time_seconds": _safe_std(calibration_times),
            "mean_time_per_evaluation_seconds": _safe_mean(time_per_eval_values),
            "std_time_per_evaluation_seconds": _safe_std(time_per_eval_values),
            "mean_failed_iteration_count": _safe_mean(failed_iterations),
            "mean_objective_cache_hit_rate": _safe_mean(cache_hit_rates),
            "mean_model_distribution_sample_count": _safe_mean(
                [float(item.model_distribution_sample_count) for item in results]
            ),
        }

        parameter_names = sorted(
            {
                str(parameter_name)
                for result in results
                for parameter_name in result.param_abs_error
            }
        )
        for parameter_name in parameter_names:
            errors = [
                float(result.param_abs_error[parameter_name])
                for result in results
                if parameter_name in result.param_abs_error
            ]
            best_values = [
                float(result.params_best[parameter_name])
                for result in results
                if parameter_name in result.params_best
            ]
            min_distribution_errors = [
                float(result.truth_distribution_min_abs_error[parameter_name])
                for result in results
                if parameter_name in result.truth_distribution_min_abs_error
            ]
            tolerance = tolerances.get(parameter_name)
            row[f"mean_param_abs_error__{parameter_name}"] = _safe_mean(errors)
            row[f"max_param_abs_error__{parameter_name}"] = (
                None if not errors else max(errors)
            )
            row[f"std_params_best__{parameter_name}"] = _safe_std(best_values)
            row[f"range_params_best__{parameter_name}"] = (
                None if not best_values else max(best_values) - min(best_values)
            )
            row[f"mean_truth_distribution_min_abs_error__{parameter_name}"] = _safe_mean(
                min_distribution_errors
            )
            if tolerance is not None and tolerance > 0.0:
                row[f"mean_param_abs_error_over_tol__{parameter_name}"] = (
                    None
                    if not errors
                    else _safe_mean([float(value) / float(tolerance) for value in errors])
                )
                row[f"range_params_best_over_tol__{parameter_name}"] = (
                    None
                    if not best_values
                    else (max(best_values) - min(best_values)) / float(tolerance)
                )

        block_names = sorted(
            {
                str(block_name)
                for result in results
                for block_name in result.block_normalized_cost_best
            }
        )
        for block_name in block_names:
            normalized_costs = [
                float(result.block_normalized_cost_best[block_name])
                for result in results
                if block_name in result.block_normalized_cost_best
            ]
            raw_costs = [
                float(result.block_raw_cost_best[block_name])
                for result in results
                if block_name in result.block_raw_cost_best
            ]
            row[f"mean_block_normalized_cost_best__{block_name}"] = _safe_mean(
                normalized_costs
            )
            row[f"max_block_normalized_cost_best__{block_name}"] = (
                None if not normalized_costs else max(normalized_costs)
            )
            row[f"mean_block_raw_cost_best__{block_name}"] = _safe_mean(raw_costs)
            row[f"max_block_raw_cost_best__{block_name}"] = (
                None if not raw_costs else max(raw_costs)
            )
        rows.append(row)
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """Write one list of rows to CSV with stable field discovery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        normalized = {key: _json_value(value) for key, value in row.items()}
        normalized_rows.append(normalized)
        for key in normalized:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(normalized_rows)


def _write_suite_summary(benchmarks) -> tuple[Path, Path] | None:
    """Persist one aggregate JSON+CSV summary across selected benchmark cases."""
    output_root = _suite_output_root(benchmarks)
    if output_root is None:
        return None

    json_path = output_root / "benchmark_suite_summary.json"
    csv_path = output_root / "benchmark_suite_summary.csv"
    output_root.mkdir(parents=True, exist_ok=True)
    suite_rows = _materialize_suite_rows(benchmarks)
    payload = {
        "role": "calibration_twin_benchmark_suite",
        "case_count": len(benchmarks),
        "case_ids": [item.definition.case_id for item in benchmarks],
        "cases": [item.to_mapping() for item in benchmarks],
        "rows": [
            {key: _json_value(value) for key, value in row.items()}
            for row in suite_rows
        ],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(csv_path, suite_rows)
    return json_path, csv_path


def _write_method_stats_summary(benchmarks) -> tuple[Path, Path] | None:
    """Persist aggregate benchmark statistics grouped by case and method."""
    output_root = _suite_output_root(benchmarks)
    if output_root is None:
        return None

    rows = _materialize_method_stat_rows(benchmarks)
    json_path = output_root / "benchmark_method_stats.json"
    csv_path = output_root / "benchmark_method_stats.csv"
    output_root.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            {
                "role": "calibration_twin_benchmark_method_stats",
                "rows": [{key: _json_value(value) for key, value in row.items()} for row in rows],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_csv(csv_path, rows)
    return json_path, csv_path


def _write_suite_report(
    benchmarks,
    *,
    figure_paths: tuple[Path, ...],
) -> Path | None:
    """Write one Markdown summary for a benchmark suite."""
    output_root = _suite_output_root(benchmarks)
    if output_root is None:
        return None
    method_rows = _materialize_method_stat_rows(benchmarks)
    report_path = output_root / "benchmark_suite_report.md"
    output_root.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Calibration Twin Benchmark Suite",
        "",
        f"- Cases: {len(benchmarks)}",
        f"- Methods rows: {len(method_rows)}",
        "",
        "## Cases",
        "",
    ]
    for benchmark in benchmarks:
        lines.append(
            f"- `{benchmark.definition.case_id}` "
            f"({benchmark.definition.regime}, solver={benchmark.definition.solver_name}, fast={benchmark.definition.fast})"
        )
    lines.extend(
        [
            "",
            "## Method Summary",
            "",
            "| Case | Method | Success Metric | Target Success | Best Fit | Mean Cost | Mean Eval | Mean Time/Eval (s) |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in method_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["case_id"]),
                    str(row["method_name"]),
                    str(row["success_metric"]),
                    f"{float(row['target_success_rate']):.3f}",
                    f"{float(row['best_fit_rate']):.3f}",
                    (
                        ""
                        if row["mean_cost_best"] is None
                        else f"{float(row['mean_cost_best']):.6g}"
                    ),
                    (
                        ""
                        if row["mean_n_evaluations"] is None
                        else f"{float(row['mean_n_evaluations']):.2f}"
                    ),
                    (
                        ""
                        if row["mean_time_per_evaluation_seconds"] is None
                        else f"{float(row['mean_time_per_evaluation_seconds']):.3f}"
                    ),
                ]
            )
            + " |"
        )
    if figure_paths:
        lines.extend(["", "## Figures", ""])
        for path in figure_paths:
            lines.append(f"- `{path.name}`")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


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
    parser.add_argument(
        "--fast-only",
        action="store_true",
        help="Run only cases marked as fast.",
    )
    parser.add_argument(
        "--slow-only",
        action="store_true",
        help="Run only cases not marked as fast.",
    )
    parser.add_argument(
        "--evaluation-budget",
        type=int,
        default=None,
        help="Approximate common evaluation budget applied heuristically per method.",
    )
    parser.add_argument(
        "--no-figures",
        action="store_true",
        help="Skip suite-level figure generation.",
    )
    parser.add_argument(
        "--figure-format",
        default="png",
        help="Raster format used for generated suite figures (default: png).",
    )
    args = parser.parse_args(argv)

    if args.fast_only and args.slow_only:
        raise SystemExit("--fast-only and --slow-only are mutually exclusive.")

    selected_definitions = iter_registered_case_definitions(
        fast_only=bool(args.fast_only),
        slow_only=bool(args.slow_only),
    )
    if args.case is not None:
        requested_case_ids = tuple(str(item).strip() for item in args.case)
        filtered_definitions = []
        for case_id in requested_case_ids:
            if case_id not in _CASE_REGISTRY:
                raise KeyError(f"Unknown calibration twin benchmark '{case_id}'.")
            filtered_definitions.append(_CASE_REGISTRY[case_id])
        selected_definitions = tuple(filtered_definitions)

    benchmarks = []
    for definition in selected_definitions:
        benchmark = run_twin_benchmark_case(
            definition,
            caller_file=Path(__file__),
            method_names=None if args.method is None else tuple(args.method),
            evaluation_budget=args.evaluation_budget,
        )
        benchmarks.append(benchmark)
        print(f"[{definition.case_id}] summary={benchmark.summary_path}")
        for result in benchmark.method_results:
            print(
                f"  {result.method_instance_name}: meets_success_target={result.meets_success_target} "
                f"recovered_truth={result.recovered_truth} "
                f"n_eval={result.n_evaluations} cost_best={result.cost_best}"
            )
    suite_paths = _write_suite_summary(benchmarks)
    if suite_paths is not None:
        json_path, csv_path = suite_paths
        print(f"[suite] json={json_path}")
        print(f"[suite] csv={csv_path}")
    stats_paths = _write_method_stats_summary(benchmarks)
    if stats_paths is not None:
        json_path, csv_path = stats_paths
        print(f"[suite-stats] json={json_path}")
        print(f"[suite-stats] csv={csv_path}")

    figure_paths: tuple[Path, ...] = ()
    if not args.no_figures:
        from validation_cases.calibration.plotting import write_suite_figures

        figure_paths = write_suite_figures(
            _materialize_method_stat_rows(benchmarks),
            output_root=_suite_output_root(benchmarks),
            figure_format=str(args.figure_format),
        )
        for figure_path in figure_paths:
            print(f"[suite-figure] {figure_path}")

    report_path = _write_suite_report(
        benchmarks,
        figure_paths=figure_paths,
    )
    if report_path is not None:
        print(f"[suite-report] {report_path}")


if __name__ == "__main__":
    main()
