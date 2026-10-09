"""Generate child simulation TOMLs for comparison experiments."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.experiment_config import (
    ComparisonSimulationConfig,
    SimulationComparisonConfig,
)
from hydromodpy.analysis.comparison.runtime.config import (
    _build_solver_process_overlay,
    _deepcopy_jsonlike,
    _let_solver_backend_follow_the_process,
    _overlay_defines_process,
    write_toml_payload,
)
from hydromodpy.analysis.testbed.child_paths import (
    absolutize_child_paths,
    root_simulation_model,
)
from hydromodpy.core.toml_io.loader import (
    load_toml_with_base_config,
    merge_toml_payloads,
)
from hydromodpy.core.toml_io.merge import DIRECTIVE_SUFFIXES

ALLOWED_TOP_LEVEL_OVERLAY_KEYS = {
    "simulation",
    "workspace",
    "solver",
    "mesh_catchment",
    "mesh_input",
    "modflow6",
    "modflownwt",
    "display",
    "flow",
    # A cell may be a whole calibration rather than a single run, which is how a
    # structural sweep is expressed: one complete calibration per mesh, each with
    # its own plan, reported side by side and read for convergence. Refining a
    # mesh and keeping the conductivity that scored best would be circular,
    # because the stream-network criterion is normalised by cell size. The child
    # is materialised the same way and dispatched by `hmp run` on its
    # `[workflow] mode`, so nothing here has to know which kind of cell it built.
    "calibration",
    "workflow",
}
OVERLAY_DIRECTIVE_SUFFIXES = DIRECTIVE_SUFFIXES

ALLOWED_SIMULATION_OVERLAY_KEYS = {
    "name",
    "tags",
    "description",
    "if_exists",
    "process",
    "results",
}

ALLOWED_FLOW_OVERLAY_KEYS = {
    "bc",
    "ic",
    "param",
    "runtime_backend",
    "surface_interaction_model",
    "vi_substeps_per_period",
    "vi_substep_on_failure",
    "vi_max_adaptive_substeps",
    "ts_vi_steps_per_period",
    "ts_vi_adapt",
    "ts_vi_dt_min_fraction",
    "ts_vi_dt_max_fraction",
    "ts_vi_type",
    "ts_vi_snes_type",
}


@dataclass(frozen=True, slots=True)
class GeneratedChildConfig:
    """Generated TOML for one comparison child simulation."""

    simulation_id: str
    label: str
    solver: str | None
    config_path: Path | None
    run_name: str
    run_folder: Path | None = None
    generated_config: bool = True
    mesh_label: str | None = None
    mesh_mode: str = "unknown"


def validate_numeric_overlay(overlay: Mapping[str, Any]) -> None:
    """Validate comparison overlays before child TOML materialization."""
    unknown_top_keys = sorted(
        key
        for key in overlay
        if _overlay_key_without_directive(key) not in ALLOWED_TOP_LEVEL_OVERLAY_KEYS
    )
    if unknown_top_keys:
        keys = ", ".join(unknown_top_keys)
        raise ValueError(f"comparison.simulation.overlay contains forbidden sections: {keys}")

    simulation = overlay.get("simulation")
    if isinstance(simulation, Mapping):
        unknown_simulation_keys = sorted(set(simulation) - ALLOWED_SIMULATION_OVERLAY_KEYS)
        if unknown_simulation_keys:
            keys = ", ".join(unknown_simulation_keys)
            raise ValueError(
                f"comparison.simulation.overlay.simulation contains forbidden keys: {keys}"
            )

    flow = overlay.get("flow")
    if isinstance(flow, Mapping):
        unknown_flow_keys = sorted(set(flow) - ALLOWED_FLOW_OVERLAY_KEYS)
        if unknown_flow_keys:
            keys = ", ".join(unknown_flow_keys)
            raise ValueError(f"comparison.simulation.overlay.flow contains forbidden keys: {keys}")


def _overlay_key_without_directive(key: str) -> str:
    for suffix in OVERLAY_DIRECTIVE_SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def _child_run_name(*, comparison_id: str, simulation_id: str) -> str:
    return f"{comparison_id}__{simulation_id}"


def _payload_workspace_root(payload: Mapping[str, Any], *, fallback: Path) -> Path:
    """Return the child run folder declared by the generated simulation payload."""
    workspace = payload.get("workspace")
    if isinstance(workspace, Mapping):
        raw_root = workspace.get("root")
        if isinstance(raw_root, str) and raw_root.strip():
            return Path(raw_root).expanduser().resolve()
    return fallback


@lru_cache(maxsize=8)
def _base_data_dirs(base_config_path: Path) -> tuple[Path, ...]:
    """The data folder of the workspace of the base simulation file.

    A child runs in a workspace of its own, so a bare input file name that the base file
    finds in its data folder would not be found by the child. It is looked for here, and
    written as an absolute path when found.
    """
    from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.core.workspace.path_registry import WorkspacePathRegistry

    try:
        cfg = get_root_config_provider().from_toml(base_config_path)
        return (WorkspacePathRegistry.from_config(cfg.workspace).data_path.resolve(),)
    except (HydroModPyError, OSError, ValueError):
        # Each child loads the base file again and reports why it does not load;
        # here such a base only loses the lookup in its data folder.
        return ()


def _simulation_paths_made_absolute(
    payload: Mapping[str, Any],
    *,
    source_dir: Path,
    data_dirs: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Make absolute the paths a child simulation config declares, as the testbed does.

    The schema says which values are paths (see ``testbed/child_paths.py``). A bare input
    file name absent from *source_dir* is looked for in *data_dirs*; it stays bare when it
    is found nowhere. The substring rule used before rewrote it against the folder of the
    base file, where it is not.
    """
    return absolutize_child_paths(
        payload, model=root_simulation_model(), source_dir=source_dir, data_dirs=data_dirs
    )


