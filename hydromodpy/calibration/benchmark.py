"""Legacy launcher-API bridge for twin calibration benchmarks.

Validation cases under ``validation_cases/calibration/`` and the tests in
``tests/validation/calibration/test_twin_*.py`` were written against the
pre-P09 ``ModelCalibrationLauncher`` and companion helpers located in
``hydromodpy.analysis.calibration.engine.*``. That tree has been removed
in favour of :mod:`hydromodpy.calibration`.

This module provides a drop-in reimplementation of the four public
symbols those tests rely on, built **on top of the new architecture**:

* :class:`ModelCalibrationLauncher` - loads a legacy
  ``[model_calibration]`` TOML, prepares a session on disk, and runs one
  full calibration loop using simple method implementations that wrap
  ``hydromodpy.Project`` + :func:`hydromodpy.simulation.execution.trial._set_by_path`.
* :class:`ModelCalibrationObjectiveEvaluator` - single-shot evaluator
  used by ``validation_cases.calibration.shared.runtime`` to score one
  candidate parameter vector.
* :func:`actualize_candidate` - materialize a candidate override TOML
  (inheriting from the target simulation config via ``base_config``) for
  an explicit parameter point.
* :func:`select_candidate_outputs` - read configured observables from a
  finished :class:`hydromodpy.core.state.run_state.WorkflowContext`.

The legacy TOML schema is considerably richer than the new
``[calibration]`` section. For the benchmark surface we only need:

- ``[model_calibration]`` top-level knobs (``simulation_config``,
  ``calibration_id``, ``disable_display``, ``disable_postprocess``,
  ``persist_model_distribution``);
- ``[[model_calibration.parameter]]`` list with ``name`` + ``target``
  dotted path (``mode`` = ``"replace"`` or ``"scale"``);
- ``[[model_calibration.output]]`` list with ``name`` + extraction
  hints + ``observed_values``;
- ``[[model_calibration.objective_block]]`` list with ``metric``,
  ``weight``, ``uses_outputs``, ``normalize_cost``;
- ``[calibration]`` with ``objective_metric`` and ``global_method``;
- ``[calibration_method.<method>]`` keyword arguments;
- ``[bounds]`` table ``{name: [low, high]}``.

Implementation strategy: parse the TOML ourselves (no Pydantic) and run
a simple dispatch into one of the supported methods
(``grid_search``, ``random_search``, ``cma_es``, ``simplex``,
``nelder_mead``, ``gp_mapping``, ``da_mh_gp``). The objective is a
weighted root-mean-square distance between the candidate outputs
(extracted via :func:`select_candidate_outputs`) and the observed
values from the TOML. Each candidate runs through
:class:`hydromodpy.Project` in headless mode.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from hydromodpy.calibration.objective import HIGHER_IS_BETTER, METRICS
from hydromodpy.core.config.toml_loader import load_toml_with_base_config

# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ParameterCfg:
    """One [[model_calibration.parameter]] entry (minimal shape)."""

    name: str
    target: str
    mode: str = "replace"  # "replace" | "scale"
    parameterization: str = "global_value"
    property: str | None = None
    lithology_key: str | None = None


@dataclass(frozen=True, slots=True)
class _OutputCfg:
    """One [[model_calibration.output]] entry."""

    name: str
    variable: str
    source: str = "runtime"
    support: str = "point"
    x: float | None = None
    y: float | None = None
    boundary_id: str | None = None
    time: str | None = "all"
    reducer: str | None = None
    observed_values: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class _ObjectiveBlockCfg:
    """One [[model_calibration.objective_block]] entry."""

    name: str
    metric: str = "rmse"
    weight: float = 1.0
    uses_outputs: tuple[str, ...] = ()
    normalize_cost: bool = True


@dataclass(frozen=True, slots=True)
class _ModelCalibrationCfg:
    """Parsed [model_calibration] section used by this bridge."""

    simulation_config: str
    calibration_id: str | None
    disable_display: bool
    disable_postprocess: bool
    rerun_best_with_outputs: bool
    persist_model_distribution: bool
    rerun_model_distribution_with_outputs: bool
    persist_iteration_history: bool
    persist_iteration_detail_level: str
    persist_calibration_report: bool
    resume_existing_session: bool
    reuse_persisted_iterations: bool
    parameter: tuple[_ParameterCfg, ...]
    output: tuple[_OutputCfg, ...]
    objective_block: tuple[_ObjectiveBlockCfg, ...]


@dataclass(frozen=True, slots=True)
class _LauncherCfg:
    """Top-level aggregate mirroring the legacy ``ModelCalibrationConfig``."""

    simulation_config_path: Path
    model_calibration: _ModelCalibrationCfg
    calibration: SimpleNamespace
    objective: SimpleNamespace
    bounds: dict[str, tuple[float, float]]
    calibration_method_kwargs: dict[str, dict[str, Any]]
    raw: dict[str, Any]

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.model_calibration.parameter)


def _parse_parameter(entry: Mapping[str, Any]) -> _ParameterCfg:
    return _ParameterCfg(
        name=str(entry["name"]).strip(),
        target=str(entry["target"]).strip(),
        mode=str(entry.get("mode", "replace")).strip().lower(),
        parameterization=str(entry.get("parameterization", "global_value")).strip().lower(),
        property=entry.get("property"),
        lithology_key=entry.get("lithology_key"),
    )


def _parse_output(entry: Mapping[str, Any]) -> _OutputCfg:
    observed_raw = entry.get("observed_values")
    observed = None if observed_raw is None else tuple(float(value) for value in observed_raw)
    return _OutputCfg(
        name=str(entry["name"]).strip(),
        variable=str(entry["variable"]).strip(),
        source=str(entry.get("source", "runtime")).strip().lower(),
        support=str(entry.get("support", "point")).strip().lower(),
        x=None if entry.get("x") is None else float(entry["x"]),
        y=None if entry.get("y") is None else float(entry["y"]),
        boundary_id=entry.get("boundary_id"),
        time=entry.get("time", "all"),
        reducer=entry.get("reducer"),
        observed_values=observed,
    )


def _parse_objective_block(entry: Mapping[str, Any]) -> _ObjectiveBlockCfg:
    return _ObjectiveBlockCfg(
        name=str(entry["name"]).strip(),
        metric=str(entry.get("metric", "rmse")).strip().lower(),
        weight=float(entry.get("weight", 1.0)),
        uses_outputs=tuple(str(item).strip() for item in entry.get("uses_outputs", [])),
        normalize_cost=bool(entry.get("normalize_cost", True)),
    )


def _parse_launcher_cfg(config_path: Path, raw: Mapping[str, Any]) -> _LauncherCfg:
    """Turn the raw TOML payload into a :class:`_LauncherCfg`."""
    model_calibration_section = dict(raw.get("model_calibration", {}))
    if "simulation_config" not in model_calibration_section:
        raise ValueError("Legacy [model_calibration] section requires a 'simulation_config' entry.")

    simulation_config_raw = str(model_calibration_section["simulation_config"])
    simulation_config_path = Path(simulation_config_raw)
    if not simulation_config_path.is_absolute():
        simulation_config_path = (config_path.parent / simulation_config_path).resolve()

    parameters = tuple(
        _parse_parameter(entry) for entry in model_calibration_section.get("parameter", [])
    )
    outputs = tuple(_parse_output(entry) for entry in model_calibration_section.get("output", []))
    objective_blocks = tuple(
        _parse_objective_block(entry)
        for entry in model_calibration_section.get("objective_block", [])
    )

    cfg_mc = _ModelCalibrationCfg(
        simulation_config=simulation_config_raw,
        calibration_id=model_calibration_section.get("calibration_id"),
        disable_display=bool(model_calibration_section.get("disable_display", True)),
        disable_postprocess=bool(model_calibration_section.get("disable_postprocess", True)),
        rerun_best_with_outputs=bool(
            model_calibration_section.get("rerun_best_with_outputs", False)
        ),
        persist_model_distribution=bool(
            model_calibration_section.get("persist_model_distribution", False)
        ),
        rerun_model_distribution_with_outputs=bool(
            model_calibration_section.get("rerun_model_distribution_with_outputs", False)
        ),
        persist_iteration_history=bool(
            model_calibration_section.get("persist_iteration_history", True)
        ),
        persist_iteration_detail_level=str(
            model_calibration_section.get("persist_iteration_detail_level", "minimal")
        ),
        persist_calibration_report=bool(
            model_calibration_section.get("persist_calibration_report", False)
        ),
        resume_existing_session=bool(
            model_calibration_section.get("resume_existing_session", False)
        ),
        reuse_persisted_iterations=bool(
            model_calibration_section.get("reuse_persisted_iterations", False)
        ),
        parameter=parameters,
        output=outputs,
        objective_block=objective_blocks,
    )

    calibration_section = dict(raw.get("calibration", {}))
    objective_section = dict(raw.get("objective", {}))
    calibration_ns = SimpleNamespace(
        objective_metric=str(calibration_section.get("objective_metric", "rmse")),
        global_method=str(calibration_section.get("global_method", "simplex")),
    )
    objective_ns = SimpleNamespace(
        transform=str(objective_section.get("transform", "identity")),
    )

    raw_bounds = dict(raw.get("bounds", {}))
    parsed_bounds: dict[str, tuple[float, float]] = {}
    for name, pair in raw_bounds.items():
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"bounds[{name!r}] must be a 2-value list")
        low = float(pair[0])
        high = float(pair[1])
        if low >= high:
            raise ValueError(f"bounds[{name!r}] lower must be < upper")
        parsed_bounds[str(name)] = (low, high)

    method_section = dict(raw.get("calibration_method", {}))
    method_kwargs: dict[str, dict[str, Any]] = {}
    for name, entry in method_section.items():
        if isinstance(entry, dict):
            method_kwargs[str(name)] = dict(entry)

    return _LauncherCfg(
        simulation_config_path=simulation_config_path,
        model_calibration=cfg_mc,
        calibration=calibration_ns,
        objective=objective_ns,
        bounds=parsed_bounds,
        calibration_method_kwargs=method_kwargs,
        raw=dict(raw),
    )


# ---------------------------------------------------------------------------
# ParameterSet helper (vector <-> mapping for the launcher-facing API)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ParameterSet:
    """Minimal ``parameter_set`` replacement used by the legacy surface.

    ``core_settings['parameter_set']`` exposed ``.vector_from(mapping|vector)``
    and ``.mapping_from(vector)`` helpers - keep the exact same contract so
    ``actualize_candidate`` / :class:`ModelCalibrationObjectiveEvaluator`
    keep working unmodified.
    """

    names: tuple[str, ...]
    bounds: dict[str, tuple[float, float]]

    def vector_from(self, params: Any) -> tuple[float, ...]:
        if isinstance(params, Mapping):
            return tuple(float(params[name]) for name in self.names)
        return tuple(float(value) for value in np.asarray(params, dtype=float).ravel())

    def mapping_from(self, vector: Any) -> dict[str, float]:
        values = tuple(float(value) for value in np.asarray(vector, dtype=float).ravel())
        if len(values) != len(self.names):
            raise ValueError(
                f"Parameter vector length {len(values)} != number of names {len(self.names)}"
            )
        return {str(name): float(value) for name, value in zip(self.names, values, strict=True)}

    @property
    def lower(self) -> np.ndarray:
        return np.asarray([float(self.bounds[name][0]) for name in self.names], dtype=float)

    @property
    def upper(self) -> np.ndarray:
        return np.asarray([float(self.bounds[name][1]) for name in self.names], dtype=float)


# ---------------------------------------------------------------------------
# Prepared session + candidate request / evaluation datatypes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreparedCalibrationSession:
    """Prepared on-disk scaffold for one calibration session.

    Minimal subset of the legacy dataclass. Fields kept so that existing
    calibration validation code (``validation_cases/calibration/``) can
    read them unmodified.
    """

    config_path: Path
    simulation_config_path: Path
    raw_simulation_toml: dict[str, Any]
    calibration_id: str
    calibration_root: Path
    session_manifest_path: Path
    iteration_history_path: Path
    core_settings: dict[str, Any]
    parameter_names: tuple[str, ...]
    candidates_root: Path | None = None

    def to_summary(self) -> dict[str, Any]:
        """Return a JSON-friendly summary with path-fields stringified."""
        return {
            "config_path": str(self.config_path),
            "simulation_config_path": str(self.simulation_config_path),
            "calibration_id": str(self.calibration_id),
            "calibration_root": str(self.calibration_root),
            "session_manifest_path": str(self.session_manifest_path),
            "iteration_history_path": str(self.iteration_history_path),
            "core_settings": {
                "method": str(self.core_settings.get("method", "")),
                "objective_metric": str(self.core_settings.get("objective_metric", "rmse")),
                "method_kwargs": dict(self.core_settings.get("method_kwargs", {})),
            },
            "parameter_names": list(self.parameter_names),
            "candidates_root": (
                None if self.candidates_root is None else str(self.candidates_root)
            ),
        }


@dataclass(frozen=True, slots=True)
class CandidateRunRequest:
    """Materialized candidate override for one iteration."""

    session: PreparedCalibrationSession
    iteration_id: str
    candidate_run_id: str
    candidate_root: Path
    candidate_config_path: Path
    params_vector: tuple[float, ...]
    params_named: dict[str, float]


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """One candidate evaluation outcome used by reference-objective scans."""

    total_cost: float | None
    status: str
    failure_reason: str | None = None
    block_costs: dict[str, float] = field(default_factory=dict)
    blocks: tuple[Any, ...] = ()


# ---------------------------------------------------------------------------
# Helpers for the candidate override TOML
# ---------------------------------------------------------------------------


def _sanitize_candidate_label(label: str) -> str:
    """Return one filesystem-safe candidate label (legacy parity)."""
    text = str(label).strip().lower()
    if not text:
        raise ValueError("candidate_label cannot be empty")
    return re.sub(r"[^a-z0-9_.-]+", "_", text)


def _dump_toml_value(value: Any, indent: int = 0) -> str:
    """Render a Python value as TOML. Limited but covers the override shape."""
    del indent  # reserved for future multiline rendering
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise ValueError(f"Cannot write non-finite float to TOML: {value}")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return '""'
    if isinstance(value, (list, tuple)):
        items = [_dump_toml_value(item) for item in value]
        return "[" + ", ".join(items) + "]"
    if isinstance(value, Mapping):
        keys = list(value.keys())
        inline_parts = [f"{key} = {_dump_toml_value(value[key])}" for key in keys]
        return "{ " + ", ".join(inline_parts) + " }"
    raise TypeError(f"Unsupported TOML value: {value!r} ({type(value)})")


def _write_toml_payload(path: Path, payload: Mapping[str, Any]) -> None:
    """Write an override TOML tree. Respects dotted-section nesting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def _emit_block(section: str, block: Mapping[str, Any]) -> None:
        scalars: list[tuple[str, Any]] = []
        tables: list[tuple[str, Mapping[str, Any]]] = []
        for key, value in block.items():
            if isinstance(value, Mapping):
                tables.append((key, value))
            else:
                scalars.append((key, value))
        if section:
            lines.append(f"[{section}]")
        for key, value in scalars:
            lines.append(f"{key} = {_dump_toml_value(value)}")
        if section:
            lines.append("")
        for key, value in tables:
            nested = f"{section}.{key}" if section else key
            _emit_block(nested, value)

    # Top-level scalars first.
    top_scalars = {k: v for k, v in payload.items() if not isinstance(v, Mapping)}
    top_tables = {k: v for k, v in payload.items() if isinstance(v, Mapping)}
    for key, value in top_scalars.items():
        lines.append(f"{key} = {_dump_toml_value(value)}")
    if top_scalars and top_tables:
        lines.append("")
    for key, value in top_tables.items():
        _emit_block(key, value)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _lookup_nested(payload: Mapping[str, Any], dotted: Sequence[str]) -> Any:
    """Look up a dotted path, returning ``None`` when missing."""
    target: Any = payload
    for part in dotted:
        if isinstance(target, Mapping) and part in target:
            target = target[part]
        else:
            return None
    return target


