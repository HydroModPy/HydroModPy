"""Prepared runtime helpers for the model-calibration launcher."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from hydromodpy.analysis.calibration.core.composite_objective import (
    CompositeObjective,
    CompositeObjectiveBlock,
    CompositeObjectiveEvaluation,
)
from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.core.workspace.config import WorkspaceConfig

from launchers.model_calibration.config import ModelCalibrationConfig


_NUMERIC_WITH_SUFFIX_RE = re.compile(
    r"^\s*(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<suffix>.*\S)?\s*$"
)
_POSTERIOR_DISTRIBUTION_METHODS = frozenset({"gp_mapping", "da_mh_gp"})
_EMPIRICAL_ENSEMBLE_METHODS = frozenset({"random_search"})


def resolve_workspace_config(
    raw_simulation_toml: dict[str, Any],
    *,
    simulation_config_path: Path,
) -> WorkspaceConfig:
    """Resolve the simulation-side workspace config without loading the full runtime."""
    workspace_section = dict(raw_simulation_toml.get("workspace", {}))
    if "project_root" not in workspace_section:
        workspace_section["project_root"] = simulation_config_path.parent.resolve()
    else:
        project_root = Path(workspace_section["project_root"]).expanduser()
        if not project_root.is_absolute():
            project_root = (simulation_config_path.parent / project_root).resolve()
        workspace_section["project_root"] = project_root

    output_root = workspace_section.get("output_root")
    if output_root is not None:
        output_root_path = Path(output_root).expanduser()
        if not output_root_path.is_absolute():
            output_root_path = (simulation_config_path.parent / output_root_path).resolve()
        workspace_section["output_root"] = output_root_path

    workspace_root = workspace_section.get("workspace_root")
    if workspace_root is not None:
        workspace_root_path = Path(workspace_root).expanduser()
        if not workspace_root_path.is_absolute():
            workspace_root_path = (
                simulation_config_path.parent / workspace_root_path
            ).resolve()
        workspace_section["workspace_root"] = workspace_root_path

    return WorkspaceConfig(**workspace_section)


def detect_solver_families(raw_simulation_toml: dict[str, Any]) -> tuple[str, ...]:
    """Extract unique solver names from the simulation process plan."""
    simulation_section = raw_simulation_toml.get("simulation", {})
    processes = simulation_section.get("process", [])
    solvers: list[str] = []
    for process in processes:
        if not isinstance(process, dict):
            continue
        for solver in process.get("solvers", []):
            token = str(solver).strip().lower()
            if token and token not in solvers:
                solvers.append(token)
    return tuple(solvers)


@dataclass(frozen=True, slots=True)
class PreparedCalibrationSession:
    """Prepared runtime context resolved once for one calibration launcher session."""

    config_path: Path
    simulation_config_path: Path
    raw_simulation_toml: dict[str, Any]
    simulation_workspace: WorkspaceConfig
    calibration_id: str
    calibration_root: Path
    session_manifest_path: Path
    iteration_history_path: Path
    solver_families: tuple[str, ...]
    primary_solver: str | None
    supported_v1_backend: bool
    core_settings: dict[str, Any]
    parameter_names: tuple[str, ...]
    output_names: tuple[str, ...]
    objective_block_names: tuple[str, ...]
    candidates_root: Path | None = None

    def to_summary(self) -> dict[str, Any]:
        """Return one launcher summary derived from the prepared session."""
        return {
            "mode": "model_calibration",
            "status": "prepared",
            "config_path": str(self.config_path),
            "simulation_config": str(self.simulation_config_path),
            "calibration_id": self.calibration_id,
            "calibration_root": str(self.calibration_root),
            "session_manifest_path": str(self.session_manifest_path),
            "iteration_history_path": str(self.iteration_history_path),
            "candidates_root": (
                None if self.candidates_root is None else str(self.candidates_root)
            ),
            "primary_solver": self.primary_solver,
            "solver_families": list(self.solver_families),
            "supported_v1_backend": self.supported_v1_backend,
            "method": self.core_settings["method"],
            "parameter_names": list(self.parameter_names),
            "n_parameters": len(self.parameter_names),
            "output_names": list(self.output_names),
            "n_outputs": len(self.output_names),
            "objective_block_names": list(self.objective_block_names),
            "n_objective_blocks": len(self.objective_block_names),
        }


@dataclass(frozen=True, slots=True)
class IterationRecord:
    """Minimal persisted record for one calibration iteration."""

    iteration_id: str
    params_vector: tuple[float, ...]
    params_named: dict[str, float]
    objective_total: float | None
    block_costs: dict[str, float] = field(default_factory=dict)
    status: str = "ok"
    failure_reason: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        """Return one JSON-serializable view of the iteration record."""
        return {
            "iteration_id": str(self.iteration_id),
            "params_vector": [float(value) for value in self.params_vector],
            "params_named": {
                str(name): float(value) for name, value in self.params_named.items()
            },
            "objective_total": (
                None if self.objective_total is None else float(self.objective_total)
            ),
            "block_costs": {
                str(name): float(value) for name, value in self.block_costs.items()
            },
            "status": str(self.status),
            "failure_reason": (
                None if self.failure_reason is None else str(self.failure_reason)
            ),
        }


@dataclass(frozen=True, slots=True)
class CandidateRunRequest:
    """One materialized candidate derived from a prepared calibration session."""

    session: PreparedCalibrationSession
    iteration_id: str
    candidate_run_id: str
    candidate_root: Path
    candidate_config_path: Path
    params_vector: tuple[float, ...]
    params_named: dict[str, float]
    override_payload: dict[str, Any]

    def to_summary(self) -> dict[str, Any]:
        """Return one concise summary of the candidate runtime request."""
        return {
            "iteration_id": self.iteration_id,
            "candidate_run_id": self.candidate_run_id,
            "candidate_root": str(self.candidate_root),
            "candidate_config_path": str(self.candidate_config_path),
            "params_vector": [float(value) for value in self.params_vector],
            "params_named": {
                str(name): float(value) for name, value in self.params_named.items()
            },
        }


@dataclass(frozen=True, slots=True)
class CandidateRunOutcome:
    """Outcome of one candidate execution attempt."""

    request: CandidateRunRequest
    status: str
    run_state: Any | None = None
    objective_evaluation: CompositeObjectiveEvaluation | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_iteration_record(self) -> IterationRecord:
        """Convert one run outcome into the persisted minimal iteration record."""
        failure_reason = self.error_message
        objective_total: float | None = None
        block_costs: dict[str, float] = {}
        if self.objective_evaluation is not None:
            objective_total = float(self.objective_evaluation.total_cost)
            block_costs = {
                block.name: float(block.normalized_cost)
                for block in self.objective_evaluation.blocks
            }
        elif self.status in {"solver_run_failed", "objective_evaluation_failed"}:
            objective_total = math.inf
        return IterationRecord(
            iteration_id=self.request.iteration_id,
            params_vector=self.request.params_vector,
            params_named=self.request.params_named,
            objective_total=objective_total,
            block_costs=block_costs,
            status=self.status,
            failure_reason=failure_reason,
        )


def _jsonable(value: Any) -> Any:
    """Convert common runtime values to JSON-friendly Python values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value


