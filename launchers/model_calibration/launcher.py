"""Launcher scaffold for model-calibration workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.core.workspace.config import WorkspaceConfig

from launchers.model_calibration.config import ModelCalibrationConfig
from launchers.model_calibration.state import ModelCalibrationState


def _resolve_workspace_config(
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


def _detect_solver_families(raw_simulation_toml: dict[str, Any]) -> tuple[str, ...]:
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


class ModelCalibrationLauncher:
    """Validate and prepare one model-calibration session."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        raw_toml = load_toml_with_base_config(self.config_path)
        self.cfg = ModelCalibrationConfig.from_toml(
            raw_toml,
            base_dir=self.config_path.parent,
        )

    def run(self) -> dict[str, Any]:
        """Validate launcher and simulation-side contracts, then return a scaffold summary."""
        state = ModelCalibrationState(cfg=self.cfg)
        state.raw_simulation_toml = load_toml_with_base_config(
            self.cfg.simulation_config_path
        )
        state.simulation_workspace = _resolve_workspace_config(
            state.raw_simulation_toml,
            simulation_config_path=self.cfg.simulation_config_path,
        )
        state.core_settings = self.cfg.resolve_core_settings()

        calibration_id = (
            self.cfg.model_calibration.calibration_id or self.config_path.stem
        )
        state.calibration_root = (
            state.simulation_workspace.calibration_folder / calibration_id
        )

        solver_families = _detect_solver_families(state.raw_simulation_toml)
        primary_solver = solver_families[0] if solver_families else None

        return {
            "mode": "model_calibration",
            "status": "scaffold",
            "config_path": str(self.config_path),
            "simulation_config": str(self.cfg.simulation_config_path),
            "calibration_id": calibration_id,
            "calibration_root": str(state.calibration_root),
            "primary_solver": primary_solver,
            "solver_families": list(solver_families),
            "supported_v1_backend": primary_solver == "modflow6",
            "method": state.core_settings["method"],
            "parameter_names": list(self.cfg.parameter_names),
            "n_parameters": len(self.cfg.parameter_names),
            "output_names": list(self.cfg.output_names),
            "n_outputs": len(self.cfg.output_names),
            "objective_block_names": list(self.cfg.objective_block_names),
            "n_objective_blocks": len(self.cfg.objective_block_names),
            "persist_iteration_history": (
                self.cfg.model_calibration.persist_iteration_history
            ),
            "persist_iteration_detail_level": (
                self.cfg.model_calibration.persist_iteration_detail_level
            ),
            "disable_display": self.cfg.model_calibration.disable_display,
            "disable_postprocess": self.cfg.model_calibration.disable_postprocess,
            "rerun_best_with_outputs": (
                self.cfg.model_calibration.rerun_best_with_outputs
            ),
        }


__all__ = ("ModelCalibrationLauncher",)
