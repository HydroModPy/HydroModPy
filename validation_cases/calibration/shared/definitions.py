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
    build_simulation_config: Callable[[Path, Path], None] | None = None
    build_truth_simulation_config: Callable[[Path, Path], None] | None = None
    build_calibration_payload: (
        Callable[
            [str, str, Mapping[str, tuple[float, ...]], CalibrationMethodProfile],
            dict[str, Any],
        ]
        | None
    ) = None


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
    failed_iteration_count: int = 0
    meets_success_target: bool = False
    candidate_run_count: int = 0
    objective_cache_hit_count: int = 0
    objective_cache_hit_rate: float | None = None
    block_raw_cost_best: dict[str, float] = field(default_factory=dict)
    block_normalized_cost_best: dict[str, float] = field(default_factory=dict)
    block_reference_scale: dict[str, float] = field(default_factory=dict)
    block_n_values: dict[str, int] = field(default_factory=dict)
    model_distribution_path: Path | None = None
    model_distribution_sample_count: int = 0
    truth_in_distribution: bool | None = None
    truth_distribution_min_abs_error: dict[str, float] = field(default_factory=dict)

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
            "failed_iteration_count": int(self.failed_iteration_count),
            "meets_success_target": bool(self.meets_success_target),
            "candidate_run_count": int(self.candidate_run_count),
            "objective_cache_hit_count": int(self.objective_cache_hit_count),
            "objective_cache_hit_rate": self.objective_cache_hit_rate,
            "block_raw_cost_best": {
                str(name): float(value) for name, value in self.block_raw_cost_best.items()
            },
            "block_normalized_cost_best": {
                str(name): float(value)
                for name, value in self.block_normalized_cost_best.items()
            },
            "block_reference_scale": {
                str(name): float(value)
                for name, value in self.block_reference_scale.items()
            },
            "block_n_values": {
                str(name): int(value) for name, value in self.block_n_values.items()
            },
            "params_best": {
                str(name): float(value) for name, value in self.params_best.items()
            },
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

    def to_mapping(self) -> dict[str, Any]:
        """Return one JSON-friendly summary."""
        return {
            "role": "calibration_twin_benchmark",
            "case_id": self.definition.case_id,
            "solver_name": self.definition.solver_name,
            "regime": self.definition.regime,
            "description": self.definition.description,
            "perturbation_description": self.definition.perturbation_description,
            "benchmark_root": str(self.benchmark_root),
            "simulation_config_path": str(self.simulation_config_path),
            "truth_simulation_config_path": str(self.truth_simulation_config_path),
            "truth_params": {
                str(name): float(value)
                for name, value in self.definition.truth_params.items()
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