def _parameter_statistics(
    *,
    samples: np.ndarray,
    parameter_names: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    """Summarize one parameter sample matrix by named marginal statistics."""
    if samples.size == 0:
        return {}
    stats: dict[str, dict[str, float]] = {}
    quantiles = np.nanpercentile(samples, [5.0, 50.0, 95.0], axis=0)
    for index, name in enumerate(parameter_names):
        values = samples[:, index]
        stats[str(name)] = {
            "mean": float(np.nanmean(values)),
            "std": float(np.nanstd(values, ddof=1)) if values.size > 1 else 0.0,
            "min": float(np.nanmin(values)),
            "q05": float(quantiles[0, index]),
            "q50": float(quantiles[1, index]),
            "q95": float(quantiles[2, index]),
            "max": float(np.nanmax(values)),
        }
    return stats


def _params_named_from_vector(
    *,
    session: PreparedCalibrationSession,
    vector: Any,
) -> dict[str, float]:
    """Map one ordered vector to calibrated parameter names."""
    parameter_set = session.core_settings["parameter_set"]
    return {
        str(name): float(value)
        for name, value in parameter_set.mapping_from(vector).items()
    }


def _sample_rows_from_matrix(
    *,
    session: PreparedCalibrationSession,
    samples: np.ndarray,
) -> list[dict[str, Any]]:
    """Serialize a parameter sample matrix as model-distribution rows."""
    rows: list[dict[str, Any]] = []
    for index, vector in enumerate(samples, start=1):
        params_vector = tuple(float(value) for value in np.asarray(vector).ravel())
        rows.append(
            {
                "sample_id": f"sample_{index:06d}",
                "params_vector": list(params_vector),
                "params_named": _params_named_from_vector(
                    session=session,
                    vector=params_vector,
                ),
            }
        )
    return rows


def _sample_rows_from_evaluated_outcomes(
    outcomes: tuple[CandidateRunOutcome, ...],
) -> list[dict[str, Any]]:
    """Serialize evaluated candidates as an empirical model ensemble."""
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        record = outcome.to_iteration_record()
        rows.append(
            {
                "sample_id": outcome.request.iteration_id,
                "candidate_run_id": outcome.request.candidate_run_id,
                "candidate_config_path": str(outcome.request.candidate_config_path),
                "params_vector": list(record.params_vector),
                "params_named": dict(record.params_named),
                "objective_total": record.objective_total,
                "block_costs": dict(record.block_costs),
                "status": record.status,
                "failure_reason": record.failure_reason,
            }
        )
    return rows


def build_model_distribution_payload(
    *,
    session: PreparedCalibrationSession,
    result: Any,
    evaluator: ModelCalibrationObjectiveEvaluator,
) -> dict[str, Any] | None:
    """Build a persisted parameter/model distribution payload when available."""
    method = str(result.method).strip().lower()
    parameter_names = tuple(session.parameter_names)
    result_samples = getattr(result, "samples", None)
    if result_samples is not None:
        samples = np.asarray(result_samples, dtype=float)
        if samples.ndim == 2 and samples.shape[0] > 0:
            return {
                "role": (
                    "posterior_parameter_distribution"
                    if method in _POSTERIOR_DISTRIBUTION_METHODS
                    else "parameter_sample_distribution"
                ),
                "method": method,
                "source": "CalibrationResults.samples",
                "parameter_names": list(parameter_names),
                "sample_count": int(samples.shape[0]),
                "model_semantics": (
                    "Each row defines one parameterized model. Full model "
                    "outputs are obtained by materializing and running that "
                    "parameter set as a candidate."
                ),
                "statistics": _parameter_statistics(
                    samples=samples,
                    parameter_names=parameter_names,
                ),
                "samples": _sample_rows_from_matrix(
                    session=session,
                    samples=samples,
                ),
            }

    if method not in _EMPIRICAL_ENSEMBLE_METHODS:
        return None

    outcomes = evaluator.outcomes
    if not outcomes:
        return None
    samples = np.asarray(
        [outcome.request.params_vector for outcome in outcomes],
        dtype=float,
    )
    return {
        "role": "empirical_evaluated_model_ensemble",
        "method": method,
        "source": "evaluated_candidates",
        "parameter_names": list(parameter_names),
        "sample_count": int(samples.shape[0]),
        "model_semantics": (
            "Each row is a model candidate already evaluated during the "
            "stochastic search, with its objective value when available."
        ),
        "statistics": _parameter_statistics(
            samples=samples,
            parameter_names=parameter_names,
        ),
        "samples": _sample_rows_from_evaluated_outcomes(outcomes),
    }


def _sample_objective_total(sample: dict[str, Any]) -> float | None:
    """Return one finite objective value when a sample carries one."""
    value = sample.get("objective_total")
    if value is None:
        return None
    try:
        objective = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(objective):
        return None
    return objective


def _unique_limited(indices: list[int], *, max_count: int) -> tuple[int, ...]:
    """Keep first-seen unique indices up to `max_count`."""
    selected: list[int] = []
    seen: set[int] = set()
    for index in indices:
        if index in seen:
            continue
        selected.append(int(index))
        seen.add(int(index))
        if len(selected) >= max_count:
            break
    return tuple(selected)


def _evenly_spaced_indices(total_count: int, *, max_count: int) -> tuple[int, ...]:
    """Return stable row indices spread over `[0, total_count)`."""
    if total_count <= 0 or max_count <= 0:
        return ()
    if total_count <= max_count:
        return tuple(range(total_count))
    raw_indices = [
        int(round(float(value)))
        for value in np.linspace(0, total_count - 1, num=max_count)
    ]
    if len(set(raw_indices)) < max_count:
        raw_indices.extend(range(total_count))
    return _unique_limited(raw_indices, max_count=max_count)


def _finite_objective_rank_indices(
    samples: list[dict[str, Any]],
) -> tuple[int, ...]:
    """Return sample row indices sorted from best to worst finite objective."""
    ranked: list[tuple[float, int]] = []
    for index, sample in enumerate(samples):
        objective = _sample_objective_total(sample)
        if objective is not None:
            ranked.append((objective, index))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple(index for _, index in ranked)


def _representative_parameter_indices(
    samples: list[dict[str, Any]],
    *,
    max_count: int,
) -> tuple[int, ...]:
    """Select sample rows closest to marginal parameter quantile vectors."""
    if max_count <= 0:
        return ()

    vectors: list[np.ndarray] = []
    row_indices: list[int] = []
    for index, sample in enumerate(samples):
        try:
            vector = np.asarray(sample["params_vector"], dtype=float).ravel()
        except (KeyError, TypeError, ValueError):
            continue
        if vector.size == 0 or not np.all(np.isfinite(vector)):
            continue
        vectors.append(vector)
        row_indices.append(index)

    if not vectors:
        return _evenly_spaced_indices(len(samples), max_count=max_count)
    if len(vectors) <= max_count:
        return tuple(row_indices)

    matrix = np.vstack(vectors)
    probabilities = (
        np.asarray([0.5], dtype=float)
        if max_count == 1
        else np.linspace(0.05, 0.95, num=max_count)
    )
    targets = np.nanquantile(matrix, probabilities, axis=0)
    scale = np.nanstd(matrix, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 0.0), scale, 1.0)

    selected: list[int] = []
    for target in np.atleast_2d(targets):
        distances = np.linalg.norm((matrix - target) / scale, axis=1)
        selected.append(row_indices[int(np.nanargmin(distances))])
    selected.extend(_evenly_spaced_indices(len(samples), max_count=max_count))
    return _unique_limited(selected, max_count=max_count)