def _load_self_contained_base_payload(base_config_path: Path) -> dict[str, Any]:
    base_payload = load_toml_with_base_config(base_config_path)
    return _simulation_paths_made_absolute(
        base_payload,
        source_dir=base_config_path.parent,
        data_dirs=_base_data_dirs(base_config_path),
    )


def _apply_default_workspace_overlay(
    overlay: dict[str, Any],
    *,
    comparison_root: Path,
    simulation_id: str,
) -> None:
    """Ensure generated children do not inherit a shared base workspace."""
    default_root = (comparison_root / "workspaces" / simulation_id).resolve().as_posix()
    workspace = overlay.get("workspace")
    if workspace is None:
        overlay["workspace"] = {
            "project_root": default_root,
            "root": default_root,
        }
        return
    if not isinstance(workspace, dict):
        raise ValueError("comparison.simulation.overlay.workspace must be a mapping")

    declared_root = workspace.get("root") or workspace.get("project_root")
    if isinstance(declared_root, str) and declared_root.strip():
        workspace.setdefault("project_root", declared_root)
        workspace.setdefault("root", declared_root)
    else:
        workspace.setdefault("project_root", default_root)
        workspace.setdefault("root", default_root)


def build_child_payload(
    *,
    cfg: SimulationComparisonConfig,
    simulation: ComparisonSimulationConfig,
) -> tuple[dict[str, Any], str]:
    """Build the TOML payload and deterministic run name for one child."""
    comparison_id = str(cfg.comparison.comparison_id or cfg.config_path.stem)
    run_name = _child_run_name(comparison_id=comparison_id, simulation_id=simulation.id)

    data_dirs = (
        _base_data_dirs(cfg.base_simulation_config_path)
        if cfg.base_simulation_config_path is not None
        else ()
    )
    overlay = _simulation_paths_made_absolute(
        _deepcopy_jsonlike(simulation.overlay),
        source_dir=cfg.base_dir,
        data_dirs=data_dirs,
    )
    validate_numeric_overlay(overlay)
    _apply_default_workspace_overlay(
        overlay,
        comparison_root=cfg.comparison_root,
        simulation_id=simulation.id,
    )

    simulation_overlay = overlay.setdefault("simulation", {})
    if not isinstance(simulation_overlay, dict):
        raise ValueError("comparison.simulation.overlay.simulation must be a mapping")
    simulation_overlay.setdefault("name", run_name)
    simulation_overlay.setdefault("if_exists", "replace")

    if not _overlay_defines_process(overlay):
        if cfg.base_simulation_config_path is None:
            raise ValueError("comparison.base_simulation_config is required")
        if simulation.solver is None:
            raise ValueError("comparison.simulation.solver is required")
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
        _let_solver_backend_follow_the_process(overlay)

    if cfg.base_simulation_config_path is None:
        raise ValueError("comparison.base_simulation_config is required")
    base_payload = _load_self_contained_base_payload(cfg.base_simulation_config_path)
    common_overlay = _simulation_paths_made_absolute(
        _deepcopy_jsonlike(cfg.comparison.base_simulation_overlay),
        source_dir=cfg.base_dir,
        data_dirs=data_dirs,
    )
    if not isinstance(common_overlay, dict):
        raise ValueError("comparison.base_simulation_overlay must be a mapping")
    base_payload = merge_toml_payloads(base_payload, common_overlay)
    base_payload["workflow"] = {"mode": "simulation"}
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
        declared_config_path = _resolve_optional_path(
            simulation.simulation_config,
            base_dir=cfg.base_dir,
        )
        declared_run_folder = _resolve_optional_path(
            simulation.run_folder,
            base_dir=cfg.base_dir,
        )
        if declared_config_path is not None:
            run_name = _child_run_name(
                comparison_id=str(cfg.comparison.comparison_id or cfg.config_path.stem),
                simulation_id=simulation.id,
            )
            children.append(
                GeneratedChildConfig(
                    simulation_id=simulation.id,
                    label=simulation.label or simulation.id,
                    solver=simulation.solver,
                    config_path=declared_config_path,
                    run_folder=declared_run_folder,
                    run_name=run_name,
                    generated_config=False,
                    mesh_label=simulation.mesh_label,
                    mesh_mode=simulation.mesh_mode,
                )
            )
            continue
        if declared_run_folder is not None:
            children.append(
                GeneratedChildConfig(
                    simulation_id=simulation.id,
                    label=simulation.label or simulation.id,
                    solver=simulation.solver,
                    config_path=None,
                    run_folder=declared_run_folder,
                    run_name=simulation.id,
                    generated_config=False,
                    mesh_label=simulation.mesh_label,
                    mesh_mode=simulation.mesh_mode,
                )
            )
            continue
        payload, run_name = build_child_payload(cfg=cfg, simulation=simulation)
        path = generated_dir / f"{simulation.id}.toml"
        write_toml_payload(path, payload)
        child_run_folder = _payload_workspace_root(payload, fallback=path.parent)
        children.append(
            GeneratedChildConfig(
                simulation_id=simulation.id,
                label=simulation.label or simulation.id,
                solver=simulation.solver,
                config_path=path,
                run_folder=child_run_folder,
                run_name=run_name,
                generated_config=True,
                mesh_label=simulation.mesh_label,
                mesh_mode=simulation.mesh_mode,
            )
        )
    return children


def _resolve_optional_path(value: str | Path | None, *, base_dir: Path) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


__all__ = (
    "GeneratedChildConfig",
    "build_child_payload",
    "materialize_child_configs",
    "validate_numeric_overlay",
)