def _assign_nested(payload: dict[str, Any], dotted: Sequence[str], value: Any) -> None:
    """Assign a value at a dotted path, creating intermediate dicts."""
    target = payload
    for part in dotted[:-1]:
        sub = target.get(part)
        if not isinstance(sub, dict):
            sub = {}
            target[part] = sub
        target = sub
    target[dotted[-1]] = value


def _split_target_path(target: str) -> tuple[str, ...]:
    """Split a dotted target path, matching the legacy alias resolution."""
    return tuple(part for part in str(target).strip().split(".") if part)


def _apply_parameter_mode(*, base_value: Any, candidate_value: float, mode: str) -> float:
    """Apply the ``"replace"``/``"scale"`` mode to a candidate value."""
    if mode == "scale":
        if base_value is None:
            raise ValueError(
                "scale mode requires a baseline value; target path unresolved in simulation TOML."
            )
        try:
            base = float(base_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"scale mode requires numeric base value, got {base_value!r}") from exc
        return float(base * float(candidate_value))
    return float(candidate_value)


# ---------------------------------------------------------------------------
# Launcher wrapper + cfg namespace
# ---------------------------------------------------------------------------


def _build_cfg_namespace(cfg: _LauncherCfg) -> SimpleNamespace:
    """Return a ``launcher.cfg`` namespace with the shape the legacy API
    consumers rely on.

    The legacy API exposed ``cfg.model_calibration.parameter`` as a list
    of objects with ``.name``, ``.target``, ``.mode``; we replicate the
    exact same shape via dataclasses + a namespace wrapper.
    """
    mc_ns = SimpleNamespace(
        simulation_config=cfg.model_calibration.simulation_config,
        calibration_id=cfg.model_calibration.calibration_id,
        disable_display=cfg.model_calibration.disable_display,
        disable_postprocess=cfg.model_calibration.disable_postprocess,
        rerun_best_with_outputs=cfg.model_calibration.rerun_best_with_outputs,
        persist_model_distribution=cfg.model_calibration.persist_model_distribution,
        rerun_model_distribution_with_outputs=cfg.model_calibration.rerun_model_distribution_with_outputs,
        persist_iteration_history=cfg.model_calibration.persist_iteration_history,
        persist_iteration_detail_level=cfg.model_calibration.persist_iteration_detail_level,
        persist_calibration_report=cfg.model_calibration.persist_calibration_report,
        resume_existing_session=cfg.model_calibration.resume_existing_session,
        reuse_persisted_iterations=cfg.model_calibration.reuse_persisted_iterations,
        parameter=list(cfg.model_calibration.parameter),
        output=list(cfg.model_calibration.output),
        objective_block=list(cfg.model_calibration.objective_block),
    )
    return SimpleNamespace(
        model_calibration=mc_ns,
        calibration=cfg.calibration,
        objective=cfg.objective,
        bounds=dict(cfg.bounds),
        parameter_names=cfg.parameter_names,
        simulation_config_path=cfg.simulation_config_path,
        calibration_method_kwargs=dict(cfg.calibration_method_kwargs),
        raw=dict(cfg.raw),
    )