def select_model_distribution_samples(
    *,
    payload: dict[str, Any],
    max_count: int,
    selection: str,
) -> list[tuple[int, dict[str, Any]]]:
    """Select model-distribution rows for optional full-output reruns."""
    if max_count <= 0:
        return []
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        return []
    indexed_samples = [
        (index, sample)
        for index, sample in enumerate(raw_samples)
        if isinstance(sample, dict)
    ]
    samples = [sample for _, sample in indexed_samples]
    max_count = min(int(max_count), len(samples))
    if max_count <= 0:
        return []

    selection_mode = str(selection).strip().lower()
    if selection_mode == "evenly_spaced":
        selected_indices = _evenly_spaced_indices(len(samples), max_count=max_count)
    elif selection_mode == "best":
        ranked = list(_finite_objective_rank_indices(samples))
        ranked.extend(range(len(samples)))
        selected_indices = _unique_limited(ranked, max_count=max_count)
    else:
        ranked = _finite_objective_rank_indices(samples)
        if ranked:
            rank_positions = _evenly_spaced_indices(
                len(ranked),
                max_count=max_count,
            )
            selected_indices = tuple(ranked[position] for position in rank_positions)
        else:
            selected_indices = _representative_parameter_indices(
                samples,
                max_count=max_count,
            )

    return [
        (indexed_samples[index][0], samples[index])
        for index in selected_indices
    ]


