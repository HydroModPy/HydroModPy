from __future__ import annotations

import json
from pathlib import Path

import pytest

from validation_cases.calibration.plotting import (
    write_case_configuration_figure,
    write_case_method_figures,
    write_suite_figures,
)
from validation_cases.calibration.run_benchmarks import (
    _materialize_method_stat_rows,
    _write_method_stats_summary,
    _write_suite_report,
    _write_suite_summary,
    iter_registered_case_definitions,
)
from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    TwinCalibrationBenchmarkResult,
    TwinCalibrationCaseDefinition,
    TwinMethodBenchmarkResult,
)
from validation_cases.calibration.shared.runtime import (
    _apply_evaluation_budget,
    _prune_benchmark_artifacts,
)


def _make_result(
    *,
    benchmark_root: Path,
    method_name: str,
    method_instance_name: str,
    success_metric: str,
    cost_best: float,
    n_evaluations: int,
    calibration_time_seconds: float,
    params_best: dict[str, float],
    param_abs_error: dict[str, float],
    truth_in_distribution: bool | None = None,
    requested_evaluation_budget: int | None = None,
) -> TwinMethodBenchmarkResult:
    return TwinMethodBenchmarkResult(
        method_name=method_name,
        method_instance_name=method_instance_name,
        success_metric=success_metric,
        effective_method_kwargs={"seed": 7},
        requested_evaluation_budget=requested_evaluation_budget,
        calibration_id=f"{method_instance_name}_id",
        calibration_root=benchmark_root / method_instance_name,
        result_path=None,
        cost_best=cost_best,
        iteration_count=n_evaluations,
        n_evaluations=n_evaluations,
        params_best=dict(params_best),
        param_abs_error=dict(param_abs_error),
        recovered_truth=True,
        repeat_index=1,
        seed=7 if "seed" in method_instance_name else None,
        calibration_time_seconds=calibration_time_seconds,
        time_per_evaluation_seconds=calibration_time_seconds / n_evaluations,
        session_prepare_time_seconds=0.5,
        estimated_candidate_runtime_seconds=0.75 * calibration_time_seconds,
        algorithm_overhead_time_seconds=0.25 * calibration_time_seconds,
        mean_candidate_total_time_seconds=(0.75 * calibration_time_seconds) / n_evaluations,
        mean_candidate_actualize_time_seconds=0.01,
        mean_candidate_launcher_prepare_time_seconds=0.02,
        mean_candidate_runtime_patch_time_seconds=0.001,
        mean_candidate_simulation_time_seconds=0.05,
        mean_candidate_output_selection_time_seconds=0.004,
        mean_candidate_objective_build_time_seconds=0.002,
        mean_candidate_objective_compute_time_seconds=0.006,
        failed_iteration_count=0,
        meets_success_target=True,
        candidate_run_count=n_evaluations,
        objective_cache_hit_count=1,
        objective_cache_hit_rate=1.0 / float(n_evaluations),
        block_raw_cost_best={"heads": cost_best / 10.0},
        block_normalized_cost_best={"heads": cost_best},
        block_reference_scale={"heads": 0.1},
        block_n_values={"heads": 20},
        model_distribution_path=None,
        model_distribution_sample_count=8,
        truth_in_distribution=truth_in_distribution,
        truth_distribution_min_abs_error={"K": 0.01} if truth_in_distribution else {},
    )


def test_iter_registered_case_definitions_fast_only_filters_cases() -> None:
    fast_cases = iter_registered_case_definitions(fast_only=True)
    slow_cases = iter_registered_case_definitions(slow_only=True)

    assert fast_cases
    assert all(case.fast for case in fast_cases)
    assert slow_cases
    assert all(not case.fast for case in slow_cases)