# ---------------------------------------------------------------------------
# Objective computation
# ---------------------------------------------------------------------------


def _observed_vector(
    block_cfg: _ObjectiveBlockCfg,
    outputs_by_name: Mapping[str, _OutputCfg],
) -> np.ndarray:
    """Concatenate the observed values for the outputs referenced by a block."""
    parts: list[np.ndarray] = []
    for output_name in block_cfg.uses_outputs:
        output_cfg = outputs_by_name[output_name]
        if output_cfg.observed_values is None:
            raise ValueError(
                f"Output '{output_name}' used by block '{block_cfg.name}' "
                "does not define observed_values"
            )
        parts.append(np.asarray(output_cfg.observed_values, dtype=float).ravel())
    return np.concatenate(parts) if parts else np.asarray([], dtype=float)


def _simulated_vector(
    block_cfg: _ObjectiveBlockCfg,
    selected: Mapping[str, Sequence[float]],
) -> np.ndarray:
    """Concatenate the simulated values referenced by a block."""
    parts: list[np.ndarray] = []
    for output_name in block_cfg.uses_outputs:
        values = selected.get(output_name)
        if values is None:
            raise ValueError(f"Missing simulated values for output '{output_name}'")
        parts.append(np.asarray(values, dtype=float).ravel())
    return np.concatenate(parts) if parts else np.asarray([], dtype=float)


def _metric_cost(observed: np.ndarray, simulated: np.ndarray, metric: str) -> float:
    """Compute one metric cost (lower is better) between observed and simulated."""
    metric_key = str(metric).strip().lower()
    fn = METRICS.get(metric_key)
    if fn is None:
        raise ValueError(f"Unsupported metric '{metric}'. Available: {sorted(METRICS)}")
    n = min(len(observed), len(simulated))
    if n == 0:
        return float("inf")
    value = float(fn(observed[:n], simulated[:n]))
    if math.isnan(value):
        return float("inf")
    return (1.0 - value) if metric_key in HIGHER_IS_BETTER else value


def _reference_scale(observed: np.ndarray) -> float:
    """Return a reference scale used to normalise a block's raw cost."""
    if observed.size == 0:
        return 1.0
    arr = np.asarray(observed, dtype=float)
    std = float(np.nanstd(arr))
    if std > 0.0 and math.isfinite(std):
        return std
    mean_abs = float(np.mean(np.abs(arr)))
    return mean_abs if mean_abs > 0.0 else 1.0


@dataclass(frozen=True, slots=True)
class _BlockEvaluation:
    """Compact block-level objective record used by :class:`CandidateEvaluation`."""

    name: str
    raw_cost: float
    normalized_cost: float
    reference_scale: float
    n_values: int


def _compute_composite_objective(
    *,
    cfg: _LauncherCfg,
    selected: Mapping[str, Sequence[float]],
) -> tuple[float, dict[str, float], tuple[_BlockEvaluation, ...]]:
    """Compute the weighted composite cost from selected outputs."""
    outputs_by_name = {o.name: o for o in cfg.model_calibration.output}
    blocks: list[_BlockEvaluation] = []
    raw_weights: list[float] = []
    costs: list[float] = []
    for block_cfg in cfg.model_calibration.objective_block:
        observed = _observed_vector(block_cfg, outputs_by_name)
        simulated = _simulated_vector(block_cfg, selected)
        raw_cost = _metric_cost(observed, simulated, block_cfg.metric)
        ref_scale = _reference_scale(observed) if block_cfg.normalize_cost else 1.0
        normalized = raw_cost / ref_scale if ref_scale > 0.0 else raw_cost
        blocks.append(
            _BlockEvaluation(
                name=block_cfg.name,
                raw_cost=float(raw_cost),
                normalized_cost=float(normalized),
                reference_scale=float(ref_scale),
                n_values=int(observed.size),
            )
        )
        raw_weights.append(float(block_cfg.weight))
        costs.append(float(normalized))
    if not blocks:
        return float("inf"), {}, ()
    weights = np.asarray(raw_weights, dtype=float)
    total_weight = float(weights.sum())
    if total_weight <= 0.0:
        raise ValueError("Composite objective requires a strictly positive total weight")
    normalized_weights = weights / total_weight
    total = float(np.sum(normalized_weights * np.asarray(costs, dtype=float)))
    block_costs = {b.name: float(b.normalized_cost) for b in blocks}
    return total, block_costs, tuple(blocks)


# ---------------------------------------------------------------------------
# Output selection from a WorkflowContext (post-Project.run)
# ---------------------------------------------------------------------------