def persist_model_distribution(
    *,
    session: PreparedCalibrationSession,
    result: Any | None = None,
    evaluator: ModelCalibrationObjectiveEvaluator | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Write `model_distribution.json` when the method exposes an ensemble."""
    if payload is None:
        if result is None or evaluator is None:
            raise ValueError(
                "persist_model_distribution requires either payload or "
                "result/evaluator"
            )
        payload = build_model_distribution_payload(
            session=session,
            result=result,
            evaluator=evaluator,
        )
    if payload is None:
        return None

    distribution_path = session.calibration_root / "model_distribution.json"
    distribution_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(distribution_path),
        "role": payload["role"],
        "method": payload["method"],
        "source": payload["source"],
        "sample_count": payload["sample_count"],
    }


def execute_model_distribution_reruns(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    distribution_payload: dict[str, Any] | None,
    launcher_factory: Any,
    max_reruns: int,
    selection: str,
) -> dict[str, Any] | None:
    """Run a selected subset of model-distribution samples with full outputs."""
    if distribution_payload is None:
        return {
            "status": "skipped",
            "reason": "no_model_distribution",
            "selected_count": 0,
        }

    selected_samples = select_model_distribution_samples(
        payload=distribution_payload,
        max_count=max_reruns,
        selection=selection,
    )
    manifest_path = session.calibration_root / "model_distribution_reruns.json"
    rerun_rows: list[dict[str, Any]] = []
    for ordinal, (sample_index, sample) in enumerate(selected_samples, start=1):
        sample_id = str(sample.get("sample_id", f"sample_{sample_index + 1:06d}"))
        request = actualize_candidate(
            session=session,
            cfg=cfg,
            params=sample["params_vector"],
            candidate_label=f"ensemble_{ordinal:04d}_{sample_id}",
            disable_display=False,
            disable_postprocess=False,
        )
        outcome = execute_candidate_run(
            request=request,
            launcher_factory=launcher_factory,
            cfg=None,
        )
        rerun_rows.append(
            {
                "rerun_id": f"ensemble_{ordinal:04d}",
                "sample_index": int(sample_index),
                "sample_id": sample_id,
                "source_objective_total": sample.get("objective_total"),
                "source_block_costs": sample.get("block_costs"),
                "status": outcome.status,
                "candidate_run_id": outcome.request.candidate_run_id,
                "candidate_config_path": str(outcome.request.candidate_config_path),
                "params_vector": list(outcome.request.params_vector),
                "params_named": dict(outcome.request.params_named),
                "error_type": outcome.error_type,
                "error_message": outcome.error_message,
            }
        )

    status = (
        "completed"
        if all(row["status"] == "solver_run_succeeded" for row in rerun_rows)
        else "completed_with_failures"
    )
    if not rerun_rows:
        status = "skipped"
    manifest_payload = {
        "role": "model_distribution_output_reruns",
        "source_model_distribution_role": distribution_payload.get("role"),
        "source_model_distribution_method": distribution_payload.get("method"),
        "selection": str(selection),
        "requested_max_reruns": int(max_reruns),
        "selected_count": len(rerun_rows),
        "status": status,
        "reruns": rerun_rows,
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(manifest_path),
        "status": status,
        "selection": str(selection),
        "requested_max_reruns": int(max_reruns),
        "selected_count": len(rerun_rows),
    }


def serialize_calibration_result(result: Any) -> dict[str, Any]:
    """Return one JSON-serializable summary of a core calibration result."""
    payload = {
        "method": str(result.method),
        "x_best": _jsonable(result.x_best),
        "params_best": _jsonable(result.params_best),
        "cost_best": float(result.cost_best),
        "score_best": (
            None if result.score_best is None else float(result.score_best)
        ),
        "n_evaluations": int(result.n_evaluations),
        "metadata": _jsonable(getattr(result, "metadata", {})),
    }
    samples = getattr(result, "samples", None)
    if samples is not None:
        payload["samples"] = _jsonable(samples)
    return payload


def _failed_objective_evaluation(
    outcome: CandidateRunOutcome,
) -> CompositeObjectiveEvaluation:
    """Represent a failed candidate as an infinite objective evaluation."""
    return CompositeObjectiveEvaluation(
        total_cost=math.inf,
        total_score=-math.inf,
        blocks=(),
        metadata={
            "status": outcome.status,
            "error_type": outcome.error_type,
            "error_message": outcome.error_message,
            "iteration_id": outcome.request.iteration_id,
            "candidate_run_id": outcome.request.candidate_run_id,
            "candidate_config_path": str(outcome.request.candidate_config_path),
        },
    )


def _sanitize_candidate_label(label: str) -> str:
    """Return one filesystem-safe candidate label."""
    text = str(label).strip().lower()
    if not text:
        raise ValueError("candidate_label cannot be empty")
    return re.sub(r"[^a-z0-9_.-]+", "_", text)


def validate_objective_ready_for_calibration(
    cfg: ModelCalibrationConfig,
) -> None:
    """Reject calibration runs whose composite objective cannot yet be evaluated."""
    outputs_by_name = {
        output_cfg.name: output_cfg for output_cfg in cfg.model_calibration.output
    }
    missing_observations: list[str] = []
    direct_cost_blocks: list[str] = []
    for block_cfg in cfg.model_calibration.objective_block:
        if block_cfg.metric == "direct_cost":
            direct_cost_blocks.append(block_cfg.name)
        for output_name in block_cfg.uses_outputs:
            output_cfg = outputs_by_name[output_name]
            if output_cfg.observed_values is None:
                missing_observations.append(f"{block_cfg.name}:{output_name}")

    if direct_cost_blocks:
        raise NotImplementedError(
            "direct_cost objective blocks are reserved for future map comparisons: "
            f"{direct_cost_blocks}"
        )
    if missing_observations:
        raise ValueError(
            "Full model calibration requires observed_values for every output used "
            f"by objective blocks. Missing: {missing_observations}"
        )


@dataclass
class ModelCalibrationObjectiveEvaluator:
    """Objective evaluator that lets CalibrationEngine drive launcher candidates."""

    session: PreparedCalibrationSession
    cfg: ModelCalibrationConfig
    launcher_factory: Any
    iteration_start: int = 1
    record_callback: Callable[[IterationRecord], None] | None = None
    _next_iteration_index: int = field(init=False, repr=False)
    _evaluations_by_key: dict[tuple[float, ...], CompositeObjectiveEvaluation] = (
        field(default_factory=dict, init=False, repr=False)
    )
    _outcomes_by_key: dict[tuple[float, ...], CandidateRunOutcome] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    cache_hit_count: int = field(default=0, init=False)
    candidate_run_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        validate_objective_ready_for_calibration(self.cfg)
        self._next_iteration_index = int(self.iteration_start)

    def _cache_key(
        self,
        params: dict[str, float] | tuple[float, ...],
    ) -> tuple[float, ...]:
        parameter_set = self.session.core_settings["parameter_set"]
        return tuple(float(value) for value in parameter_set.vector_from(params))

    def evaluate(self, params: dict[str, float]) -> CompositeObjectiveEvaluation:
        """Run or reuse one candidate objective evaluation."""
        key = self._cache_key(params)
        cached = self._evaluations_by_key.get(key)
        if cached is not None:
            self.cache_hit_count += 1
            return cached

        iteration_index = self._next_iteration_index
        self._next_iteration_index += 1
        request = actualize_candidate(
            session=self.session,
            cfg=self.cfg,
            params=key,
            iteration_index=iteration_index,
        )
        outcome = execute_candidate_run(
            request=request,
            launcher_factory=self.launcher_factory,
            cfg=self.cfg,
        )
        self.candidate_run_count += 1
        if self.record_callback is not None:
            self.record_callback(outcome.to_iteration_record())

        evaluation = (
            outcome.objective_evaluation
            if outcome.objective_evaluation is not None
            else _failed_objective_evaluation(outcome)
        )
        self._outcomes_by_key[key] = outcome
        self._evaluations_by_key[key] = evaluation
        return evaluation

    @property
    def outcomes(self) -> tuple[CandidateRunOutcome, ...]:
        """Return unique executed candidate outcomes in evaluation order."""
        return tuple(self._outcomes_by_key.values())


def _split_target_path(target: str) -> tuple[str, ...]:
    """Split one dotted target path into validated segments."""
    parts = tuple(str(token).strip() for token in str(target).split("."))
    if not parts or any(not part for part in parts):
        raise ValueError(f"Invalid empty target path segment in '{target}'")
    return parts


def _lookup_nested_value(mapping: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Resolve one dotted target path inside a nested mapping."""
    current: Any = mapping
    current_path: list[str] = []
    for key in path:
        current_path.append(key)
        if not isinstance(current, dict):
            raise KeyError(
                "Cannot descend into non-mapping value at "
                f"{'.'.join(current_path[:-1]) or '<root>'}"
            )
        if key not in current:
            raise KeyError(f"Missing target path '{'.'.join(current_path)}'")
        current = current[key]
    return current


def _assign_nested_value(mapping: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """Assign one value inside a nested mapping, creating intermediate dicts."""
    current = mapping
    for key in path[:-1]:
        existing = current.get(key)
        if existing is None:
            current[key] = {}
            existing = current[key]
        elif not isinstance(existing, dict):
            raise ValueError(
                f"Cannot create nested path under non-mapping key '{key}'"
            )
        current = existing
    current[path[-1]] = value


def _parse_numeric_with_optional_suffix(value: Any) -> tuple[float, str | None] | None:
    """Return `(number, suffix)` for scalars or numeric-with-unit strings."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value), None
    if not isinstance(value, str):
        return None
    match = _NUMERIC_WITH_SUFFIX_RE.match(value)
    if match is None:
        return None
    number = float(match.group("number"))
    suffix = match.group("suffix")
    return number, (None if suffix is None else str(suffix).strip())


def _format_numeric_like(value: float, *, suffix: str | None) -> Any:
    """Format one numeric value, optionally preserving a unit suffix."""
    number_text = format(float(value), ".12g")
    if suffix is None or suffix == "":
        return float(number_text)
    return f"{number_text} {suffix}"


def _apply_parameter_override(
    *,
    base_value: Any,
    candidate_value: float,
    mode: str,
) -> Any:
    """Apply one calibrated candidate value onto the current target payload."""
    parsed = _parse_numeric_with_optional_suffix(base_value)
    if parsed is None:
        raise TypeError(
            "Path-based parameter injection currently supports only numeric "
            "targets or numeric strings with optional unit suffixes"
        )
    base_number, suffix = parsed
    candidate_number = float(candidate_value)

    if mode == "replace":
        return _format_numeric_like(candidate_number, suffix=suffix)
    if mode == "scale":
        return _format_numeric_like(base_number * candidate_number, suffix=suffix)
    raise ValueError(f"Unsupported parameter injection mode '{mode}'")


def _format_toml_scalar(value: Any) -> str:
    """Format one supported scalar as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("TOML writer does not support NaN/Inf values")
        return format(value, ".12g")
    if isinstance(value, Path):
        return json.dumps(str(value), ensure_ascii=True)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML scalar value: {type(value)!r}")


def _render_toml_mapping(mapping: dict[str, Any], *, prefix: tuple[str, ...] = ()) -> list[str]:
    """Render a nested mapping into a minimal TOML document."""
    lines: list[str] = []
    scalars: list[tuple[str, Any]] = []
    subtables: list[tuple[str, dict[str, Any]]] = []

    for key, value in mapping.items():
        if isinstance(value, dict):
            subtables.append((str(key), value))
        else:
            scalars.append((str(key), value))

    if prefix:
        lines.append(f"[{'.'.join(prefix)}]")
    for key, value in scalars:
        lines.append(f"{key} = {_format_toml_scalar(value)}")
    if prefix and (scalars or subtables):
        lines.append("")

    for key, value in subtables:
        lines.extend(_render_toml_mapping(value, prefix=(*prefix, key)))

    return lines


def _write_override_toml(path: Path, payload: dict[str, Any]) -> None:
    """Write one minimal override TOML payload to disk."""
    lines = _render_toml_mapping(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def prepare_calibration_session(
    *,
    config_path: Path,
    cfg: ModelCalibrationConfig,
) -> PreparedCalibrationSession:
    """Resolve one prepared calibration session from launcher config plus target simulation."""
    raw_simulation_toml = load_toml_with_base_config(cfg.simulation_config_path)
    simulation_workspace = resolve_workspace_config(
        raw_simulation_toml,
        simulation_config_path=cfg.simulation_config_path,
    )
    core_settings = cfg.resolve_core_settings()
    calibration_id = cfg.model_calibration.calibration_id or config_path.stem
    calibration_root = simulation_workspace.calibration_folder / calibration_id
    solver_families = detect_solver_families(raw_simulation_toml)
    primary_solver = solver_families[0] if solver_families else None

    return PreparedCalibrationSession(
        config_path=config_path,
        simulation_config_path=cfg.simulation_config_path,
        raw_simulation_toml=dict(raw_simulation_toml),
        simulation_workspace=simulation_workspace,
        calibration_id=calibration_id,
        calibration_root=calibration_root,
        session_manifest_path=calibration_root / "session_manifest.json",
        iteration_history_path=calibration_root / "iteration_history.jsonl",
        candidates_root=calibration_root / "runtime_candidates",
        solver_families=solver_families,
        primary_solver=primary_solver,
        supported_v1_backend=primary_solver == "modflow6",
        core_settings=dict(core_settings),
        parameter_names=cfg.parameter_names,
        output_names=cfg.output_names,
        objective_block_names=cfg.objective_block_names,
    )


def initialize_calibration_session(
    session: PreparedCalibrationSession,
    *,
    cfg: ModelCalibrationConfig,
) -> dict[str, Any]:
    """Materialize one prepared session on disk and return the written manifest payload."""
    session.calibration_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        **session.to_summary(),
        "disable_display": cfg.model_calibration.disable_display,
        "disable_postprocess": cfg.model_calibration.disable_postprocess,
        "rerun_best_with_outputs": cfg.model_calibration.rerun_best_with_outputs,
        "persist_model_distribution": (
            cfg.model_calibration.persist_model_distribution
        ),
        "rerun_model_distribution_with_outputs": (
            cfg.model_calibration.rerun_model_distribution_with_outputs
        ),
        "model_distribution_max_reruns": (
            cfg.model_calibration.model_distribution_max_reruns
        ),
        "model_distribution_rerun_selection": (
            cfg.model_calibration.model_distribution_rerun_selection
        ),
        "persist_iteration_history": cfg.model_calibration.persist_iteration_history,
        "persist_iteration_detail_level": (
            cfg.model_calibration.persist_iteration_detail_level
        ),
        "objective_metric": cfg.calibration.objective_metric,
        "objective_transform": cfg.objective.transform,
        "iteration_count": 0,
    }
    session.session_manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    if cfg.model_calibration.persist_iteration_history:
        session.iteration_history_path.write_text("", encoding="utf-8")
    return manifest


def append_iteration_record(
    *,
    history_path: Path,
    record: IterationRecord,
) -> None:
    """Append one minimal iteration record to the session JSONL history."""
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record.to_mapping(), ensure_ascii=True) + "\n")