def test_apply_evaluation_budget_adapts_known_methods() -> None:
    grid = _apply_evaluation_budget(
        CalibrationMethodProfile(name="grid_search", method_kwargs={"n_per_dim": 9}),
        n_parameters=2,
        evaluation_budget=10,
    )
    random = _apply_evaluation_budget(
        CalibrationMethodProfile(name="random_search", method_kwargs={"n_samples": 99, "seed": 1}),
        n_parameters=2,
        evaluation_budget=10,
    )
    simplex = _apply_evaluation_budget(
        CalibrationMethodProfile(name="simplex", method_kwargs={"max_iter": 50}),
        n_parameters=2,
        evaluation_budget=10,
    )
    gp_mapping = _apply_evaluation_budget(
        CalibrationMethodProfile(
            name="gp_mapping",
            method_kwargs={
                "seed": 1,
                "n_init": 8,
                "n_refine": 6,
                "batch_size": 2,
                "n_candidates": 20,
                "kappa": 1.0,
                "alpha": 1.0e-6,
                "jitter": 1.0e-8,
                "n_posterior_pool": 20,
                "n_posterior_samples": 4,
                "log_transform": False,
            },
        ),
        n_parameters=2,
        evaluation_budget=10,
    )
    da_mh = _apply_evaluation_budget(
        CalibrationMethodProfile(
            name="da_mh_gp",
            method_kwargs={
                "n_init": 10,
                "n_samples": 96,
                "burn_in": 24,
                "thin": 2,
                "proposal_scale": 0.04,
            },
        ),
        n_parameters=2,
        evaluation_budget=12,
    )

    assert grid.method_kwargs["n_per_dim"] == 3
    assert random.method_kwargs["n_samples"] == 10
    assert simplex.method_kwargs["max_iter"] == 10
    assert simplex.method_kwargs["max_fun"] == 10
    assert gp_mapping.method_kwargs["n_init"] <= 10
    assert gp_mapping.method_kwargs["n_init"] + (
        gp_mapping.method_kwargs["n_refine"] * gp_mapping.method_kwargs["batch_size"]
    ) <= 10
    retained = (
        da_mh.method_kwargs["n_samples"] - da_mh.method_kwargs["burn_in"]
        + da_mh.method_kwargs["thin"] - 1
    ) // da_mh.method_kwargs["thin"]
    assert retained >= 8


def test_benchmark_suite_writers_emit_extended_outputs(tmp_path: Path) -> None:
    suite_root = tmp_path / "suite"
    benchmark_root = suite_root / "case_a"
    definition = TwinCalibrationCaseDefinition(
        case_id="case_a",
        solver_name="modflow6",
        regime="steady",
        description="demo",
        truth_params={"K": 1.0},
        bounds={"K": (0.5, 1.5)},
        parameter_abs_tolerances={"K": 0.1},
        output_names=("q",),
        method_profiles=(
            CalibrationMethodProfile(name="random_search", method_kwargs={"n_samples": 8}),
        ),
        fast=True,
    )
    benchmark = TwinCalibrationBenchmarkResult(
        definition=definition,
        benchmark_root=benchmark_root,
        simulation_config_path=benchmark_root / "simulation.toml",
        truth_simulation_config_path=benchmark_root / "truth_simulation.toml",
        observations_truth={"q": (1.0,)},
        observations_used={"q": (1.05,)},
        method_results=(
            _make_result(
                benchmark_root=benchmark_root,
                method_name="random_search",
                method_instance_name="random_search_seed007",
                success_metric="best_fit",
                cost_best=0.5,
                n_evaluations=8,
                calibration_time_seconds=4.0,
                params_best={"K": 1.02},
                param_abs_error={"K": 0.02},
                truth_in_distribution=True,
                requested_evaluation_budget=8,
            ),
            _make_result(
                benchmark_root=benchmark_root,
                method_name="random_search",
                method_instance_name="random_search_seed011",
                success_metric="best_fit",
                cost_best=0.8,
                n_evaluations=8,
                calibration_time_seconds=6.0,
                params_best={"K": 0.98},
                param_abs_error={"K": 0.02},
                truth_in_distribution=True,
                requested_evaluation_budget=8,
            ),
        ),
        summary_path=benchmark_root / "benchmark_summary.json",
    )

    suite_paths = _write_suite_summary((benchmark,))
    stats_paths = _write_method_stats_summary((benchmark,))
    method_rows = _materialize_method_stat_rows((benchmark,))
    figure_paths = write_suite_figures(method_rows, output_root=suite_root)
    report_path = _write_suite_report((benchmark,), figure_paths=figure_paths)

    assert suite_paths is not None
    assert stats_paths is not None
    suite_json, suite_csv = suite_paths
    stats_json, stats_csv = stats_paths
    assert suite_json.is_file()
    assert suite_csv.is_file()
    assert stats_json.is_file()
    assert stats_csv.is_file()
    assert report_path is not None and report_path.is_file()

    payload = json.loads(stats_json.read_text(encoding="utf-8"))
    assert payload["rows"][0]["target_success_rate"] == 1.0
    assert payload["rows"][0]["mean_time_per_evaluation_seconds"] == 0.625
    assert payload["rows"][0]["mean_param_abs_error_over_tol__K"] == 0.2
    assert payload["rows"][0]["mean_algorithm_overhead_time_seconds"] == 1.25
    assert "mean_candidate_preparation_time_seconds" in payload["rows"][0]
    assert "mean_candidate_simulation_time_seconds" in payload["rows"][0]

    suite_payload = json.loads(suite_json.read_text(encoding="utf-8"))
    assert (
        suite_payload["cases"][0]["truth_simulation_config_path"]
        == str(benchmark_root / "truth_simulation.toml")
    )

    csv_text = stats_csv.read_text(encoding="utf-8")
    assert "mean_block_normalized_cost_best__heads" in csv_text
    assert "requested_evaluation_budget" in csv_text
    assert "success_metric" in csv_text
    assert "mean_algorithm_overhead_time_seconds" in csv_text

    assert figure_paths
    assert all(path.is_file() for path in figure_paths)
    report_text = report_path.read_text(encoding="utf-8")
    assert "Calibration Twin Benchmark Suite" in report_text
    assert "random_search" in report_text
    assert "Algorithm Overhead (s)" in report_text


