"""Runtime helpers for calibration same-solver twin benchmarks."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.calibration.engine.launcher import ModelCalibrationLauncher
from hydromodpy.analysis.calibration.engine.session import (
    actualize_candidate,
    execute_candidate_run,
    select_candidate_outputs,
)
from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    ObservationNoiseSpec,
    TwinCalibrationBenchmarkResult,
    TwinCalibrationCaseDefinition,
    TwinMethodBenchmarkResult,
)
from validation_cases.shared.runtime import _dump_toml, resolve_validation_results_dir


def _write_toml(path: Path, payload: dict[str, Any]) -> None:
    """Write one TOML payload to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def _short_digest(text: str, *, size: int = 8) -> str:
    """Return one short stable digest used to keep Windows paths compact."""
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[: int(size)]


def _compact_method_code(method_name: str) -> str:
    """Return one short readable code for a calibration method."""
    mapping = {
        "grid_search": "gs",
        "random_search": "rs",
        "simplex": "sx",
        "nelder_mead": "nm",
        "gp_mapping": "gpm",
        "da_mh_gp": "damh",
        "truth": "tr",
    }
    token = str(method_name).strip().lower()
    return mapping.get(token, token[:4] or "m")


def _compact_case_code(definition: TwinCalibrationCaseDefinition) -> str:
    """Return one short stable identifier for a benchmark case."""
    return f"ct_{_short_digest(definition.case_id, size=10)}"


def _compact_calibration_id(
    definition: TwinCalibrationCaseDefinition,
    method_name: str,
) -> str:
    """Return one short calibration id to avoid path-length failures on Windows."""
    method_token = _compact_method_code(method_name)
    method_suffix = _short_digest(method_name, size=6)
    return (
        f"{_compact_case_code(definition)}_"
        f"{method_token}_{method_suffix}"
    )


def _resolve_twin_benchmark_root(
    definition: TwinCalibrationCaseDefinition,
) -> Path:
    """Resolve one compact deterministic output root for a twin benchmark."""
    return resolve_validation_results_dir(
        test_file="validation_calibration_twin.py",
        run_name=_compact_case_code(definition),
    )


def _normalize_selected_outputs(selected: dict[str, Any]) -> dict[str, tuple[float, ...]]:
    """Convert selected observables to stable float tuples."""
    normalized: dict[str, tuple[float, ...]] = {}
    for name, values in selected.items():
        arr = np.asarray(values, dtype=float).reshape(-1)
        normalized[str(name)] = tuple(float(value) for value in arr)
    return normalized