def update_session_manifest(
    *,
    manifest_path: Path,
    record: IterationRecord | None = None,
) -> dict[str, Any]:
    """Update the session manifest after one iteration append."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["iteration_count"] = int(manifest.get("iteration_count", 0)) + 1
    if record is not None:
        manifest["last_iteration_id"] = record.iteration_id
        manifest["last_iteration_status"] = record.status
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def persist_iteration_record(
    *,
    session: PreparedCalibrationSession,
    record: IterationRecord,
) -> dict[str, Any]:
    """Append one iteration record and refresh the session manifest counter."""
    append_iteration_record(history_path=session.iteration_history_path, record=record)
    return update_session_manifest(manifest_path=session.session_manifest_path, record=record)


def finalize_calibration_session(
    *,
    session: PreparedCalibrationSession,
    result: Any,
    evaluator: ModelCalibrationObjectiveEvaluator,
    best_rerun_outcome: CandidateRunOutcome | None = None,
    model_distribution_payload: dict[str, Any] | None = None,
    model_distribution_rerun_summary: dict[str, Any] | None = None,
    persist_distribution: bool = True,
) -> dict[str, Any]:
    """Persist the final calibration result and update the session manifest."""
    result_payload = serialize_calibration_result(result)
    result_path = session.calibration_root / "calibration_result.json"
    result_path.write_text(
        json.dumps(result_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    distribution_summary = None
    if persist_distribution:
        distribution_summary = persist_model_distribution(
            session=session,
            result=result,
            evaluator=evaluator,
            payload=model_distribution_payload,
        )

    manifest = json.loads(session.session_manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "status": "calibrated",
            "result_path": str(result_path),
            "method": result_payload["method"],
            "cost_best": result_payload["cost_best"],
            "score_best": result_payload["score_best"],
            "params_best": result_payload["params_best"],
            "n_evaluations": result_payload["n_evaluations"],
            "candidate_run_count": int(evaluator.candidate_run_count),
            "objective_cache_hit_count": int(evaluator.cache_hit_count),
            "model_distribution": distribution_summary,
            "model_distribution_rerun": model_distribution_rerun_summary,
        }
    )
    if best_rerun_outcome is not None:
        manifest["best_rerun"] = {
            "status": best_rerun_outcome.status,
            "candidate_run_id": best_rerun_outcome.request.candidate_run_id,
            "candidate_config_path": str(
                best_rerun_outcome.request.candidate_config_path
            ),
            "error_type": best_rerun_outcome.error_type,
            "error_message": best_rerun_outcome.error_message,
        }
    session.session_manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _as_1d_float_tuple(values: Any, *, label: str) -> tuple[float, ...]:
    """Normalize one selected observable payload to a non-empty float tuple."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{label} cannot be empty")
    return tuple(float(value) for value in arr)


