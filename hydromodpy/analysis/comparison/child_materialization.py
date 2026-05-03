"""Generate child simulation TOMLs for comparison experiments."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.experiment_config import (
    ComparisonSimulationConfig,
    SimulationComparisonConfig,
)
from hydromodpy.analysis.comparison.runtime import (
    _build_solver_process_overlay,
    _deepcopy_jsonlike,
    _overlay_defines_process,
    write_toml_payload,
)
from hydromodpy.core.config.path_resolution import is_declared_absolute_path
from hydromodpy.core.config.toml_loader import (
    load_toml_with_base_config,
    merge_toml_payloads,
)

ALLOWED_TOP_LEVEL_OVERLAY_KEYS = {
    "simulation",
    "workspace",
    "solver",
    "modflow6",
    "modflownwt",
    "display",
    "flow",
}

ALLOWED_SIMULATION_OVERLAY_KEYS = {
    "name",
    "run_id",
    "description",
    "on_collision",
    "process",
    "results",
}

ALLOWED_FLOW_OVERLAY_KEYS = {
    "bc",
    "param",
    "runtime_backend",
}

PATH_KEY_HINTS = ("path", "root", "dir", "folder", "file", "mask")


@dataclass(frozen=True, slots=True)
class GeneratedChildConfig:
    """Generated TOML for one comparison child simulation."""

    simulation_id: str
    label: str
    solver: str
    config_path: Path
    run_name: str
    mesh_label: str | None = None
    mesh_mode: str = "unknown"


def validate_numeric_overlay(overlay: Mapping[str, Any]) -> None:
    """Validate comparison overlays before child TOML materialization."""
    unknown_top_keys = sorted(set(overlay) - ALLOWED_TOP_LEVEL_OVERLAY_KEYS)
    if unknown_top_keys:
        keys = ", ".join(unknown_top_keys)
        raise ValueError(f"comparison.simulation.overlay contains forbidden sections: {keys}")

    simulation = overlay.get("simulation")
    if isinstance(simulation, Mapping):
        unknown_simulation_keys = sorted(set(simulation) - ALLOWED_SIMULATION_OVERLAY_KEYS)
        if unknown_simulation_keys:
            keys = ", ".join(unknown_simulation_keys)
            raise ValueError(
                "comparison.simulation.overlay.simulation contains forbidden keys: "
                f"{keys}"
            )

    flow = overlay.get("flow")
    if isinstance(flow, Mapping):
        unknown_flow_keys = sorted(set(flow) - ALLOWED_FLOW_OVERLAY_KEYS)
        if unknown_flow_keys:
            keys = ", ".join(unknown_flow_keys)
            raise ValueError(
                "comparison.simulation.overlay.flow contains forbidden keys: "
                f"{keys}"
            )


def _child_run_name(*, comparison_id: str, simulation_id: str) -> str:
    return f"{comparison_id}__{simulation_id}"


def _looks_like_path_key(key: str) -> bool:
    token = str(key).strip().strip("'\"").split(".")[-1].lower()
    if token == "base_config":
        return True
    return any(hint in token for hint in PATH_KEY_HINTS)


def _absolutize_relative_path_values(value: Any, *, source_dir: Path, key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {
            str(child_key): _absolutize_relative_path_values(
                child_value,
                source_dir=source_dir,
                key=str(child_key),
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [
            _absolutize_relative_path_values(item, source_dir=source_dir, key=key)
            for item in value
        ]
    if not isinstance(value, str) or not _looks_like_path_key(key):
        return value
    if value.strip() in ("", "~"):
        return value
    if "://" in value:
        return value
    declared_path = Path(value).expanduser()
    if is_declared_absolute_path(declared_path):
        return declared_path.as_posix()
    return (source_dir / declared_path).resolve().as_posix()


def _load_self_contained_base_payload(base_config_path: Path) -> dict[str, Any]:
    base_payload = load_toml_with_base_config(base_config_path)
    return _absolutize_relative_path_values(
        base_payload,
        source_dir=base_config_path.parent,
    )


def build_child_payload(
    *,
    cfg: SimulationComparisonConfig,
    simulation: ComparisonSimulationConfig,
) -> tuple[dict[str, Any], str]:
    """Build the TOML payload and deterministic run name for one child."""
    comparison_id = str(cfg.comparison.comparison_id or cfg.config_path.stem)
    run_name = _child_run_name(comparison_id=comparison_id, simulation_id=simulation.id)

    overlay = _absolutize_relative_path_values(
        _deepcopy_jsonlike(simulation.overlay),
        source_dir=cfg.base_dir,
    )
    validate_numeric_overlay(overlay)

    simulation_overlay = overlay.setdefault("simulation", {})
    if not isinstance(simulation_overlay, dict):
        raise ValueError("comparison.simulation.overlay.simulation must be a mapping")
    simulation_overlay.setdefault("name", run_name)
    simulation_overlay.setdefault("run_id", run_name)
    simulation_overlay.setdefault("on_collision", "replace")

    if not _overlay_defines_process(overlay):
        process_overlay = _build_solver_process_overlay(
            base_config_path=cfg.base_simulation_config_path,
            solver=simulation.solver,
        )
        if process_overlay is None:
            raise ValueError(
                "Cannot generate child process overlay: base_simulation_config "
                "must declare exactly one flow process."
            )
        simulation_overlay["process"] = process_overlay

    base_payload = _load_self_contained_base_payload(cfg.base_simulation_config_path)
    base_payload["workflow"] = "simulation"
    payload = merge_toml_payloads(base_payload, overlay)
    return payload, run_name


def materialize_child_configs(
    cfg: SimulationComparisonConfig,
) -> list[GeneratedChildConfig]:
    """Write generated child TOML files and return their metadata."""
    generated_dir = cfg.comparison_root / "_generated_configs"
    children: list[GeneratedChildConfig] = []
    for simulation in cfg.comparison.simulation:
        if not simulation.enabled:
            continue
        payload, run_name = build_child_payload(cfg=cfg, simulation=simulation)
        path = generated_dir / f"{simulation.id}.toml"
        write_toml_payload(path, payload)
        children.append(
            GeneratedChildConfig(
                simulation_id=simulation.id,
                label=simulation.label or simulation.id,
                solver=simulation.solver,
                config_path=path,
                run_name=run_name,
                mesh_label=simulation.mesh_label,
                mesh_mode=simulation.mesh_mode,
            )
        )
    return children


__all__ = (
    "GeneratedChildConfig",
    "build_child_payload",
    "materialize_child_configs",
    "validate_numeric_overlay",
)
