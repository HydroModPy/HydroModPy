"""Contracts shared by calibration inverse-validation cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _json_ready_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return one JSON-safe shallow mapping."""
    normalized: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            normalized[str(key)] = value
        elif isinstance(value, (list, tuple, dict)):
            normalized[str(key)] = value
        else:
            normalized[str(key)] = str(value)
    return normalized


@dataclass(frozen=True, slots=True)
class CalibrationMethodProfile:
    """Method configuration used in one standardized inverse benchmark."""

    name: str
    method_kwargs: Mapping[str, Any] = field(default_factory=dict)
    persist_model_distribution: bool = False
    repeat_seeds: tuple[int, ...] = ()
    seed_kwarg_name: str = "seed"
    success_metric: str = "best_fit"


@dataclass(frozen=True, slots=True)
class ObservationNoiseSpec:
    """Optional synthetic-observation perturbation applied after the truth run."""

    absolute_sigma_by_output: Mapping[str, float] = field(default_factory=dict)
    relative_sigma_by_output: Mapping[str, float] = field(default_factory=dict)
    seed: int = 0


def build_payload(
    definition: TwinCalibrationCaseDefinition,
    *,
    simulation_config_name: str,
    calibration_id: str,
    observed_values: Mapping[str, tuple[float, ...]],
    method_profile: CalibrationMethodProfile,
) -> dict[str, Any]:
    """Build one ``[calibration]`` payload for a twin definition.

    Emits the enriched schema consumed by
    :class:`hydromodpy.calibration.config.CalibrationConfig`:

    - ``[calibration]`` carries top-level knobs (``method``, ``max_iter``,
      ``seed``, ``save_runs`` defaulting to ``"none"``).
    - ``[calibration.parameters.<name>]`` collects bounds, target,
      transform, and mode.
    - ``[calibration.outputs.<name>]`` injects ``observed_values`` from the
      truth synthesis.
    - ``[calibration.objective_blocks]`` lists the weighted blocks.
    - ``[calibration.optimizer_kwargs]`` forwards method kwargs.

    The returned dict is deep-mergeable with a base simulation TOML via
    ``base_config = ...`` so the caller can write it next to the
    simulation config and load it through :class:`hydromodpy.Project`.
    """
    if definition.parameter_targets is None:
        raise ValueError(
            f"build_payload requires definition.parameter_targets for {definition.case_id!r}; "
            "add a `parameter_targets` mapping to the case definition."
        )
    if definition.output_specs is None:
        raise ValueError(
            f"build_payload requires definition.output_specs for {definition.case_id!r}; "
            "add an `output_specs` mapping to the case definition."
        )
    if definition.objective_block_specs is None:
        raise ValueError(
            f"build_payload requires definition.objective_block_specs for {definition.case_id!r}; "
            "add an `objective_block_specs` tuple to the case definition."
        )

    parameters: dict[str, dict[str, Any]] = {}
    for name, target in definition.parameter_targets.items():
        low, high = definition.bounds[name]
        parameter_decl: dict[str, Any] = {
            "bounds": [float(low), float(high)],
            "target": str(target.target),
            "mode": str(target.mode),
        }
        if target.transform is not None:
            parameter_decl["transform"] = str(target.transform)
        parameters[str(name)] = parameter_decl

    outputs: dict[str, dict[str, Any]] = {}
    for name, spec in definition.output_specs.items():
        observed = observed_values.get(name)
        output_decl: dict[str, Any] = {
            "variable": str(spec.variable),
            "support": str(spec.support),
        }
        if spec.x is not None:
            output_decl["x"] = float(spec.x)
        if spec.y is not None:
            output_decl["y"] = float(spec.y)
        if spec.boundary_id is not None:
            output_decl["boundary_id"] = str(spec.boundary_id)
        if spec.time is not None:
            output_decl["time"] = spec.time
        if spec.reducer is not None:
            output_decl["reducer"] = str(spec.reducer)
        if observed is not None:
            output_decl["observed_values"] = [float(value) for value in observed]
        outputs[str(name)] = output_decl

    objective_blocks: list[dict[str, Any]] = []
    for block in definition.objective_block_specs:
        objective_blocks.append(
            {
                "name": str(block.name),
                "metric": str(block.metric),
                "weight": float(block.weight),
                "uses_outputs": [str(item) for item in block.uses_outputs],
                "normalize_cost": bool(block.normalize_cost),
            }
        )

    method_kwargs = dict(method_profile.method_kwargs)
    # Hoist seed to the top-level [calibration].seed knob so build_optimizer
    # receives it once via its dedicated kwarg rather than twice (the CLI
    # forwards both cfg.seed and **optimizer_kwargs which would clash).
    seed_value = method_kwargs.pop(method_profile.seed_kwarg_name, None)
    n_parameters = max(1, len(parameters))
    max_iter = _resolve_max_iter_from_kwargs(
        method_profile.name,
        method_kwargs,
        n_parameters=n_parameters,
    )
    if str(method_profile.name).strip().lower() == "random_search":
        method_kwargs.pop("max_iter", None)

    calibration_section: dict[str, Any] = {
        "method": str(method_profile.name),
        "max_iter": int(max_iter),
        "save_runs": "none",
        "use_cache": False,
        "parameters": parameters,
        "outputs": outputs,
        "objective_blocks": objective_blocks,
        "optimizer_kwargs": method_kwargs,
        "persist_iteration_detail": "full",
        "persist_model_distribution": bool(method_profile.persist_model_distribution),
    }
    if seed_value is not None:
        try:
            calibration_section["seed"] = int(seed_value)
        except (TypeError, ValueError):
            pass

    return {
        "_calibration_id": str(calibration_id),
        "_simulation_config": str(simulation_config_name),
        "calibration": calibration_section,
    }