def _candidate_output_containers(run_state: Any) -> tuple[Any, ...]:
    """Return possible output containers in lookup priority order."""
    containers: list[Any] = []
    if isinstance(run_state, dict):
        for key in ("calibration_outputs", "outputs"):
            value = run_state.get(key)
            if value is not None:
                containers.append(value)
        containers.append(run_state)
        return tuple(containers)

    for attr in ("calibration_outputs", "outputs"):
        value = getattr(run_state, attr, None)
        if value is not None:
            containers.append(value)
    execution = getattr(run_state, "execution", None)
    if execution is not None:
        for attr in ("calibration_outputs", "outputs"):
            value = getattr(execution, attr, None)
            if value is not None:
                containers.append(value)
    return tuple(containers)


def _lookup_output_value(run_state: Any, output_name: str) -> Any:
    """Lookup one configured output in generic run-state output containers."""
    for container in _candidate_output_containers(run_state):
        if isinstance(container, dict) and output_name in container:
            return container[output_name]
        if hasattr(container, output_name):
            return getattr(container, output_name)
    raise KeyError(
        "Could not find calibration output "
        f"'{output_name}' in run_state.calibration_outputs or run_state.outputs"
    )


def select_candidate_outputs(
    *,
    cfg: ModelCalibrationConfig,
    run_state: Any,
) -> dict[str, tuple[float, ...]]:
    """Select configured simulated observables from one run-state payload."""
    selected: dict[str, tuple[float, ...]] = {}
    for output_cfg in cfg.model_calibration.output:
        value = _lookup_output_value(run_state, output_cfg.name)
        selected[output_cfg.name] = _as_1d_float_tuple(
            value,
            label=f"simulated output '{output_cfg.name}'",
        )
    return selected


