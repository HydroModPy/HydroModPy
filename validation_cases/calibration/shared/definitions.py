"""Contracts shared by calibration inverse-validation cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CalibrationMethodProfile:
    """Method configuration used in one standardized inverse benchmark."""

    name: str
    method_kwargs: Mapping[str, Any] = field(default_factory=dict)
    persist_model_distribution: bool = False


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
    build_simulation_config: Callable[[Path, Path], None] | None = None
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
    calibration_id: str
    calibration_root: Path
    result_path: Path | None
    cost_best: float | None
    iteration_count: int
    n_evaluations: int
    params_best: dict[str, float]
    param_abs_error: dict[str, float]
    recovered_truth: bool
    model_distribution_path: Path | None = None
    model_distribution_sample_count: int = 0
    truth_in_distribution: bool | None = None
    truth_distribution_min_abs_error: dict[str, float] = field(default_factory=dict)

    def to_mapping(self) -> dict[str, Any]:
        """Return one JSON-friendly representation."""
        return {
            "method_name": self.method_name,
            "calibration_id": self.calibration_id,
            "calibration_root": str(self.calibration_root),
            "result_path": None if self.result_path is None else str(self.result_path),
            "cost_best": self.cost_best,
            "iteration_count": int(self.iteration_count),
            "n_evaluations": int(self.n_evaluations),
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
    observations_truth: dict[str, tuple[float, ...]]
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
            "benchmark_root": str(self.benchmark_root),
            "simulation_config_path": str(self.simulation_config_path),
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
            "method_results": [item.to_mapping() for item in self.method_results],
        }