def _simulation_output_dir(run_state: Any) -> Path | None:
    """Return the first flow simulation output directory in the context."""
    registry = getattr(run_state, "execution", None)
    if registry is None:
        return None
    output_dirs = getattr(registry, "output_dirs_by_run_id", {}) or {}
    plan = getattr(registry, "simulation_plan", None)
    if plan is not None:
        for run in getattr(plan, "runs", ()):
            if run.process_type == "flow" and run.id in output_dirs:
                return Path(output_dirs[run.id])
    if output_dirs:
        return Path(next(iter(output_dirs.values())))
    return None


def _model_name(run_state: Any) -> str | None:
    """Return the first flow model's name when available."""
    registry = getattr(run_state, "execution", None)
    if registry is None:
        return None
    models = getattr(registry, "models_by_run_id", {}) or {}
    if not models:
        return None
    model = next(iter(models.values()))
    return getattr(model, "model_name", None) or getattr(model, "name", None)


def _extract_outlet_discharge(
    output_dir: Path,
    model_name: str,
    *,
    boundary_keys: tuple[str, ...] = ("drain", "drains", "drn", "chd"),
) -> np.ndarray | None:
    """Sum boundary/outlet discharge per timestep from a MODFLOW CBC file."""
    try:
        import flopy.utils.binaryfile as bf
    except Exception:
        return None
    for extension in ("cbc", "cbb"):
        cbc_path = output_dir / f"{model_name}.{extension}"
        if cbc_path.exists():
            break
    else:
        return None
    cbb = bf.CellBudgetFile(str(cbc_path))
    try:
        record_names = [r.decode().strip().lower() for r in cbb.get_unique_record_names()]
        record_name = None
        for key in boundary_keys:
            for rec in record_names:
                if key in rec:
                    record_name = rec
                    break
            if record_name is not None:
                break
        if record_name is None:
            return None
        times = cbb.get_times()
        kstpkpers = cbb.get_kstpkper()
        values = np.zeros(len(times), dtype=float)
        for t, (totim, ksk) in enumerate(zip(times, kstpkpers, strict=False)):
            try:
                data = cbb.get_data(text=record_name, kstpkper=ksk, totim=totim, full3D=True)
            except Exception:
                continue
            if not data:
                continue
            arr = np.asarray(data[0], dtype=float)
            values[t] = float(np.abs(np.minimum(arr, 0.0)).sum())
    finally:
        cbb.close()
    return values


def _extract_head_timeseries(
    output_dir: Path,
    model_name: str,
    *,
    x: float,
    y: float,
    mesh: Any,
) -> np.ndarray | None:
    """Extract a head timeseries at the cell closest to (x, y)."""
    try:
        import flopy.utils.binaryfile as bf
    except Exception:
        return None
    hds_path = output_dir / f"{model_name}.hds"
    if not hds_path.exists():
        return None
    # Locate cell index closest to (x, y) on the mesh.
    cell_index = _nearest_cell_index(mesh, x=x, y=y)
    if cell_index is None:
        return None
    k, i, j = cell_index
    hf = bf.HeadFile(str(hds_path))
    try:
        times = hf.get_times()
        values = np.full(len(times), np.nan, dtype=float)
        for t, totim in enumerate(times):
            try:
                head = hf.get_data(totim=totim)
                values[t] = float(head[k, i, j])
            except Exception:
                pass
        values[np.abs(values) > 1e6] = np.nan
    finally:
        hf.close()
    return values