def _objective_has_observations(cfg: ModelCalibrationConfig) -> bool:
    """Return True when at least one configured output carries observed values."""
    return any(
        output_cfg.observed_values is not None
        for output_cfg in cfg.model_calibration.output
    )


def evaluate_candidate_objective(
    *,
    cfg: ModelCalibrationConfig,
    run_state: Any,
) -> CompositeObjectiveEvaluation:
    """Evaluate configured composite objective from one candidate run-state."""
    selected = select_candidate_outputs(cfg=cfg, run_state=run_state)
    outputs_by_name = {
        output_cfg.name: output_cfg for output_cfg in cfg.model_calibration.output
    }

    blocks: list[CompositeObjectiveBlock] = []
    for block_cfg in cfg.model_calibration.objective_block:
        if block_cfg.metric == "direct_cost":
            raise NotImplementedError(
                "direct_cost objective blocks are reserved for future map comparisons"
            )

        observed_parts: list[np.ndarray] = []
        for output_name in block_cfg.uses_outputs:
            output_cfg = outputs_by_name[output_name]
            if output_cfg.observed_values is None:
                raise ValueError(
                    f"Output '{output_name}' used by block '{block_cfg.name}' "
                    "does not define observed_values"
                )
            observed_parts.append(
                np.asarray(output_cfg.observed_values, dtype=float).ravel()
            )
        observed = np.concatenate(observed_parts)

        def _selector(
            payload: dict[str, tuple[float, ...]],
            names=tuple(block_cfg.uses_outputs),
        ):
            return np.concatenate(
                [np.asarray(payload[name], dtype=float).ravel() for name in names]
            )

        blocks.append(
            CompositeObjectiveBlock(
                name=block_cfg.name,
                observed=observed,
                selector=_selector,
                metric=block_cfg.metric,
                weight=block_cfg.weight,
                normalize_cost=block_cfg.normalize_cost,
                metadata={"uses_outputs": tuple(block_cfg.uses_outputs)},
            )
        )

    objective = CompositeObjective(
        simulator=lambda _params: selected,
        blocks=tuple(blocks),
    )
    return objective.evaluate({})