def _resolve_max_iter_from_kwargs(
    method: str,
    kwargs: Mapping[str, Any],
    *,
    n_parameters: int = 1,
) -> int:
    """Estimate a reasonable ``max_iter`` upper bound from method kwargs."""
    method_key = str(method).strip().lower()
    if method_key == "grid":
        points_per_dim = int(kwargs.get("points_per_dim", 5))
        return max(1, points_per_dim ** max(1, int(n_parameters)))
    if method_key == "random_search":
        return max(1, int(kwargs.get("max_iter", 20)))
    if method_key == "cma_es":
        return max(1, int(kwargs.get("max_evaluations", 30)))
    if method_key == "scipy_nelder_mead":
        return max(1, int(kwargs.get("maxiter", 30)))
    if method_key == "gp_mapping":
        n_init = int(kwargs.get("n_init", 8))
        n_refine = int(kwargs.get("n_refine", 3))
        batch = int(kwargs.get("batch_size", 1))
        return max(1, n_init + n_refine * batch)
    if method_key == "da_mh_gp":
        return max(1, int(kwargs.get("max_iter", 32)))
    return max(1, int(kwargs.get("max_iter", kwargs.get("max_evaluations", 50))))


@dataclass(frozen=True, slots=True)
class TwinParameterTarget:
    """One v1 parameter declaration shared by twin cases."""

    target: str
    mode: str = "replace"
    transform: str | None = None


@dataclass(frozen=True, slots=True)
class TwinOutputSpec:
    """One v1 output declaration shared by twin cases."""

    variable: str
    support: str = "point"
    x: float | None = None
    y: float | None = None
    boundary_id: str | None = None
    time: str | list[str] | None = "all"
    reducer: str | None = None


@dataclass(frozen=True, slots=True)
class TwinObjectiveBlockSpec:
    """One v1 objective block declaration shared by twin cases."""

    name: str
    metric: str = "rmse"
    weight: float = 1.0
    uses_outputs: tuple[str, ...] = ()
    normalize_cost: bool = True


@dataclass(frozen=True, slots=True)
class TwinCalibrationCaseDefinition:
    """Definition of one same-solver twin calibration experiment."""

    case_id: str
    solver_name: str
    regime: str
    description: str
    truth_params: Mapping[str, float]
    bounds: Mapping[str, tuple[float, float]]
    parameter_abs_tolerances: Mapping[str, float]
    output_names: tuple[str, ...]
    method_profiles: tuple[CalibrationMethodProfile, ...]
    fast: bool = False
    observation_noise: ObservationNoiseSpec | None = None
    perturbation_description: str | None = None
    artifact_retention: str = "minimal"
    generate_case_figures: bool = True
    reference_objective_sample_count: int | None = None
    reference_objective_sampling: str = "sobol"
    reference_objective_seed: int = 91
    build_simulation_config: Callable[[Path, Path], None] | None = None
    build_truth_simulation_config: Callable[[Path, Path], None] | None = None
    parameter_targets: Mapping[str, TwinParameterTarget] | None = None
    output_specs: Mapping[str, TwinOutputSpec] | None = None
    objective_block_specs: tuple[TwinObjectiveBlockSpec, ...] | None = None