def _nearest_cell_index(mesh: Any, *, x: float, y: float) -> tuple[int, int, int] | None:
    """Return ``(layer, row, col)`` of the cell closest to ``(x, y)``."""
    # The mesh layout in hydromodpy varies between solvers; pull out the
    # cell centroids and fall back gracefully when unavailable.
    centroids = getattr(mesh, "cell_centroids", None)
    if centroids is None:
        centroids = getattr(mesh, "centroids", None)
    if centroids is None:
        return None
    arr = np.asarray(centroids, dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 2:
        return None
    distances = np.hypot(arr[:, 0] - float(x), arr[:, 1] - float(y))
    flat_index = int(np.argmin(distances))
    shape = getattr(mesh, "shape", None)
    if shape is None or len(shape) < 2:
        # 1D fallback - treat as (0, 0, flat_index)
        return (0, 0, flat_index)
    _, n_rows, n_cols = shape if len(shape) == 3 else (1, *shape)
    layer = 0
    row = flat_index // n_cols
    col = flat_index % n_cols
    return (layer, int(row), int(col))


def select_candidate_outputs(
    *,
    cfg: Any,
    run_state: Any,
    session: PreparedCalibrationSession | None = None,  # noqa: ARG001
) -> dict[str, tuple[float, ...]]:
    """Extract configured simulated observables from a finished run state.

    Best-effort implementation on top of the new architecture. It inspects
    ``run_state.execution`` (populated by :class:`hydromodpy.Project.run`)
    to locate the simulation output directory and the flow model name, then
    reads the MODFLOW binary files (``.cbc`` / ``.hds``) for each output
    declared in ``cfg.model_calibration.output``.

    Returns the legacy dict format ``{output_name: tuple[float, ...]}``.
    """
    # Accept both our internal cfg + the launcher namespace shape.
    model_calibration = getattr(cfg, "model_calibration", None)
    if model_calibration is None:
        return {}
    outputs = tuple(getattr(model_calibration, "output", ()))
    output_dir = _simulation_output_dir(run_state)
    model_name = _model_name(run_state)
    mesh = getattr(getattr(run_state, "setup", None), "mesh_planar", None)

    selected: dict[str, tuple[float, ...]] = {}
    for output_cfg in outputs:
        variable = str(output_cfg.variable).strip().lower()
        support = str(output_cfg.support).strip().lower()
        values: np.ndarray | None = None
        if output_dir is not None and model_name is not None:
            if variable == "outlet_discharge" or support == "boundary":
                values = _extract_outlet_discharge(output_dir, model_name)
            elif variable in {"watertable_elevation", "head"} and support == "point":
                values = _extract_head_timeseries(
                    output_dir,
                    model_name,
                    x=float(output_cfg.x) if output_cfg.x is not None else 0.0,
                    y=float(output_cfg.y) if output_cfg.y is not None else 0.0,
                    mesh=mesh,
                )
        if values is None or values.size == 0:
            # Fall back to observed values' length filled with NaNs so the
            # evaluator still receives a vector of the right shape.
            observed = output_cfg.observed_values
            length = len(observed) if observed is not None else 1
            values = np.full(length, np.nan, dtype=float)
        selected[output_cfg.name] = tuple(float(value) for value in np.asarray(values).ravel())
    return selected


# ---------------------------------------------------------------------------
# actualize_candidate
# ---------------------------------------------------------------------------


def actualize_candidate(
    *,
    session: PreparedCalibrationSession,
    cfg: Any,
    params: Mapping[str, float] | Sequence[float],
    iteration_index: int | None = None,
    candidate_label: str | None = None,
    disable_postprocess: bool | None = None,
    disable_display: bool | None = None,
) -> CandidateRunRequest:
    """Materialize one candidate TOML under ``session.candidates_root``.

    The override inherits the target simulation config via
    ``base_config = session.simulation_config_path`` and rewrites each
    configured parameter by dotted target path.
    """
    model_calibration = getattr(cfg, "model_calibration", None)
    if model_calibration is None:
        raise ValueError("cfg must expose .model_calibration (with parameter/output/...)")
    parameter_set: _ParameterSet = session.core_settings["parameter_set"]
    vector = parameter_set.vector_from(params)
    params_named = parameter_set.mapping_from(vector)

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
    # The strict binary workspace resolver requires either [workspace] root,
    # HYDROMODPY_WORKSPACE, or a canonical `<workspace>/projects/<name>/`
    # scaffold. Benchmark configs ship under a flat benchmark_root so we
    # inject an explicit workspace root here instead of relying on env vars.
    workspace_section = dict(session.raw_simulation_toml.get("workspace", {}))
    if not workspace_section.get("root"):
        workspace_section["root"] = str(session.simulation_config_path.parent)
    override_payload["workspace"] = workspace_section
    if disable_display is None:
        disable_display = bool(model_calibration.disable_display)
    if disable_postprocess is None:
        disable_postprocess = bool(model_calibration.disable_postprocess)
    if disable_display:
        override_payload["display"] = {"enabled": False, "show": False, "save": False}
    if disable_postprocess:
        override_payload["postprocess"] = {"enabled": False}

    for parameter_cfg in model_calibration.parameter:
        dotted = _split_target_path(parameter_cfg.target)
        base_value = _lookup_nested(session.raw_simulation_toml, dotted)
        resolved = _apply_parameter_mode(
            base_value=base_value,
            candidate_value=float(params_named[parameter_cfg.name]),
            mode=str(parameter_cfg.mode).strip().lower(),
        )
        _assign_nested(override_payload, dotted, resolved)

    _write_toml_payload(candidate_config_path, override_payload)

    return CandidateRunRequest(
        session=session,
        iteration_id=iteration_id,
        candidate_run_id=candidate_run_id,
        candidate_root=candidate_root,
        candidate_config_path=candidate_config_path,
        params_vector=vector,
        params_named=params_named,
    )


# ---------------------------------------------------------------------------
# ModelCalibrationObjectiveEvaluator
# ---------------------------------------------------------------------------


class ModelCalibrationObjectiveEvaluator:
    """Single-shot evaluator for one parameter dict.

    Used by ``validation_cases.calibration.shared.runtime`` when building
    the non-regular reference-objective payload. It delegates to
    :func:`actualize_candidate` + :class:`hydromodpy.project.Project` and
    computes the configured composite objective.
    """

    def __init__(
        self,
        *,
        session: PreparedCalibrationSession,
        cfg: Any,
        iteration_start: int = 1,
        record_callback: Callable[[Any], None] | None = None,
        launcher_factory: Any = None,
    ) -> None:
        self.session = session
        self.cfg = cfg
        self._next_iteration = int(iteration_start)
        self._record_callback = record_callback
        self._launcher_factory = launcher_factory  # accepted for parity; unused
        self._evaluations: list[CandidateEvaluation] = []

    def evaluate(self, params: Mapping[str, float]) -> CandidateEvaluation:
        """Run one candidate simulation and score it."""
        iteration_index = self._next_iteration
        self._next_iteration += 1
        try:
            request = actualize_candidate(
                session=self.session,
                cfg=self.cfg,
                params=params,
                iteration_index=iteration_index,
            )
        except Exception as exc:
            evaluation = CandidateEvaluation(
                total_cost=float("inf"),
                status="parameter_injection_failed",
                failure_reason=f"{type(exc).__name__}: {exc}",
                block_costs={},
                blocks=(),
            )
            self._evaluations.append(evaluation)
            if self._record_callback is not None:
                self._record_callback(evaluation)
            return evaluation

        # Late import to avoid a hard dependency at import time.
        from hydromodpy.project import Project

        project = Project(request.candidate_config_path, headless=True)
        try:
            project.run()
            run_state = project._ctx
        except Exception as exc:
            project.close()
            evaluation = CandidateEvaluation(
                total_cost=float("inf"),
                status="simulation_failed",
                failure_reason=f"{type(exc).__name__}: {exc}",
                block_costs={},
                blocks=(),
            )
            self._evaluations.append(evaluation)
            if self._record_callback is not None:
                self._record_callback(evaluation)
            return evaluation

        try:
            selected = select_candidate_outputs(
                cfg=self.cfg,
                run_state=run_state,
                session=self.session,
            )
            total, block_costs, blocks = _compute_composite_objective(
                cfg=_LauncherCfg(
                    simulation_config_path=self.session.simulation_config_path,
                    model_calibration=_ModelCalibrationCfg(
                        **{
                            k: getattr(self.cfg.model_calibration, k)
                            for k in _ModelCalibrationCfg.__dataclass_fields__
                        }
                    ),
                    calibration=self.cfg.calibration,
                    objective=self.cfg.objective,
                    bounds=dict(getattr(self.cfg, "bounds", {})),
                    calibration_method_kwargs=dict(
                        getattr(self.cfg, "calibration_method_kwargs", {})
                    ),
                    raw=dict(getattr(self.cfg, "raw", {})),
                ),
                selected=selected,
            )
            evaluation = CandidateEvaluation(
                total_cost=float(total) if math.isfinite(total) else None,
                status="objective_evaluated",
                failure_reason=None,
                block_costs=dict(block_costs),
                blocks=blocks,
            )
        except Exception as exc:
            evaluation = CandidateEvaluation(
                total_cost=float("inf"),
                status="objective_evaluation_failed",
                failure_reason=f"{type(exc).__name__}: {exc}",
                block_costs={},
                blocks=(),
            )
        finally:
            project.close()

        self._evaluations.append(evaluation)
        if self._record_callback is not None:
            self._record_callback(evaluation)
        return evaluation


# ---------------------------------------------------------------------------
# Calibration driver (method dispatch)
# ---------------------------------------------------------------------------


def _latin_hypercube(rng: np.random.Generator, n: int, dim: int) -> np.ndarray:
    """Generate a Latin-hypercube sample in the unit hypercube."""
    unit = np.empty((n, dim), dtype=float)
    for index in range(dim):
        base = (np.arange(n, dtype=float) + rng.random(n)) / float(max(1, n))
        rng.shuffle(base)
        unit[:, index] = base
    return unit


def _driver_grid_search(
    *,
    cost_fn: Callable[[np.ndarray], tuple[float, np.ndarray]],
    lower: np.ndarray,
    upper: np.ndarray,
    kwargs: Mapping[str, Any],
) -> tuple[np.ndarray, float, int]:
    n_per_dim = int(kwargs.get("n_per_dim", 5))
    dim = lower.size
    axes = [np.linspace(lower[i], upper[i], n_per_dim) for i in range(dim)]
    best_cost = float("inf")
    best_vector: np.ndarray | None = None
    n_eval = 0
    import itertools

    for point in itertools.product(*axes):
        vector = np.asarray(point, dtype=float)
        cost, _vec = cost_fn(vector)
        n_eval += 1
        if math.isfinite(cost) and cost < best_cost:
            best_cost = cost
            best_vector = vector
    if best_vector is None:
        best_vector = 0.5 * (lower + upper)
    return best_vector, best_cost, n_eval


def _driver_random_search(
    *,
    cost_fn: Callable[[np.ndarray], tuple[float, np.ndarray]],
    lower: np.ndarray,
    upper: np.ndarray,
    kwargs: Mapping[str, Any],
) -> tuple[np.ndarray, float, int]:
    n_samples = int(kwargs.get("n_samples", 20))
    seed = kwargs.get("seed")
    rng = np.random.default_rng(None if seed is None else int(seed))
    best_cost = float("inf")
    best_vector: np.ndarray | None = None
    for _ in range(max(1, n_samples)):
        unit = rng.random(lower.size)
        vector = lower + unit * (upper - lower)
        cost, _ = cost_fn(vector)
        if math.isfinite(cost) and cost < best_cost:
            best_cost = cost
            best_vector = vector
    if best_vector is None:
        best_vector = 0.5 * (lower + upper)
    return best_vector, best_cost, int(max(1, n_samples))


def _driver_cma_es(
    *,
    cost_fn: Callable[[np.ndarray], tuple[float, np.ndarray]],
    lower: np.ndarray,
    upper: np.ndarray,
    kwargs: Mapping[str, Any],
) -> tuple[np.ndarray, float, int]:
    try:
        import cma  # type: ignore[import-not-found]
    except Exception as exc:
        raise ImportError(
            "The 'cma' package is required for the cma_es method; install via pip install cma."
        ) from exc
    sigma0 = float(kwargs.get("sigma0", 0.25))
    popsize = int(kwargs.get("popsize", 6))
    max_evaluations = int(kwargs.get("max_evaluations", 30))
    seed = kwargs.get("seed")
    normalize = bool(kwargs.get("normalize", True))
    x0 = 0.5 * (lower + upper)
    if normalize:
        span = upper - lower
        span = np.where(span > 0.0, span, 1.0)
        x0_t = (x0 - lower) / span
        lower_t = np.zeros_like(lower)
        upper_t = np.ones_like(upper)

        def _to_physical(x: np.ndarray) -> np.ndarray:
            return lower + np.clip(x, 0.0, 1.0) * span

        x0_start = x0_t
        bounds_t = [lower_t.tolist(), upper_t.tolist()]
    else:

        def _to_physical(x: np.ndarray) -> np.ndarray:
            return np.clip(x, lower, upper)

        x0_start = x0
        bounds_t = [lower.tolist(), upper.tolist()]

    options = {
        "popsize": popsize,
        "maxfevals": max_evaluations,
        "bounds": bounds_t,
        "verbose": -9,
    }
    if seed is not None:
        options["seed"] = int(seed)
    es = cma.CMAEvolutionStrategy(x0_start.tolist(), float(sigma0), options)
    best_cost = float("inf")
    best_vector: np.ndarray | None = None
    n_eval = 0
    while not es.stop() and n_eval < max_evaluations:
        xs = es.ask()
        costs: list[float] = []
        for x in xs:
            physical = _to_physical(np.asarray(x, dtype=float))
            cost, _ = cost_fn(physical)
            costs.append(cost if math.isfinite(cost) else 1e12)
            n_eval += 1
            if math.isfinite(cost) and cost < best_cost:
                best_cost = cost
                best_vector = physical.copy()
            if n_eval >= max_evaluations:
                break
        es.tell(xs[: len(costs)], costs)
    if best_vector is None:
        best_vector = x0
    return best_vector, best_cost, int(n_eval)


def _driver_simplex(
    *,
    cost_fn: Callable[[np.ndarray], tuple[float, np.ndarray]],
    lower: np.ndarray,
    upper: np.ndarray,
    kwargs: Mapping[str, Any],
) -> tuple[np.ndarray, float, int]:
    from scipy.optimize import minimize

    max_iter = int(kwargs.get("max_iter", kwargs.get("maxiter", 30)))
    max_fun = int(kwargs.get("max_fun", max_iter))
    xtol = float(kwargs.get("xtol", 1e-4))
    ftol = float(kwargs.get("ftol", 1e-4))
    x0 = 0.5 * (lower + upper)
    state = {"best_cost": float("inf"), "best_vector": x0.copy(), "n_eval": 0}

    def _obj(x: np.ndarray) -> float:
        x_clipped = np.clip(np.asarray(x, dtype=float), lower, upper)
        cost, _ = cost_fn(x_clipped)
        state["n_eval"] += 1
        if math.isfinite(cost) and cost < state["best_cost"]:
            state["best_cost"] = cost
            state["best_vector"] = x_clipped.copy()
        return cost if math.isfinite(cost) else 1e12

    minimize(
        _obj,
        x0,
        method="Nelder-Mead",
        options={"maxiter": max_iter, "maxfev": max_fun, "xatol": xtol, "fatol": ftol},
    )
    return state["best_vector"], state["best_cost"], int(state["n_eval"])


def _driver_nelder_mead(
    *,
    cost_fn: Callable[[np.ndarray], tuple[float, np.ndarray]],
    lower: np.ndarray,
    upper: np.ndarray,
    kwargs: Mapping[str, Any],
) -> tuple[np.ndarray, float, int]:
    return _driver_simplex(cost_fn=cost_fn, lower=lower, upper=upper, kwargs=kwargs)


def _driver_gp_mapping(
    *,
    cost_fn: Callable[[np.ndarray], tuple[float, np.ndarray]],
    lower: np.ndarray,
    upper: np.ndarray,
    kwargs: Mapping[str, Any],
) -> tuple[np.ndarray, float, int]:
    """Simple GP/Latin-hypercube hybrid standing in for the legacy gp_mapping."""
    n_init = int(kwargs.get("n_init", 8))
    n_refine = int(kwargs.get("n_refine", 3))
    batch_size = max(1, int(kwargs.get("batch_size", 1)))
    seed = kwargs.get("seed")
    rng = np.random.default_rng(None if seed is None else int(seed))
    unit = _latin_hypercube(rng, n_init, lower.size)
    best_cost = float("inf")
    best_vector: np.ndarray | None = None
    n_eval = 0
    for row in unit:
        vector = lower + row * (upper - lower)
        cost, _ = cost_fn(vector)
        n_eval += 1
        if math.isfinite(cost) and cost < best_cost:
            best_cost = cost
            best_vector = vector
    # Refinement phase: sample around the best point.
    for _ in range(max(0, n_refine * batch_size)):
        if best_vector is None:
            center = 0.5 * (lower + upper)
        else:
            center = best_vector
        perturb = rng.normal(0.0, 0.1 * (upper - lower))
        vector = np.clip(center + perturb, lower, upper)
        cost, _ = cost_fn(vector)
        n_eval += 1
        if math.isfinite(cost) and cost < best_cost:
            best_cost = cost
            best_vector = vector
    if best_vector is None:
        best_vector = 0.5 * (lower + upper)
    return best_vector, best_cost, int(n_eval)


def _driver_da_mh_gp(
    *,
    cost_fn: Callable[[np.ndarray], tuple[float, np.ndarray]],
    lower: np.ndarray,
    upper: np.ndarray,
    kwargs: Mapping[str, Any],
) -> tuple[np.ndarray, float, int]:
    """Very compact Metropolis-Hastings stand-in for da_mh_gp."""
    n_samples = int(kwargs.get("n_samples", 48))
    n_init = int(kwargs.get("n_init", 8))
    sigma_noise = float(kwargs.get("sigma_noise", 0.1))
    proposal_scale = float(kwargs.get("proposal_scale", 0.1))
    seed = kwargs.get("seed")
    rng = np.random.default_rng(None if seed is None else int(seed))
    unit = _latin_hypercube(rng, n_init, lower.size)
    best_cost = float("inf")
    best_vector: np.ndarray | None = None
    n_eval = 0
    current_vector: np.ndarray | None = None
    current_cost = float("inf")
    for row in unit:
        vector = lower + row * (upper - lower)
        cost, _ = cost_fn(vector)
        n_eval += 1
        if math.isfinite(cost) and cost < best_cost:
            best_cost = cost
            best_vector = vector
        if math.isfinite(cost) and cost < current_cost:
            current_cost = cost
            current_vector = vector.copy()
    if current_vector is None:
        current_vector = 0.5 * (lower + upper)
        current_cost, _ = cost_fn(current_vector)
        n_eval += 1
    for _ in range(max(0, n_samples)):
        perturb = rng.normal(0.0, proposal_scale * (upper - lower))
        proposal = np.clip(current_vector + perturb, lower, upper)
        cost, _ = cost_fn(proposal)
        n_eval += 1
        if math.isfinite(cost) and cost < best_cost:
            best_cost = cost
            best_vector = proposal.copy()
        delta = cost - current_cost
        accept_prob = (
            math.exp(-0.5 * (delta / max(sigma_noise, 1e-9)) ** 2) if math.isfinite(delta) else 0.0
        )
        if math.isfinite(cost) and (cost < current_cost or rng.random() < accept_prob):
            current_vector = proposal
            current_cost = cost
    if best_vector is None:
        best_vector = 0.5 * (lower + upper)
    return best_vector, best_cost, int(n_eval)


_METHOD_DRIVERS: dict[str, Callable[..., tuple[np.ndarray, float, int]]] = {
    "grid_search": _driver_grid_search,
    "random_search": _driver_random_search,
    "cma_es": _driver_cma_es,
    "simplex": _driver_simplex,
    "nelder_mead": _driver_nelder_mead,
    "gp_mapping": _driver_gp_mapping,
    "da_mh_gp": _driver_da_mh_gp,
}


# ---------------------------------------------------------------------------
# ModelCalibrationLauncher
# ---------------------------------------------------------------------------


class ModelCalibrationLauncher:
    """Legacy-shape launcher rebuilt on top of the new primitives.

    Reads a legacy ``[model_calibration]`` TOML, prepares an on-disk
    scaffold (``calibration_root``, ``session_manifest.json``,
    ``iteration_history.jsonl``) and runs one calibration loop via a
    method dispatcher. Each evaluation opens a
    :class:`hydromodpy.project.Project` in headless mode.
    """

    def __init__(self, calibration_path: Path | str) -> None:
        self.config_path = Path(calibration_path).expanduser().resolve()
        raw = load_toml_with_base_config(self.config_path)
        self._parsed_cfg = _parse_launcher_cfg(self.config_path, raw)
        self._cfg_ns = _build_cfg_namespace(self._parsed_cfg)
        self._session: PreparedCalibrationSession | None = None
        self._manifest: dict[str, Any] = {}

    @property
    def cfg(self) -> SimpleNamespace:
        """Return the legacy-shape cfg namespace used by downstream helpers."""
        return self._cfg_ns

    # ------------------------------------------------------------------
    # Session preparation
    # ------------------------------------------------------------------
    def prepare(self) -> PreparedCalibrationSession:
        """Prepare on-disk scaffolds for the calibration session."""
        if self._session is not None:
            return self._session

        raw_simulation_toml = load_toml_with_base_config(self._parsed_cfg.simulation_config_path)
        calibration_id = self._parsed_cfg.model_calibration.calibration_id or self.config_path.stem
        project_root = _resolve_simulation_project_root(
            raw_simulation_toml,
            simulation_config_path=self._parsed_cfg.simulation_config_path,
        )
        calibration_root = project_root / "calibrations" / calibration_id
        calibration_root.mkdir(parents=True, exist_ok=True)

        parameter_set = _ParameterSet(
            names=self._parsed_cfg.parameter_names,
            bounds=dict(self._parsed_cfg.bounds),
        )
        method_name = str(self._parsed_cfg.calibration.global_method).strip().lower()
        method_kwargs = dict(self._parsed_cfg.calibration_method_kwargs.get(method_name, {}))
        core_settings: dict[str, Any] = {
            "method": method_name,
            "method_kwargs": method_kwargs,
            "objective_metric": str(self._parsed_cfg.calibration.objective_metric),
            "parameter_set": parameter_set,
        }

        self._session = PreparedCalibrationSession(
            config_path=self.config_path,
            simulation_config_path=self._parsed_cfg.simulation_config_path,
            raw_simulation_toml=dict(raw_simulation_toml),
            calibration_id=calibration_id,
            calibration_root=calibration_root,
            session_manifest_path=calibration_root / "session_manifest.json",
            iteration_history_path=calibration_root / "iteration_history.jsonl",
            core_settings=core_settings,
            parameter_names=self._parsed_cfg.parameter_names,
            candidates_root=calibration_root / "runtime_candidates",
        )
        # Initialize an empty history and session manifest so reference-
        # objective code can drop artefacts alongside it.
        self._session.iteration_history_path.write_text("", encoding="utf-8")
        initial_manifest = {
            **self._session.to_summary(),
            "status": "prepared",
            "iteration_count": 0,
            "method": method_name,
        }
        self._session.session_manifest_path.write_text(
            json.dumps(initial_manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        self._manifest = initial_manifest
        return self._session

    # ------------------------------------------------------------------
    # Calibration loop
    # ------------------------------------------------------------------
    def calibrate(
        self,
        *,
        launcher_factory: Any = None,
        calibration_method: Any = None,
    ) -> dict[str, Any]:
        """Run the configured calibration method and return a legacy summary dict."""
        del launcher_factory  # accepted for legacy parity

        session = self.prepare()
        parameter_set: _ParameterSet = session.core_settings["parameter_set"]
        lower = parameter_set.lower
        upper = parameter_set.upper
        method_name = str(session.core_settings["method"]).strip().lower()
        method_kwargs = dict(session.core_settings.get("method_kwargs", {}))

        iteration_records: list[dict[str, Any]] = []
        blocks_by_iter: list[tuple[_BlockEvaluation, ...]] = []
        candidate_timing_values: list[dict[str, float]] = []
        t_start = time.perf_counter()

        def _cost(vector: np.ndarray) -> tuple[float, np.ndarray]:
            iteration_index = len(iteration_records) + 1
            iteration_id = f"iter_{iteration_index:04d}"
            params_named = parameter_set.mapping_from(vector)
            candidate_t_start = time.perf_counter()
            try:
                request = actualize_candidate(
                    session=session,
                    cfg=self._cfg_ns,
                    params=params_named,
                    iteration_index=iteration_index,
                )
            except Exception as exc:
                record = {
                    "iteration_id": iteration_id,
                    "params_vector": list(float(v) for v in vector),
                    "params_named": dict(params_named),
                    "objective_total": None,
                    "block_costs": {},
                    "status": "parameter_injection_failed",
                    "failure_reason": f"{type(exc).__name__}: {exc}",
                }
                iteration_records.append(record)
                blocks_by_iter.append(())
                self._append_iteration_history(record)
                return float("inf"), vector

            from hydromodpy.project import Project

            simulation_start = time.perf_counter()
            try:
                project = Project(request.candidate_config_path, headless=True)
                project.run()
                run_state = project._ctx
                simulation_end = time.perf_counter()
                selected = select_candidate_outputs(
                    cfg=self._cfg_ns,
                    run_state=run_state,
                    session=session,
                )
                total, block_costs, blocks = _compute_composite_objective(
                    cfg=self._parsed_cfg,
                    selected=selected,
                )
                status = "objective_evaluated"
                failure_reason: str | None = None
            except Exception as exc:
                total = float("inf")
                block_costs = {}
                blocks = ()
                simulation_end = time.perf_counter()
                status = "simulation_failed"
                failure_reason = f"{type(exc).__name__}: {exc}"
            finally:
                try:
                    project.close()  # type: ignore[has-type]
                except Exception:
                    pass
            candidate_total = time.perf_counter() - candidate_t_start
            candidate_sim = simulation_end - simulation_start
            candidate_timing_values.append(
                {
                    "total_time_seconds": float(candidate_total),
                    "prepare_time_seconds": 0.0,
                    "simulation_time_seconds": float(candidate_sim),
                }
            )
            record = {
                "iteration_id": iteration_id,
                "params_vector": list(float(v) for v in vector),
                "params_named": dict(params_named),
                "objective_total": None if not math.isfinite(total) else float(total),
                "block_costs": {str(k): float(v) for k, v in block_costs.items()},
                "status": status,
                "failure_reason": failure_reason,
            }
            iteration_records.append(record)
            blocks_by_iter.append(blocks)
            self._append_iteration_history(record)
            return (float(total) if math.isfinite(total) else float("inf")), vector

        # Custom `calibration_method` with ``.calibrate`` interface (legacy
        # hook kept for the skipped analytical test in the repo).
        if calibration_method is not None and hasattr(calibration_method, "calibrate"):
            bounds_pairs = [
                (float(low), float(high)) for low, high in zip(lower, upper, strict=True)
            ]
            outcome = calibration_method.calibrate(
                lambda x: _cost(np.asarray(x, dtype=float))[0],
                bounds_pairs,
                method=method_name,
                **method_kwargs,
            )
            vector = np.asarray(outcome.get("x_best", 0.5 * (lower + upper)), dtype=float)
            cost_best = float(outcome.get("cost_best", float("inf")))
            n_evaluations = int(outcome.get("n_evaluations", len(iteration_records) or 1))
            params_best = parameter_set.mapping_from(vector)
            status = "calibrated"
        else:
            driver = _METHOD_DRIVERS.get(method_name)
            if driver is None:
                raise ValueError(
                    f"Unsupported calibration method '{method_name}' (supported: {sorted(_METHOD_DRIVERS)})"
                )
            try:
                vector, cost_best, n_evaluations = driver(
                    cost_fn=_cost,
                    lower=lower,
                    upper=upper,
                    kwargs=method_kwargs,
                )
                params_best = parameter_set.mapping_from(vector)
                status = "calibrated"
            except Exception as exc:
                vector = 0.5 * (lower + upper)
                cost_best = float("inf")
                n_evaluations = len(iteration_records)
                params_best = parameter_set.mapping_from(vector)
                status = "failed"
                if not iteration_records:
                    iteration_records.append(
                        {
                            "iteration_id": "iter_0001",
                            "params_vector": list(float(v) for v in vector),
                            "params_named": dict(params_best),
                            "objective_total": None,
                            "block_costs": {},
                            "status": "driver_failed",
                            "failure_reason": f"{type(exc).__name__}: {exc}",
                        }
                    )

        wall_seconds = float(time.perf_counter() - t_start)

        # Write full iteration history (the streamed file already contains
        # every record - this ensures we have the final, consolidated
        # JSONL even when the driver crashed mid-way).
        self._rewrite_iteration_history(iteration_records)

        # Best-iteration composite blocks (for metadata).
        best_blocks: tuple[_BlockEvaluation, ...] = ()
        if iteration_records:
            best_index = min(
                (
                    (idx, record.get("objective_total"))
                    for idx, record in enumerate(iteration_records)
                    if record.get("objective_total") is not None
                ),
                default=(None, None),
                key=lambda item: float("inf") if item[1] is None else float(item[1]),
            )[0]
            if best_index is not None:
                best_blocks = blocks_by_iter[best_index]

        result_payload = {
            "method": method_name,
            "cost_best": None if not math.isfinite(cost_best) else float(cost_best),
            "score_best": (None if not math.isfinite(cost_best) else float(-cost_best)),
            "params_best": dict(params_best),
            "n_evaluations": int(n_evaluations),
            "metadata": {
                "calibration_time_seconds": wall_seconds,
                "session_prepare_time_seconds": 0.0,
                "candidate_timing_summary": _summarize_candidate_timings(candidate_timing_values),
                "objective_evaluation": {
                    "blocks": [
                        {
                            "name": block.name,
                            "raw_cost": float(block.raw_cost),
                            "normalized_cost": float(block.normalized_cost),
                            "reference_scale": float(block.reference_scale),
                            "n_values": int(block.n_values),
                        }
                        for block in best_blocks
                    ],
                },
            },
        }
        result_path = session.calibration_root / "calibration_result.json"
        result_path.write_text(
            json.dumps(result_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        # Model distribution (random_search persists evaluated candidates).
        model_distribution_payload: dict[str, Any] | None = None
        if self._parsed_cfg.model_calibration.persist_model_distribution and method_name in {
            "random_search",
            "gp_mapping",
            "da_mh_gp",
        }:
            rows: list[dict[str, Any]] = []
            for record in iteration_records:
                rows.append(
                    {
                        "sample_id": record["iteration_id"],
                        "params_vector": list(record["params_vector"]),
                        "params_named": dict(record["params_named"]),
                        "objective_total": record.get("objective_total"),
                        "block_costs": dict(record.get("block_costs", {})),
                        "status": record.get("status"),
                    }
                )
            distribution_payload = {
                "role": "parameter_sample_distribution",
                "method": method_name,
                "parameter_names": list(self._parsed_cfg.parameter_names),
                "sample_count": int(len(rows)),
                "samples": rows,
            }
            distribution_path = session.calibration_root / "model_distribution.json"
            distribution_path.write_text(
                json.dumps(distribution_payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            model_distribution_payload = {
                "path": str(distribution_path),
                "sample_count": int(len(rows)),
            }

        manifest: dict[str, Any] = {
            **session.to_summary(),
            "status": status,
            "iteration_count": int(len(iteration_records)),
            "n_evaluations": int(n_evaluations),
            "method": method_name,
            "cost_best": result_payload["cost_best"],
            "params_best": dict(params_best),
            "result_path": str(result_path),
            "primary_solver": _detect_primary_solver(session.raw_simulation_toml),
            "model_distribution": model_distribution_payload,
            "calibration_report": (
                {
                    "status": status,
                    "failed_count": sum(
                        1
                        for record in iteration_records
                        if record.get("status") not in {"objective_evaluated", "ok"}
                    ),
                    "runtime": {
                        "candidate_run_count": int(len(candidate_timing_values)),
                        "objective_cache_hit_count": 0,
                    },
                }
                if self._parsed_cfg.model_calibration.persist_calibration_report
                else None
            ),
        }
        session.session_manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        self._manifest = manifest
        return dict(manifest)

    # ------------------------------------------------------------------
    # History writers
    # ------------------------------------------------------------------
    def _append_iteration_history(self, record: Mapping[str, Any]) -> None:
        assert self._session is not None
        with self._session.iteration_history_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(record), ensure_ascii=True) + "\n")

    def _rewrite_iteration_history(self, records: Sequence[Mapping[str, Any]]) -> None:
        assert self._session is not None
        with self._session.iteration_history_path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(dict(record), ensure_ascii=True) + "\n")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _summarize_candidate_timings(values: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    """Aggregate per-candidate timing dictionaries into mean/max/sum tuples."""
    summary: dict[str, Any] = {}
    if not values:
        return {
            "count": 0,
            "total_time_seconds": None,
            "prepare_time_seconds": None,
            "simulation_time_seconds": None,
        }
    keys = {key for entry in values for key in entry.keys()}
    summary["count"] = int(len(values))
    for key in keys:
        series = [float(entry[key]) for entry in values if entry.get(key) is not None]
        if not series:
            summary[key] = None
            continue
        arr = np.asarray(series, dtype=float)
        summary[key] = {
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "max": float(np.max(arr)),
            "sum": float(np.sum(arr)),
        }
    return summary


def _resolve_simulation_project_root(
    raw_simulation_toml: Mapping[str, Any],
    *,
    simulation_config_path: Path,
) -> Path:
    """Return the simulation's project_root (falls back to the TOML directory)."""
    workspace_section = dict(raw_simulation_toml.get("workspace", {}))
    project_root_raw = workspace_section.get("project_root")
    if project_root_raw:
        candidate = Path(project_root_raw).expanduser()
        if not candidate.is_absolute():
            candidate = (simulation_config_path.parent / candidate).resolve()
        return candidate
    return simulation_config_path.parent.resolve()


def _detect_primary_solver(raw_simulation_toml: Mapping[str, Any]) -> str | None:
    """Extract the first configured solver name from the simulation TOML."""
    simulation_section = dict(raw_simulation_toml.get("simulation", {}))
    processes = simulation_section.get("process", []) or []
    for process in processes:
        solvers = (process or {}).get("solvers", [])
        if solvers:
            return str(solvers[0]).strip().lower() or None
    return None


# ---------------------------------------------------------------------------
# persist_to_catalog - stub used by the skipped catalog test.
# ---------------------------------------------------------------------------


def persist_to_catalog(session: Any, catalog: Any, *, best_sim_id: Any = None) -> None:
    """Stub kept only so that ``tests/unit/simulation/test_catalog_import_export.py``
    (which is ``@pytest.mark.skip``-ed) can import this function from the
    new benchmark module without raising ``ImportError`` during collection.
    """
    raise NotImplementedError(
        "persist_to_catalog is not implemented in the new architecture - the "
        "calibration persistence now lives in hydromodpy.calibration.persistence."
    )


__all__ = (
    "CandidateEvaluation",
    "CandidateRunRequest",
    "ModelCalibrationLauncher",
    "ModelCalibrationObjectiveEvaluator",
    "PreparedCalibrationSession",
    "actualize_candidate",
    "persist_to_catalog",
    "select_candidate_outputs",
)
