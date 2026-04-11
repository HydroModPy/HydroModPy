"""Prepared runtime helpers for the model-calibration launcher."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.core.workspace.config import WorkspaceConfig

from launchers.model_calibration.config import ModelCalibrationConfig


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
    objective_total: float
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
            "objective_total": float(self.objective_total),
            "block_costs": {
                str(name): float(value) for name, value in self.block_costs.items()
            },
            "status": str(self.status),
            "failure_reason": (
                None if self.failure_reason is None else str(self.failure_reason)
            ),
        }


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


__all__ = (
    "IterationRecord",
    "PreparedCalibrationSession",
    "append_iteration_record",
    "detect_solver_families",
    "initialize_calibration_session",
    "prepare_calibration_session",
    "resolve_workspace_config",
)