def _remove_artifact_path(path: Path, *, removed: list[str]) -> None:
    """Remove one heavy artifact path when it exists."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path))
        elif path.is_file():
            path.unlink()
            removed.append(str(path))
    except OSError:
        return


def _prune_benchmark_artifacts(
    *,
    benchmark_root: Path,
    retention: str,
) -> tuple[str, ...]:
    """Prune heavy benchmark artifacts according to the selected retention mode."""
    mode = str(retention).strip().lower() or "minimal"
    if mode == "full":
        return ()
    if mode != "minimal":
        raise ValueError(
            f"Unsupported calibration benchmark artifact_retention '{retention}'."
        )

    removed: list[str] = []
    for project_name in ("project", "project_truth"):
        project_root = benchmark_root / project_name
        _remove_artifact_path(
            project_root / "results_simulations",
            removed=removed,
        )
        _remove_artifact_path(
            project_root / "results_stable",
            removed=removed,
        )
        _remove_artifact_path(
            project_root / "hydromodpy_debug.log",
            removed=removed,
        )
        if project_root.is_dir() and not any(project_root.iterdir()):
            _remove_artifact_path(project_root, removed=removed)
    return tuple(removed)


def _placeholder_observations(
    definition: TwinCalibrationCaseDefinition,
) -> dict[str, tuple[float, ...]]:
    """Return one minimal observed-value mapping accepted by config parsing."""
    return {str(name): (0.0,) for name in definition.output_names}


def _apply_observation_noise(
    observations: dict[str, tuple[float, ...]],
    *,
    noise: ObservationNoiseSpec | None,
) -> dict[str, tuple[float, ...]]:
    """Apply one deterministic Gaussian perturbation to synthetic observations."""
    if noise is None:
        return {
            str(name): tuple(float(value) for value in values)
            for name, values in observations.items()
        }
    rng = np.random.default_rng(int(noise.seed))
    perturbed: dict[str, tuple[float, ...]] = {}
    for name, values in observations.items():
        arr = np.asarray(values, dtype=float).reshape(-1)
        abs_sigma = float(noise.absolute_sigma_by_output.get(str(name), 0.0))
        rel_sigma = float(noise.relative_sigma_by_output.get(str(name), 0.0))
        sigma = np.sqrt(abs_sigma**2 + (rel_sigma * np.abs(arr)) ** 2)
        if np.any(sigma > 0.0):
            arr = arr + rng.normal(loc=0.0, scale=sigma, size=arr.shape)
        perturbed[str(name)] = tuple(float(value) for value in arr)
    return perturbed


def _seeded_method_profile(
    profile: CalibrationMethodProfile,
    *,
    seed: int | None,
) -> CalibrationMethodProfile:
    """Clone one method profile with an overridden stochastic seed."""
    if seed is None:
        return profile
    kwargs = dict(profile.method_kwargs)
    kwargs[str(profile.seed_kwarg_name)] = int(seed)
    return CalibrationMethodProfile(
        name=profile.name,
        method_kwargs=kwargs,
        persist_model_distribution=profile.persist_model_distribution,
        repeat_seeds=(),
        seed_kwarg_name=profile.seed_kwarg_name,
        success_metric=profile.success_metric,
    )


def _apply_evaluation_budget(
    profile: CalibrationMethodProfile,
    *,
    n_parameters: int,
    evaluation_budget: int | None,
) -> CalibrationMethodProfile:
    """Adapt one method profile to an approximate common evaluation budget."""
    if evaluation_budget is None:
        return profile
    budget = int(evaluation_budget)
    if budget <= 0:
        raise ValueError("evaluation_budget must be > 0")

    kwargs = dict(profile.method_kwargs)
    method = str(profile.name).strip().lower()
    if method == "grid_search":
        n_per_dim = max(1, int(budget ** (1.0 / max(1, n_parameters))))
        kwargs["n_per_dim"] = int(n_per_dim)
    elif method == "random_search":
        kwargs["n_samples"] = int(budget)
    elif method == "simplex":
        kwargs["max_iter"] = int(budget)
        kwargs["max_fun"] = int(budget)
    elif method == "nelder_mead":
        kwargs["max_iter"] = int(budget)
    elif method == "gp_mapping":
        batch_size = max(1, int(kwargs.get("batch_size", 1)))
        n_init_default = max(1, int(kwargs.get("n_init", batch_size)))
        n_init = min(n_init_default, budget)
        remaining = max(0, budget - n_init)
        kwargs["n_init"] = int(n_init)
        kwargs["n_refine"] = int(remaining // batch_size)
    elif method == "da_mh_gp":
        base_init = max(1, int(kwargs.get("n_init", max(1, budget // 5))))
        base_samples = max(1, int(kwargs.get("n_samples", max(1, budget))))
        scale = float(budget) / float(base_init + base_samples)
        kwargs["n_init"] = max(1, int(round(base_init * scale)))
        kwargs["n_samples"] = max(1, int(round(base_samples * scale)))
        burn_in = kwargs.get("burn_in")
        if burn_in is not None:
            kwargs["burn_in"] = min(int(burn_in), max(0, int(kwargs["n_samples"]) - 1))
        thin = max(1, int(kwargs.get("thin", 1)))
        retained_target = max(8, min(32, int(budget)))
        retained_count = max(
            0,
            (int(kwargs["n_samples"]) - int(kwargs.get("burn_in", 0)) + thin - 1) // thin,
        )
        if retained_count < retained_target:
            kwargs["n_samples"] = int(kwargs.get("burn_in", 0)) + thin * retained_target
    else:
        raise ValueError(
            f"Unsupported evaluation-budget adaptation for method '{profile.name}'."
        )

    return CalibrationMethodProfile(
        name=profile.name,
        method_kwargs=kwargs,
        persist_model_distribution=profile.persist_model_distribution,
        repeat_seeds=profile.repeat_seeds,
        seed_kwarg_name=profile.seed_kwarg_name,
        success_metric=profile.success_metric,
    )


def _iter_selected_method_runs(
    selected_profiles: tuple[CalibrationMethodProfile, ...],
):
    """Yield one concrete method execution per selected profile and seed repeat."""
    for profile in selected_profiles:
        seeds = tuple(int(value) for value in profile.repeat_seeds)
        if not seeds:
            yield {
                "profile": profile,
                "effective_profile": profile,
                "instance_name": profile.name,
                "repeat_index": 1,
                "seed": (
                    None
                    if profile.seed_kwarg_name not in profile.method_kwargs
                    else int(profile.method_kwargs[profile.seed_kwarg_name])
                ),
            }
            continue
        for repeat_index, seed in enumerate(seeds, start=1):
            yield {
                "profile": profile,
                "effective_profile": _seeded_method_profile(profile, seed=seed),
                "instance_name": f"{profile.name}_seed{int(seed):03d}",
                "repeat_index": int(repeat_index),
                "seed": int(seed),
            }


def synthesize_truth_observations(
    *,
    definition: TwinCalibrationCaseDefinition,
    truth_simulation_config_path: Path,
    benchmark_root: Path,
    launcher_factory: Any = None,
) -> dict[str, dict[str, tuple[float, ...]]]:
    """Run the truth candidate once and extract the synthetic observations."""
    if definition.build_calibration_payload is None:
        raise ValueError("Twin calibration case is missing build_calibration_payload")
    truth_method = CalibrationMethodProfile(
        name="random_search",
        method_kwargs={"n_samples": 1, "seed": 7},
        persist_model_distribution=False,
    )
    truth_calibration_path = benchmark_root / "truth_calibration.toml"
    truth_payload = definition.build_calibration_payload(
        truth_simulation_config_path.name,
        _compact_calibration_id(definition, "truth"),
        _placeholder_observations(definition),
        truth_method,
    )
    _write_toml(truth_calibration_path, truth_payload)

    launcher = ModelCalibrationLauncher(truth_calibration_path)
    request = actualize_candidate(
        session=launcher.prepare(),
        cfg=launcher.cfg,
        params=dict(definition.truth_params),
        candidate_label="truth",
        disable_postprocess=False,
    )
    outcome = execute_candidate_run(
        request=request,
        launcher_factory=launcher_factory,
        cfg=None,
    )
    if outcome.status != "solver_run_succeeded":
        raise RuntimeError(
            f"Truth simulation failed for benchmark '{definition.case_id}': "
            f"{outcome.error_message or outcome.status}"
        )
    selected = select_candidate_outputs(
        cfg=launcher.cfg,
        run_state=outcome.run_state,
        session=request.session,
    )
    clean_observations = _normalize_selected_outputs(selected)
    used_observations = _apply_observation_noise(
        clean_observations,
        noise=definition.observation_noise,
    )
    truth_output_path = benchmark_root / "truth_observations.json"
    truth_output_path.write_text(
        json.dumps(
            {
                "role": "synthetic_truth_observations",
                "case_id": definition.case_id,
                "solver_name": definition.solver_name,
                "truth_simulation_config_path": str(truth_simulation_config_path),
                "truth_params": {
                    str(name): float(value)
                    for name, value in definition.truth_params.items()
                },
                "observations_truth": {
                    str(name): [float(value) for value in values]
                    for name, values in clean_observations.items()
                },
                "observations_used": {
                    str(name): [float(value) for value in values]
                    for name, values in used_observations.items()
                },
                "observation_noise": (
                    None
                    if definition.observation_noise is None
                    else {
                        "absolute_sigma_by_output": {
                            str(name): float(value)
                            for name, value in definition.observation_noise.absolute_sigma_by_output.items()
                        },
                        "relative_sigma_by_output": {
                            str(name): float(value)
                            for name, value in definition.observation_noise.relative_sigma_by_output.items()
                        },
                        "seed": int(definition.observation_noise.seed),
                    }
                ),
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "truth": clean_observations,
        "used": used_observations,
    }


def _param_abs_error(
    *,
    truth_params: dict[str, float],
    params_best: dict[str, Any],
) -> dict[str, float]:
    """Return absolute parameter errors against the truth."""
    errors: dict[str, float] = {}
    for name, truth in truth_params.items():
        raw_value = params_best.get(name)
        if raw_value is None:
            errors[str(name)] = math.inf
            continue
        errors[str(name)] = abs(float(raw_value) - float(truth))
    return errors


def _distribution_truth_metrics(
    *,
    model_distribution_path: Path | None,
    truth_params: dict[str, float],
    abs_tolerances: dict[str, float],
) -> tuple[int, bool | None, dict[str, float]]:
    """Evaluate whether a persisted distribution covers the truth within tolerances."""
    if model_distribution_path is None or not model_distribution_path.is_file():
        return 0, None, {}
    payload = json.loads(model_distribution_path.read_text(encoding="utf-8"))
    samples = payload.get("samples", [])
    if not isinstance(samples, list):
        return 0, None, {}

    min_errors = {str(name): math.inf for name in truth_params}
    truth_in_distribution = False
    for sample in samples:
        params_named = sample.get("params_named", {})
        if not isinstance(params_named, dict):
            continue
        sample_ok = True
        for name, truth in truth_params.items():
            raw_value = params_named.get(name)
            if raw_value is None:
                sample_ok = False
                continue
            error = abs(float(raw_value) - float(truth))
            if error < min_errors[str(name)]:
                min_errors[str(name)] = float(error)
            if error > float(abs_tolerances[str(name)]):
                sample_ok = False
        if sample_ok:
            truth_in_distribution = True

    normalized_min_errors = {
        str(name): (None if not math.isfinite(value) else float(value))
        for name, value in min_errors.items()
    }
    return int(len(samples)), truth_in_distribution, normalized_min_errors


def _estimate_candidate_runtime_seconds(
    *,
    mean_candidate_total_time_seconds: float | None,
    candidate_run_count: int,
    n_evaluations: int,
) -> float | None:
    """Estimate aggregate candidate runtime from mean-per-candidate timings."""
    if mean_candidate_total_time_seconds is None:
        return None
    run_count = int(candidate_run_count)
    if run_count <= 0:
        run_count = int(n_evaluations)
    if run_count <= 0:
        return None
    return float(mean_candidate_total_time_seconds) * float(run_count)


def _algorithm_overhead_time_seconds(
    *,
    calibration_time_seconds: float | None,
    estimated_candidate_runtime_seconds: float | None,
) -> float | None:
    """Estimate method overhead not spent inside candidate runtime segments."""
    if calibration_time_seconds is None or estimated_candidate_runtime_seconds is None:
        return None
    raw = float(calibration_time_seconds) - float(estimated_candidate_runtime_seconds)
    if raw < 0.0 and abs(raw) < 1.0e-9:
        return 0.0
    return max(0.0, raw)


def _assess_method_result(
    *,
    definition: TwinCalibrationCaseDefinition,
    method_profile: CalibrationMethodProfile,
    method_instance_name: str,
    repeat_index: int,
    seed: int | None,
    effective_method_kwargs: dict[str, Any],
    requested_evaluation_budget: int | None,
    summary: dict[str, Any],
) -> TwinMethodBenchmarkResult:
    """Convert one launcher summary to benchmark metrics."""
    truth_params = {
        str(name): float(value) for name, value in definition.truth_params.items()
    }
    abs_tolerances = {
        str(name): float(value)
        for name, value in definition.parameter_abs_tolerances.items()
    }
    params_best = {
        str(name): float(value)
        for name, value in dict(summary.get("params_best", {})).items()
    }
    param_abs_error = _param_abs_error(
        truth_params=truth_params,
        params_best=params_best,
    )
    recovered_truth = bool(
        summary.get("status") == "calibrated"
        and summary.get("cost_best") is not None
        and math.isfinite(float(summary["cost_best"]))
        and all(
            math.isfinite(param_abs_error[name])
            and param_abs_error[name] <= abs_tolerances[name]
            for name in truth_params
        )
    )

    distribution_summary = summary.get("model_distribution")
    distribution_path = None
    if isinstance(distribution_summary, dict) and distribution_summary.get("path"):
        distribution_path = Path(str(distribution_summary["path"]))
    iteration_history_path = calibration_root = Path(str(summary["calibration_root"]))
    iteration_history_path = calibration_root / "iteration_history.jsonl"
    if not iteration_history_path.is_file():
        iteration_history_path = None
    result_payload = {}
    result_path = (
        None
        if summary.get("result_path") is None
        else Path(str(summary["result_path"]))
    )
    if result_path is not None and result_path.is_file():
        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    calibration_time_seconds = None
    time_per_evaluation_seconds = None
    session_prepare_time_seconds = None
    mean_candidate_total_time_seconds = None
    mean_candidate_preparation_time_seconds = None
    mean_candidate_simulation_time_seconds = None
    mean_candidate_actualize_time_seconds = None
    mean_candidate_launcher_prepare_time_seconds = None
    mean_candidate_runtime_patch_time_seconds = None
    mean_candidate_output_selection_time_seconds = None
    mean_candidate_objective_build_time_seconds = None
    mean_candidate_objective_compute_time_seconds = None
    mean_candidate_objective_time_seconds = None
    block_raw_cost_best: dict[str, float] = {}
    block_normalized_cost_best: dict[str, float] = {}
    block_reference_scale: dict[str, float] = {}
    block_n_values: dict[str, int] = {}
    metadata = result_payload.get("metadata", {})
    if isinstance(metadata, dict) and metadata.get("calibration_time_seconds") is not None:
        calibration_time_seconds = float(metadata["calibration_time_seconds"])
    if isinstance(metadata, dict) and metadata.get("session_prepare_time_seconds") is not None:
        session_prepare_time_seconds = float(metadata["session_prepare_time_seconds"])
    candidate_timing_summary = {}
    if isinstance(metadata, dict):
        raw_candidate_timing_summary = metadata.get("candidate_timing_summary", {})
        if isinstance(raw_candidate_timing_summary, dict):
            candidate_timing_summary = raw_candidate_timing_summary
    if isinstance(candidate_timing_summary.get("total_time_seconds"), dict):
        raw_value = candidate_timing_summary["total_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_total_time_seconds = float(raw_value)
    if isinstance(candidate_timing_summary.get("prepare_time_seconds"), dict):
        raw_value = candidate_timing_summary["prepare_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_preparation_time_seconds = float(raw_value)
    if isinstance(candidate_timing_summary.get("simulation_time_seconds"), dict):
        raw_value = candidate_timing_summary["simulation_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_simulation_time_seconds = float(raw_value)
    if isinstance(candidate_timing_summary.get("actualize_time_seconds"), dict):
        raw_value = candidate_timing_summary["actualize_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_actualize_time_seconds = float(raw_value)
    if isinstance(candidate_timing_summary.get("launcher_prepare_time_seconds"), dict):
        raw_value = candidate_timing_summary["launcher_prepare_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_launcher_prepare_time_seconds = float(raw_value)
    if isinstance(candidate_timing_summary.get("runtime_patch_time_seconds"), dict):
        raw_value = candidate_timing_summary["runtime_patch_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_runtime_patch_time_seconds = float(raw_value)
    if isinstance(candidate_timing_summary.get("output_selection_time_seconds"), dict):
        raw_value = candidate_timing_summary["output_selection_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_output_selection_time_seconds = float(raw_value)
    if isinstance(candidate_timing_summary.get("objective_build_time_seconds"), dict):
        raw_value = candidate_timing_summary["objective_build_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_objective_build_time_seconds = float(raw_value)
    if isinstance(candidate_timing_summary.get("objective_compute_time_seconds"), dict):
        raw_value = candidate_timing_summary["objective_compute_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_objective_compute_time_seconds = float(raw_value)
    if isinstance(candidate_timing_summary.get("objective_time_seconds"), dict):
        raw_value = candidate_timing_summary["objective_time_seconds"].get("mean")
        if raw_value is not None:
            mean_candidate_objective_time_seconds = float(raw_value)
    if calibration_time_seconds is not None and int(summary.get("n_evaluations", 0)) > 0:
        time_per_evaluation_seconds = (
            float(calibration_time_seconds) / float(int(summary["n_evaluations"]))
        )
    objective_evaluation = metadata.get("objective_evaluation", {})
    if isinstance(objective_evaluation, dict):
        blocks = objective_evaluation.get("blocks", [])
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict) or block.get("name") is None:
                    continue
                block_name = str(block["name"])
                if block.get("raw_cost") is not None:
                    block_raw_cost_best[block_name] = float(block["raw_cost"])
                if block.get("normalized_cost") is not None:
                    block_normalized_cost_best[block_name] = float(
                        block["normalized_cost"]
                    )
                if block.get("reference_scale") is not None:
                    block_reference_scale[block_name] = float(block["reference_scale"])
                if block.get("n_values") is not None:
                    block_n_values[block_name] = int(block["n_values"])
    failed_iteration_count = 0
    candidate_run_count = 0
    objective_cache_hit_count = 0
    objective_cache_hit_rate = None
    calibration_report = summary.get("calibration_report")
    if isinstance(calibration_report, dict) and calibration_report.get("failed_count") is not None:
        failed_iteration_count = int(calibration_report["failed_count"])
    if isinstance(calibration_report, dict):
        runtime_report = calibration_report.get("runtime", {})
        if isinstance(runtime_report, dict):
            if runtime_report.get("candidate_run_count") is not None:
                candidate_run_count = int(runtime_report["candidate_run_count"])
            if runtime_report.get("objective_cache_hit_count") is not None:
                objective_cache_hit_count = int(runtime_report["objective_cache_hit_count"])
            if candidate_run_count > 0:
                objective_cache_hit_rate = (
                    float(objective_cache_hit_count) / float(candidate_run_count)
                )
    estimated_candidate_runtime_seconds = _estimate_candidate_runtime_seconds(
        mean_candidate_total_time_seconds=mean_candidate_total_time_seconds,
        candidate_run_count=candidate_run_count,
        n_evaluations=int(summary.get("n_evaluations", 0)),
    )
    algorithm_overhead_time_seconds = _algorithm_overhead_time_seconds(
        calibration_time_seconds=calibration_time_seconds,
        estimated_candidate_runtime_seconds=estimated_candidate_runtime_seconds,
    )
    distribution_sample_count, truth_in_distribution, min_distribution_error = (
        _distribution_truth_metrics(
            model_distribution_path=distribution_path,
            truth_params=truth_params,
            abs_tolerances=abs_tolerances,
        )
    )
    success_metric = str(method_profile.success_metric).strip().lower()
    if success_metric == "best_fit":
        meets_success_target = recovered_truth
    elif success_metric == "distribution":
        meets_success_target = truth_in_distribution is True
    elif success_metric == "best_fit_or_distribution":
        meets_success_target = recovered_truth or truth_in_distribution is True
    else:
        raise ValueError(
            f"Unsupported calibration benchmark success_metric '{method_profile.success_metric}'."
        )
    return TwinMethodBenchmarkResult(
        method_name=method_profile.name,
        method_instance_name=method_instance_name,
        success_metric=success_metric,
        effective_method_kwargs={
            str(name): value for name, value in effective_method_kwargs.items()
        },
        requested_evaluation_budget=requested_evaluation_budget,
        calibration_id=str(summary["calibration_id"]),
        calibration_root=calibration_root,
        result_path=result_path,
        cost_best=(
            None if summary.get("cost_best") is None else float(summary["cost_best"])
        ),
        iteration_count=int(summary.get("iteration_count", 0)),
        n_evaluations=int(summary.get("n_evaluations", 0)),
        params_best=params_best,
        param_abs_error=param_abs_error,
        recovered_truth=recovered_truth,
        repeat_index=int(repeat_index),
        seed=seed,
        calibration_time_seconds=calibration_time_seconds,
        time_per_evaluation_seconds=time_per_evaluation_seconds,
        session_prepare_time_seconds=session_prepare_time_seconds,
        estimated_candidate_runtime_seconds=estimated_candidate_runtime_seconds,
        algorithm_overhead_time_seconds=algorithm_overhead_time_seconds,
        mean_candidate_total_time_seconds=mean_candidate_total_time_seconds,
        mean_candidate_preparation_time_seconds=(
            mean_candidate_preparation_time_seconds
        ),
        mean_candidate_simulation_time_seconds=(
            mean_candidate_simulation_time_seconds
        ),
        mean_candidate_actualize_time_seconds=(
            mean_candidate_actualize_time_seconds
        ),
        mean_candidate_launcher_prepare_time_seconds=(
            mean_candidate_launcher_prepare_time_seconds
        ),
        mean_candidate_runtime_patch_time_seconds=(
            mean_candidate_runtime_patch_time_seconds
        ),
        mean_candidate_output_selection_time_seconds=(
            mean_candidate_output_selection_time_seconds
        ),
        mean_candidate_objective_build_time_seconds=(
            mean_candidate_objective_build_time_seconds
        ),
        mean_candidate_objective_compute_time_seconds=(
            mean_candidate_objective_compute_time_seconds
        ),
        mean_candidate_objective_time_seconds=(
            mean_candidate_objective_time_seconds
        ),
        failed_iteration_count=failed_iteration_count,
        meets_success_target=bool(meets_success_target),
        candidate_run_count=candidate_run_count,
        objective_cache_hit_count=objective_cache_hit_count,
        objective_cache_hit_rate=objective_cache_hit_rate,
        block_raw_cost_best=block_raw_cost_best,
        block_normalized_cost_best=block_normalized_cost_best,
        block_reference_scale=block_reference_scale,
        block_n_values=block_n_values,
        iteration_history_path=iteration_history_path,
        model_distribution_path=distribution_path,
        model_distribution_sample_count=int(distribution_sample_count),
        truth_in_distribution=truth_in_distribution,
        truth_distribution_min_abs_error={
            str(name): float(value)
            for name, value in min_distribution_error.items()
            if value is not None
        },
    )


def run_twin_benchmark_case(
    definition: TwinCalibrationCaseDefinition,
    *,
    caller_file: str | Path,
    launcher_factory: Any = None,
    method_names: tuple[str, ...] | None = None,
    evaluation_budget: int | None = None,
    artifact_retention: str | None = None,
    case_figures: bool | None = None,
    figure_format: str = "png",
) -> TwinCalibrationBenchmarkResult:
    """Run one same-solver twin benchmark and assess each configured method."""
    del caller_file
    if definition.build_simulation_config is None:
        raise ValueError("Twin calibration case is missing build_simulation_config")
    if definition.build_calibration_payload is None:
        raise ValueError("Twin calibration case is missing build_calibration_payload")

    benchmark_root = _resolve_twin_benchmark_root(definition)
    benchmark_root.mkdir(parents=True, exist_ok=True)
    simulation_config_path = benchmark_root / "simulation.toml"
    definition.build_simulation_config(
        simulation_config_path,
        benchmark_root / "project",
    )
    truth_builder = definition.build_truth_simulation_config
    if truth_builder is None:
        truth_simulation_config_path = simulation_config_path
    else:
        truth_simulation_config_path = benchmark_root / "truth_simulation.toml"
        truth_builder(
            truth_simulation_config_path,
            benchmark_root / "project_truth",
        )
    synthesized_observations = synthesize_truth_observations(
        definition=definition,
        truth_simulation_config_path=truth_simulation_config_path,
        benchmark_root=benchmark_root,
        launcher_factory=launcher_factory,
    )
    observations_truth = synthesized_observations["truth"]
    observations_used = synthesized_observations["used"]

    selected_profiles = tuple(definition.method_profiles)
    if method_names is not None:
        requested = {str(name).strip().lower() for name in method_names}
        selected_profiles = tuple(
            profile
            for profile in selected_profiles
            if str(profile.name).strip().lower() in requested
        )
    if not selected_profiles:
        raise ValueError(
            f"No method profile selected for benchmark '{definition.case_id}'."
        )

    configuration_figure = None
    generate_case_figures = (
        definition.generate_case_figures
        if case_figures is None
        else bool(case_figures)
    )
    retained_mode = (
        str(definition.artifact_retention)
        if artifact_retention is None
        else str(artifact_retention)
    )
    if generate_case_figures:
        from validation_cases.calibration.plotting import (
            write_case_configuration_figure,
        )

        configuration_figure = write_case_configuration_figure(
            benchmark_root=benchmark_root,
            definition=definition,
            simulation_config_path=simulation_config_path,
            truth_simulation_config_path=truth_simulation_config_path,
            artifact_retention=retained_mode,
            figure_format=figure_format,
        )

    method_results: list[TwinMethodBenchmarkResult] = []
    for method_run in _iter_selected_method_runs(selected_profiles):
        method_profile = method_run["profile"]
        effective_profile = _apply_evaluation_budget(
            method_run["effective_profile"],
            n_parameters=len(definition.truth_params),
            evaluation_budget=evaluation_budget,
        )
        method_instance_name = str(method_run["instance_name"])
        repeat_index = int(method_run["repeat_index"])
        seed = method_run["seed"]
        calibration_id = _compact_calibration_id(
            definition,
            method_instance_name,
        )
        calibration_path = benchmark_root / f"calibration_{method_instance_name}.toml"
        payload = definition.build_calibration_payload(
            simulation_config_path.name,
            calibration_id,
            observations_used,
            effective_profile,
        )
        _write_toml(calibration_path, payload)
        summary = ModelCalibrationLauncher(calibration_path).calibrate(
            launcher_factory=launcher_factory,
        )
        assessed_result = _assess_method_result(
            definition=definition,
            method_profile=method_profile,
            method_instance_name=method_instance_name,
            repeat_index=repeat_index,
            seed=seed,
            effective_method_kwargs=dict(effective_profile.method_kwargs),
            requested_evaluation_budget=evaluation_budget,
            summary=summary,
        )
        if generate_case_figures:
            from validation_cases.calibration.plotting import write_case_method_figures

            figure_paths = write_case_method_figures(
                benchmark_root=benchmark_root,
                definition=definition,
                result=assessed_result,
                figure_format=figure_format,
            )
            assessed_result = replace(
                assessed_result,
                objective_trace_figure=figure_paths.get("objective_trace"),
                objective_landscape_figure=figure_paths.get("objective_landscape"),
                posterior_distribution_figure=figure_paths.get(
                    "posterior_distribution"
                ),
            )
        method_results.append(assessed_result)

    pruned_artifacts = _prune_benchmark_artifacts(
        benchmark_root=benchmark_root,
        retention=retained_mode,
    )

    benchmark = TwinCalibrationBenchmarkResult(
        definition=definition,
        benchmark_root=benchmark_root,
        simulation_config_path=simulation_config_path,
        truth_simulation_config_path=truth_simulation_config_path,
        observations_truth=observations_truth,
        observations_used=observations_used,
        method_results=tuple(method_results),
        summary_path=benchmark_root / "benchmark_summary.json",
        artifact_retention=retained_mode,
        configuration_figure=configuration_figure,
        pruned_artifacts=pruned_artifacts,
    )
    benchmark.summary_path.write_text(
        json.dumps(benchmark.to_mapping(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return benchmark
