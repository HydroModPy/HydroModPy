"""Runtime helpers for calibration same-solver twin benchmarks."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from launchers import HydroModPyLauncher
from launchers.model_calibration.launcher import ModelCalibrationLauncher
from launchers.model_calibration.runtime import (
    actualize_candidate,
    execute_candidate_run,
    select_candidate_outputs,
)
from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
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
    return (
        f"{_compact_case_code(definition)}_"
        f"{_compact_method_code(method_name)}"
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


def _placeholder_observations(
    definition: TwinCalibrationCaseDefinition,
) -> dict[str, tuple[float, ...]]:
    """Return one minimal observed-value mapping accepted by config parsing."""
    return {str(name): (0.0,) for name in definition.output_names}


def synthesize_truth_observations(
    *,
    definition: TwinCalibrationCaseDefinition,
    simulation_config_path: Path,
    benchmark_root: Path,
    launcher_factory: Any = HydroModPyLauncher,
) -> dict[str, tuple[float, ...]]:
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
        simulation_config_path.name,
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
    observations = _normalize_selected_outputs(selected)
    truth_output_path = benchmark_root / "truth_observations.json"
    truth_output_path.write_text(
        json.dumps(
            {
                "role": "synthetic_truth_observations",
                "case_id": definition.case_id,
                "solver_name": definition.solver_name,
                "truth_params": {
                    str(name): float(value)
                    for name, value in definition.truth_params.items()
                },
                "observations": {
                    str(name): [float(value) for value in values]
                    for name, values in observations.items()
                },
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return observations


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


def _assess_method_result(
    *,
    definition: TwinCalibrationCaseDefinition,
    method_profile: CalibrationMethodProfile,
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
    distribution_sample_count, truth_in_distribution, min_distribution_error = (
        _distribution_truth_metrics(
            model_distribution_path=distribution_path,
            truth_params=truth_params,
            abs_tolerances=abs_tolerances,
        )
    )
    return TwinMethodBenchmarkResult(
        method_name=method_profile.name,
        calibration_id=str(summary["calibration_id"]),
        calibration_root=Path(str(summary["calibration_root"])),
        result_path=(
            None
            if summary.get("result_path") is None
            else Path(str(summary["result_path"]))
        ),
        cost_best=(
            None if summary.get("cost_best") is None else float(summary["cost_best"])
        ),
        iteration_count=int(summary.get("iteration_count", 0)),
        n_evaluations=int(summary.get("n_evaluations", 0)),
        params_best=params_best,
        param_abs_error=param_abs_error,
        recovered_truth=recovered_truth,
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
    launcher_factory: Any = HydroModPyLauncher,
    method_names: tuple[str, ...] | None = None,
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
    observations_truth = synthesize_truth_observations(
        definition=definition,
        simulation_config_path=simulation_config_path,
        benchmark_root=benchmark_root,
        launcher_factory=launcher_factory,
    )

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

    method_results: list[TwinMethodBenchmarkResult] = []
    for method_profile in selected_profiles:
        calibration_id = _compact_calibration_id(
            definition,
            method_profile.name,
        )
        calibration_path = benchmark_root / f"calibration_{method_profile.name}.toml"
        payload = definition.build_calibration_payload(
            simulation_config_path.name,
            calibration_id,
            observations_truth,
            method_profile,
        )
        _write_toml(calibration_path, payload)
        summary = ModelCalibrationLauncher(calibration_path).calibrate(
            launcher_factory=launcher_factory,
        )
        method_results.append(
            _assess_method_result(
                definition=definition,
                method_profile=method_profile,
                summary=summary,
            )
        )

    benchmark = TwinCalibrationBenchmarkResult(
        definition=definition,
        benchmark_root=benchmark_root,
        simulation_config_path=simulation_config_path,
        observations_truth=observations_truth,
        method_results=tuple(method_results),
        summary_path=benchmark_root / "benchmark_summary.json",
    )
    benchmark.summary_path.write_text(
        json.dumps(benchmark.to_mapping(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return benchmark