@dataclass(frozen=True, slots=True)
class TwinMethodBenchmarkResult:
    """Assessed result of one calibration method on one twin benchmark."""

    method_name: str
    method_instance_name: str
    success_metric: str
    effective_method_kwargs: dict[str, Any]
    requested_evaluation_budget: int | None
    calibration_id: str
    calibration_root: Path
    result_path: Path | None
    cost_best: float | None
    iteration_count: int
    n_evaluations: int
    params_best: dict[str, float]
    param_abs_error: dict[str, float]
    recovered_truth: bool
    repeat_index: int = 1
    seed: int | None = None
    calibration_time_seconds: float | None = None
    time_per_evaluation_seconds: float | None = None
    session_prepare_time_seconds: float | None = None
    estimated_candidate_runtime_seconds: float | None = None
    algorithm_overhead_time_seconds: float | None = None
    mean_candidate_total_time_seconds: float | None = None
    mean_candidate_preparation_time_seconds: float | None = None
    mean_candidate_simulation_time_seconds: float | None = None
    mean_candidate_actualize_time_seconds: float | None = None
    mean_candidate_launcher_prepare_time_seconds: float | None = None
    mean_candidate_runtime_patch_time_seconds: float | None = None
    mean_candidate_output_selection_time_seconds: float | None = None
    mean_candidate_objective_build_time_seconds: float | None = None
    mean_candidate_objective_compute_time_seconds: float | None = None
    mean_candidate_objective_time_seconds: float | None = None
    failed_iteration_count: int = 0
    meets_success_target: bool = False
    candidate_run_count: int = 0
    objective_cache_hit_count: int = 0
    objective_cache_hit_rate: float | None = None
    block_raw_cost_best: dict[str, float] = field(default_factory=dict)
    block_normalized_cost_best: dict[str, float] = field(default_factory=dict)
    block_reference_scale: dict[str, float] = field(default_factory=dict)
    block_n_values: dict[str, int] = field(default_factory=dict)
    iteration_history_path: Path | None = None
    model_distribution_path: Path | None = None
    model_distribution_sample_count: int = 0
    truth_in_distribution: bool | None = None
    truth_distribution_min_abs_error: dict[str, float] = field(default_factory=dict)
    objective_trace_figure: Path | None = None
    objective_landscape_figure: Path | None = None
    posterior_distribution_figure: Path | None = None

    def to_mapping(self) -> dict[str, Any]:
        """Return one JSON-friendly representation."""
        return {
            "method_name": self.method_name,
            "method_instance_name": self.method_instance_name,
            "success_metric": self.success_metric,
            "effective_method_kwargs": _json_ready_mapping(self.effective_method_kwargs),
            "requested_evaluation_budget": self.requested_evaluation_budget,
            "calibration_id": self.calibration_id,
            "calibration_root": str(self.calibration_root),
            "result_path": None if self.result_path is None else str(self.result_path),
            "cost_best": self.cost_best,
            "iteration_count": int(self.iteration_count),
            "n_evaluations": int(self.n_evaluations),
            "repeat_index": int(self.repeat_index),
            "seed": self.seed,
            "calibration_time_seconds": self.calibration_time_seconds,
            "time_per_evaluation_seconds": self.time_per_evaluation_seconds,
            "session_prepare_time_seconds": self.session_prepare_time_seconds,
            "estimated_candidate_runtime_seconds": (self.estimated_candidate_runtime_seconds),
            "algorithm_overhead_time_seconds": (self.algorithm_overhead_time_seconds),
            "mean_candidate_total_time_seconds": self.mean_candidate_total_time_seconds,
            "mean_candidate_preparation_time_seconds": (
                self.mean_candidate_preparation_time_seconds
            ),
            "mean_candidate_simulation_time_seconds": (self.mean_candidate_simulation_time_seconds),
            "mean_candidate_actualize_time_seconds": (self.mean_candidate_actualize_time_seconds),
            "mean_candidate_launcher_prepare_time_seconds": (
                self.mean_candidate_launcher_prepare_time_seconds
            ),
            "mean_candidate_runtime_patch_time_seconds": (
                self.mean_candidate_runtime_patch_time_seconds
            ),
            "mean_candidate_output_selection_time_seconds": (
                self.mean_candidate_output_selection_time_seconds
            ),
            "mean_candidate_objective_build_time_seconds": (
                self.mean_candidate_objective_build_time_seconds
            ),
            "mean_candidate_objective_compute_time_seconds": (
                self.mean_candidate_objective_compute_time_seconds
            ),
            "mean_candidate_objective_time_seconds": (self.mean_candidate_objective_time_seconds),
            "failed_iteration_count": int(self.failed_iteration_count),
            "meets_success_target": bool(self.meets_success_target),
            "candidate_run_count": int(self.candidate_run_count),
            "objective_cache_hit_count": int(self.objective_cache_hit_count),
            "objective_cache_hit_rate": self.objective_cache_hit_rate,
            "block_raw_cost_best": {
                str(name): float(value) for name, value in self.block_raw_cost_best.items()
            },
            "block_normalized_cost_best": {
                str(name): float(value) for name, value in self.block_normalized_cost_best.items()
            },
            "block_reference_scale": {
                str(name): float(value) for name, value in self.block_reference_scale.items()
            },
            "block_n_values": {
                str(name): int(value) for name, value in self.block_n_values.items()
            },
            "iteration_history_path": (
                None if self.iteration_history_path is None else str(self.iteration_history_path)
            ),
            "params_best": {str(name): float(value) for name, value in self.params_best.items()},
            "param_abs_error": {
                str(name): float(value) for name, value in self.param_abs_error.items()
            },
            "recovered_truth": bool(self.recovered_truth),
            "model_distribution_path": (
                None if self.model_distribution_path is None else str(self.model_distribution_path)
            ),
            "model_distribution_sample_count": int(self.model_distribution_sample_count),
            "truth_in_distribution": self.truth_in_distribution,
            "truth_distribution_min_abs_error": {
                str(name): float(value)
                for name, value in self.truth_distribution_min_abs_error.items()
            },
            "objective_trace_figure": (
                None if self.objective_trace_figure is None else str(self.objective_trace_figure)
            ),
            "objective_landscape_figure": (
                None
                if self.objective_landscape_figure is None
                else str(self.objective_landscape_figure)
            ),
            "posterior_distribution_figure": (
                None
                if self.posterior_distribution_figure is None
                else str(self.posterior_distribution_figure)
            ),
        }


