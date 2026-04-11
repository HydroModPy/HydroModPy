"""Prepared runtime helpers for the model-calibration launcher."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.core.workspace.config import WorkspaceConfig

from launchers.model_calibration.config import ModelCalibrationConfig


_NUMERIC_WITH_SUFFIX_RE = re.compile(
    r"^\s*(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<suffix>.*\S)?\s*$"
)


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
    error_type: str | None = None
    error_message: str | None = None

    def to_iteration_record(self) -> IterationRecord:
        """Convert one run outcome into the persisted minimal iteration record."""
        failure_reason = self.error_message
        objective_total: float | None = None
        if self.status == "solver_run_failed":
            objective_total = math.inf
        return IterationRecord(
            iteration_id=self.request.iteration_id,
            params_vector=self.request.params_vector,
            params_named=self.request.params_named,
            objective_total=objective_total,
            block_costs={},
            status=self.status,
            failure_reason=failure_reason,
        )


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


def actualize_candidate(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    params: dict[str, float] | tuple[float, ...] | list[float],
    iteration_index: int,
) -> CandidateRunRequest:
    """Materialize one candidate override TOML from calibrated parameters."""
    parameter_set = session.core_settings["parameter_set"]
    params_vector = tuple(float(value) for value in parameter_set.vector_from(params))
    params_named = {
        str(name): float(value)
        for name, value in parameter_set.mapping_from(params_vector).items()
    }
    iteration_id = f"iter_{int(iteration_index):04d}"
    candidate_run_id = f"{session.calibration_id}__{iteration_id}"
    candidate_root = (session.candidates_root or session.calibration_root / "runtime_candidates") / iteration_id
    candidate_config_path = candidate_root / "candidate_override.toml"

    override_payload: dict[str, Any] = {
        "base_config": str(session.simulation_config_path),
        "simulation": {"run_id": candidate_run_id},
    }
    if cfg.model_calibration.disable_display:
        override_payload["display"] = {
            "enabled": False,
            "show": False,
            "save": False,
        }
    if cfg.model_calibration.disable_postprocess:
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


def execute_candidate_run(
    *,
    request: CandidateRunRequest,
    launcher_factory: Any,
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
    return CandidateRunOutcome(
        request=request,
        status="solver_run_succeeded",
        run_state=run_state,
        error_type=None,
        error_message=None,
    )


__all__ = (
    "actualize_candidate",
    "CandidateRunOutcome",
    "CandidateRunRequest",
    "IterationRecord",
    "PreparedCalibrationSession",
    "append_iteration_record",
    "detect_solver_families",
    "execute_candidate_run",
    "initialize_calibration_session",
    "persist_iteration_record",
    "prepare_calibration_session",
    "resolve_workspace_config",
    "update_session_manifest",
)