def actualize_candidate(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    params: dict[str, float] | tuple[float, ...] | list[float],
    iteration_index: int | None = None,
    candidate_label: str | None = None,
    disable_display: bool | None = None,
    disable_postprocess: bool | None = None,
) -> CandidateRunRequest:
    """Materialize one candidate override TOML from calibrated parameters."""
    parameter_set = session.core_settings["parameter_set"]
    params_vector = tuple(float(value) for value in parameter_set.vector_from(params))
    params_named = {
        str(name): float(value)
        for name, value in parameter_set.mapping_from(params_vector).items()
    }
    if candidate_label is not None:
        iteration_id = _sanitize_candidate_label(candidate_label)
    elif iteration_index is not None:
        iteration_id = f"iter_{int(iteration_index):04d}"
    else:
        raise ValueError("actualize_candidate requires iteration_index or candidate_label")
    candidate_run_id = f"{session.calibration_id}__{iteration_id}"
    candidate_root = (
        session.candidates_root or session.calibration_root / "runtime_candidates"
    ) / iteration_id
    candidate_config_path = candidate_root / "candidate_override.toml"

    override_payload: dict[str, Any] = {
        "base_config": str(session.simulation_config_path),
        "simulation": {"run_id": candidate_run_id},
    }
    if disable_display is None:
        disable_display = cfg.model_calibration.disable_display
    if disable_postprocess is None:
        disable_postprocess = cfg.model_calibration.disable_postprocess

    if disable_display:
        override_payload["display"] = {
            "enabled": False,
            "show": False,
            "save": False,
        }
    if disable_postprocess:
        override_payload["postprocess"] = {
            "enabled": False,
        }

    for parameter_cfg in cfg.model_calibration.parameter:
        target_path = _split_target_path(parameter_cfg.target)
        base_value = _lookup_nested_value(session.raw_simulation_toml, target_path)
        resolved_value = _apply_parameter_override(
            base_value=base_value,
            candidate_value=params_named[parameter_cfg.name],
            mode=parameter_cfg.mode,
        )
        _assign_nested_value(override_payload, target_path, resolved_value)

    _write_override_toml(candidate_config_path, override_payload)
    return CandidateRunRequest(
        session=session,
        iteration_id=iteration_id,
        candidate_run_id=candidate_run_id,
        candidate_root=candidate_root,
        candidate_config_path=candidate_config_path,
        params_vector=params_vector,
        params_named=params_named,
        override_payload=override_payload,
    )


def execute_best_candidate_rerun(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    result: Any,
    launcher_factory: Any,
) -> CandidateRunOutcome:
    """Rerun the best candidate without calibration-time output suppression."""
    params = getattr(result, "params_best", None)
    if params is None:
        params = getattr(result, "x_best")
    request = actualize_candidate(
        session=session,
        cfg=cfg,
        params=params,
        candidate_label="best",
        disable_display=False,
        disable_postprocess=False,
    )
    return execute_candidate_run(
        request=request,
        launcher_factory=launcher_factory,
        cfg=None,
    )


def execute_candidate_run(
    *,
    request: CandidateRunRequest,
    launcher_factory: Any,
    cfg: ModelCalibrationConfig | None = None,
) -> CandidateRunOutcome:
    """Execute one candidate simulation via a launcher factory."""
    try:
        launcher = launcher_factory(request.candidate_config_path)
        run_state = launcher.run()
    except Exception as exc:
        return CandidateRunOutcome(
            request=request,
            status="solver_run_failed",
            run_state=None,
            error_type=type(exc).__name__,
            error_message=f"{type(exc).__name__}: {exc}",
        )

    if cfg is not None and _objective_has_observations(cfg):
        try:
            objective_evaluation = evaluate_candidate_objective(
                cfg=cfg,
                run_state=run_state,
            )
        except Exception as exc:
            return CandidateRunOutcome(
                request=request,
                status="objective_evaluation_failed",
                run_state=run_state,
                objective_evaluation=None,
                error_type=type(exc).__name__,
                error_message=f"{type(exc).__name__}: {exc}",
            )
        return CandidateRunOutcome(
            request=request,
            status="objective_evaluated",
            run_state=run_state,
            objective_evaluation=objective_evaluation,
            error_type=None,
            error_message=None,
        )
    return CandidateRunOutcome(
        request=request,
        status="solver_run_succeeded",
        run_state=run_state,
        objective_evaluation=None,
        error_type=None,
        error_message=None,
    )


__all__ = (
    "actualize_candidate",
    "build_model_distribution_payload",
    "CandidateRunOutcome",
    "CandidateRunRequest",
    "IterationRecord",
    "PreparedCalibrationSession",
    "append_iteration_record",
    "detect_solver_families",
    "execute_best_candidate_rerun",
    "execute_candidate_run",
    "execute_model_distribution_reruns",
    "evaluate_candidate_objective",
    "finalize_calibration_session",
    "initialize_calibration_session",
    "ModelCalibrationObjectiveEvaluator",
    "persist_iteration_record",
    "persist_model_distribution",
    "prepare_calibration_session",
    "resolve_workspace_config",
    "serialize_calibration_result",
    "select_candidate_outputs",
    "select_model_distribution_samples",
    "update_session_manifest",
    "validate_objective_ready_for_calibration",
)