@dataclass(frozen=True, slots=True)
class TwinCalibrationBenchmarkResult:
    """Full benchmark output for one standardized twin-experiment case."""

    definition: TwinCalibrationCaseDefinition
    benchmark_root: Path
    simulation_config_path: Path
    truth_simulation_config_path: Path
    observations_truth: dict[str, tuple[float, ...]]
    observations_used: dict[str, tuple[float, ...]]
    method_results: tuple[TwinMethodBenchmarkResult, ...]
    summary_path: Path
    artifact_retention: str = "minimal"
    configuration_figure: Path | None = None
    reference_objective_path: Path | None = None
    pruned_artifacts: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        """Return one JSON-friendly summary."""
        return {
            "role": "calibration_twin_benchmark",
            "case_id": self.definition.case_id,
            "solver_name": self.definition.solver_name,
            "regime": self.definition.regime,
            "description": self.definition.description,
            "perturbation_description": self.definition.perturbation_description,
            "artifact_retention": str(self.artifact_retention),
            "benchmark_root": str(self.benchmark_root),
            "simulation_config_path": str(self.simulation_config_path),
            "truth_simulation_config_path": str(self.truth_simulation_config_path),
            "configuration_figure": (
                None if self.configuration_figure is None else str(self.configuration_figure)
            ),
            "reference_objective_path": (
                None
                if self.reference_objective_path is None
                else str(self.reference_objective_path)
            ),
            "pruned_artifacts": [str(item) for item in self.pruned_artifacts],
            "truth_params": {
                str(name): float(value) for name, value in self.definition.truth_params.items()
            },
            "parameter_abs_tolerances": {
                str(name): float(value)
                for name, value in self.definition.parameter_abs_tolerances.items()
            },
            "observations_truth": {
                str(name): [float(value) for value in values]
                for name, values in self.observations_truth.items()
            },
            "observations_used": {
                str(name): [float(value) for value in values]
                for name, values in self.observations_used.items()
            },
            "observation_noise": (
                None
                if self.definition.observation_noise is None
                else {
                    "absolute_sigma_by_output": {
                        str(name): float(value)
                        for name, value in self.definition.observation_noise.absolute_sigma_by_output.items()
                    },
                    "relative_sigma_by_output": {
                        str(name): float(value)
                        for name, value in self.definition.observation_noise.relative_sigma_by_output.items()
                    },
                    "seed": int(self.definition.observation_noise.seed),
                }
            ),
            "method_results": [item.to_mapping() for item in self.method_results],
        }