def test_case_method_figures_and_minimal_pruning(tmp_path: Path) -> None:
    benchmark_root = tmp_path / "case_a"
    calibration_root = benchmark_root / "project" / "results_calibration" / "method_a"
    calibration_root.mkdir(parents=True, exist_ok=True)
    history_path = calibration_root / "iteration_history.jsonl"
    history_rows = [
        {
            "iteration_id": "iter_0001",
            "params_vector": [0.9],
            "params_named": {"K": 0.9},
            "objective_total": 2.0,
            "block_costs": {"flux": 2.0},
            "status": "objective_evaluated",
            "failure_reason": None,
        },
        {
            "iteration_id": "iter_0002",
            "params_vector": [1.0],
            "params_named": {"K": 1.0},
            "objective_total": 0.2,
            "block_costs": {"flux": 0.2},
            "status": "objective_evaluated",
            "failure_reason": None,
        },
        {
            "iteration_id": "iter_0003",
            "params_vector": [1.1],
            "params_named": {"K": 1.1},
            "objective_total": 1.0,
            "block_costs": {"flux": 1.0},
            "status": "objective_evaluated",
            "failure_reason": None,
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=True) for row in history_rows) + "\n",
        encoding="utf-8",
    )
    distribution_path = calibration_root / "model_distribution.json"
    distribution_path.write_text(
        json.dumps(
            {
                "samples": [
                    {"params_named": {"K": 0.98}},
                    {"params_named": {"K": 1.01}},
                ]
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    definition = TwinCalibrationCaseDefinition(
        case_id="case_a",
        solver_name="modflow6",
        regime="steady",
        description="demo",
        truth_params={"K": 1.0},
        bounds={"K": (0.8, 1.2)},
        parameter_abs_tolerances={"K": 0.1},
        output_names=("q",),
        method_profiles=(),
        fast=True,
    )
    configuration_figure = write_case_configuration_figure(
        benchmark_root=benchmark_root,
        definition=definition,
        simulation_config_path=benchmark_root / "simulation.toml",
        truth_simulation_config_path=benchmark_root / "simulation.toml",
        artifact_retention="minimal",
    )
    assert configuration_figure is not None
    assert configuration_figure.is_file()

    result = TwinMethodBenchmarkResult(
        method_name="random_search",
        method_instance_name="random_search_seed007",
        success_metric="best_fit_or_distribution",
        effective_method_kwargs={"seed": 7},
        requested_evaluation_budget=8,
        calibration_id="calibration_a",
        calibration_root=calibration_root,
        result_path=None,
        cost_best=0.2,
        iteration_count=3,
        n_evaluations=3,
        params_best={"K": 1.0},
        param_abs_error={"K": 0.0},
        recovered_truth=True,
        iteration_history_path=history_path,
        model_distribution_path=distribution_path,
        model_distribution_sample_count=2,
        truth_in_distribution=True,
    )

    figure_paths = write_case_method_figures(
        benchmark_root=benchmark_root,
        definition=definition,
        result=result,
    )

    assert "objective_trace" in figure_paths
    assert "objective_landscape" in figure_paths
    assert "posterior_distribution" in figure_paths
    assert figure_paths["objective_trace"].is_file()
    assert figure_paths["objective_landscape"].is_file()
    assert figure_paths["posterior_distribution"].is_file()

    results_simulations = benchmark_root / "project" / "results_simulations"
    results_stable = benchmark_root / "project" / "results_stable"
    project_truth = benchmark_root / "project_truth"
    (results_simulations / "dummy").mkdir(parents=True, exist_ok=True)
    (results_stable / "dummy").mkdir(parents=True, exist_ok=True)
    (benchmark_root / "project" / "hydromodpy_debug.log").write_text(
        "x",
        encoding="utf-8",
    )
    (project_truth / "results_simulations").mkdir(parents=True, exist_ok=True)
    (project_truth / "results_stable").mkdir(parents=True, exist_ok=True)
    (project_truth / "hydromodpy_debug.log").write_text("x", encoding="utf-8")

    removed = _prune_benchmark_artifacts(
        benchmark_root=benchmark_root,
        retention="minimal",
    )

    assert removed
    assert not results_simulations.exists()
    assert not results_stable.exists()
    assert calibration_root.exists()


def test_case_method_figures_use_regular_objective_grid_for_two_parameters(
    tmp_path: Path,
) -> None:
    benchmark_root = tmp_path / "case_b"
    calibration_root = benchmark_root / "project" / "results_calibration" / "method_b"
    calibration_root.mkdir(parents=True, exist_ok=True)
    history_path = calibration_root / "iteration_history.jsonl"
    history_rows = [
        {
            "iteration_id": "iter_0001",
            "params_vector": [0.9, 0.08],
            "params_named": {"K": 0.9, "Sy": 0.08},
            "objective_total": 1.2,
            "block_costs": {"heads": 0.7, "flux": 0.5},
            "status": "objective_evaluated",
            "failure_reason": None,
        },
        {
            "iteration_id": "iter_0002",
            "params_vector": [1.0, 0.10],
            "params_named": {"K": 1.0, "Sy": 0.10},
            "objective_total": 0.05,
            "block_costs": {"heads": 0.03, "flux": 0.02},
            "status": "objective_evaluated",
            "failure_reason": None,
        },
        {
            "iteration_id": "iter_0003",
            "params_vector": [1.1, 0.12],
            "params_named": {"K": 1.1, "Sy": 0.12},
            "objective_total": 0.9,
            "block_costs": {"heads": 0.5, "flux": 0.4},
            "status": "objective_evaluated",
            "failure_reason": None,
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=True) for row in history_rows) + "\n",
        encoding="utf-8",
    )
    (benchmark_root / "objective_regular_grid.json").write_text(
        json.dumps(
            {
                "role": "calibration_regular_objective_grid",
                "case_id": "case_b",
                "parameter_names": ["K", "Sy"],
                "n_per_dim": 3,
                "x": [0.8, 1.0, 1.2],
                "y": [0.06, 0.10, 0.14],
                "objective_total": [
                    [1.5, 0.8, 1.0],
                    [0.7, 0.05, 0.6],
                    [1.1, 0.7, 1.4],
                ],
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    definition = TwinCalibrationCaseDefinition(
        case_id="case_b",
        solver_name="modflow6",
        regime="transient",
        description="demo2d",
        truth_params={"K": 1.0, "Sy": 0.10},
        bounds={"K": (0.8, 1.2), "Sy": (0.06, 0.14)},
        parameter_abs_tolerances={"K": 0.1, "Sy": 0.03},
        output_names=("head", "q"),
        method_profiles=(),
        fast=True,
    )
    result = TwinMethodBenchmarkResult(
        method_name="simplex",
        method_instance_name="simplex",
        success_metric="best_fit",
        effective_method_kwargs={},
        requested_evaluation_budget=None,
        calibration_id="calibration_b",
        calibration_root=calibration_root,
        result_path=None,
        cost_best=0.05,
        iteration_count=3,
        n_evaluations=3,
        params_best={"K": 1.0, "Sy": 0.10},
        param_abs_error={"K": 0.0, "Sy": 0.0},
        recovered_truth=True,
        iteration_history_path=history_path,
    )

    figure_paths = write_case_method_figures(
        benchmark_root=benchmark_root,
        definition=definition,
        result=result,
    )

    assert "objective_trace" in figure_paths
    assert "objective_landscape" in figure_paths
    assert figure_paths["objective_trace"].is_file()
    assert figure_paths["objective_landscape"].is_file()
