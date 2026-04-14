"""Mesh step — optional catchment meshing or external mesh loading.

This module contains the functions that handle the optional catchment meshing
phase, including both embedded mesh generation and external mesh loading.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.solver.utils.mesh.gmsh_grid import load_planar_mesh
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import LauncherRunState
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfigSchema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional mesh section resolution
# ---------------------------------------------------------------------------

def resolve_optional_mesh_section(
    raw_toml: Mapping[str, object],
) -> MeshCatchmentConfigSchema | None:
    """Extract and validate the optional [mesh_catchment] section from raw TOML."""
    from hydromodpy.spatial.mesh.config import parse_mesh_catchment_batch_config_data
    from hydromodpy.spatial.mesh.runtime import get_optional_mesh_section

    section = get_optional_mesh_section(raw_toml)
    batch_section = raw_toml.get("mesh_catchment_batch")
    if batch_section is None:
        return section
    batch_cfg = parse_mesh_catchment_batch_config_data(batch_section)
    if batch_cfg.enabled:
        raise ValueError(
            "Embedded [mesh_catchment_batch] is not supported in process_simulation. "
            "Use the dedicated mesh-catchment launcher for batch runs."
        )
    return section


def resolve_optional_mesh_input(
    raw_toml: Mapping[str, object],
    config_path: str | Path,
) -> dict[str, str] | None:
    """Resolve one optional external mesh-input block from raw launcher TOML."""
    section = raw_toml.get("mesh_input")
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise ValueError("[mesh_input] configuration must be a mapping when provided.")

    config_path = Path(config_path)

    def _resolve_optional_path(raw_value: object) -> str:
        text = str(raw_value or "").strip()
        if text == "":
            return ""
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (config_path.parent / path).resolve()
        return str(path)

    mesh_path = _resolve_optional_path(section.get("mesh_path"))
    bundle_dir = _resolve_optional_path(section.get("bundle_dir"))
    if mesh_path == "" and bundle_dir == "":
        raise ValueError(
            "[mesh_input] requires at least one of 'mesh_path' or 'bundle_dir'."
        )
    return {
        "mesh_path": mesh_path,
        "bundle_dir": bundle_dir,
    }


# ---------------------------------------------------------------------------
# Mesh phases
# ---------------------------------------------------------------------------

def run_mesh_phase(
    config_path: str | Path,
    cfg: object,
    run_state: LauncherRunState,
    mesh_section_data: MeshCatchmentConfigSchema | None,
    constraints_mode: str | None,
) -> None:
    """Run the optional catchment meshing phase embedded in simulation TOML."""
    if mesh_section_data is None or constraints_mode is None:
        return

    from hydromodpy.spatial.mesh.runtime import (
        run_single_mesh_catchment_workflow_with_runtime_artifacts,
    )

    setup_state = run_state.setup
    mesh_runtime = run_single_mesh_catchment_workflow_with_runtime_artifacts(
        config_path=config_path,
        section_data=mesh_section_data,
        workspace_cfg=cfg.workspace,
        geographic_cfg=cfg.geographic,
        domain_cfg=cfg.domain,
        constraints_mode=constraints_mode,
        workspace=setup_state.workspace,
        geographic_features=setup_state.geographic_features,
        domain_geographic=setup_state.domain_geographic,
    )
    setup_state.mesh_summary = mesh_runtime.summary
    setup_state.mesh_planar = mesh_runtime.mesh_planar
    load_mesh_artifacts_from_summary(run_state, strict=False, preserve_preloaded=True)


def run_mesh_input_phase(
    run_state: LauncherRunState,
    external_mesh_input: dict[str, str] | None,
) -> None:
    """Load one pre-existing external mesh declared in ``[mesh_input]``."""
    if external_mesh_input is None:
        return

    mesh_summary: dict[str, str] = {
        "mesh_source": "external_input",
    }
    mesh_path = str(external_mesh_input.get("mesh_path", "")).strip()
    bundle_dir = str(external_mesh_input.get("bundle_dir", "")).strip()
    if mesh_path != "":
        mesh_summary["output_mesh"] = mesh_path
    if bundle_dir != "":
        mesh_summary["output_exchange_bundle_dir"] = bundle_dir

    run_state.setup.mesh_summary = mesh_summary
    load_mesh_artifacts_from_summary(run_state, strict=True)


# ---------------------------------------------------------------------------
# Mesh artifact loading
# ---------------------------------------------------------------------------

def load_mesh_artifacts_from_summary(
    run_state: LauncherRunState,
    *,
    strict: bool,
    preserve_preloaded: bool = False,
) -> None:
    """Populate runtime mesh objects from ``setup.mesh_summary`` when available."""
    setup_state = run_state.setup
    if not preserve_preloaded:
        setup_state.mesh_bundle = None
        setup_state.mesh_planar = None

    mesh_summary = setup_state.mesh_summary
    if not isinstance(mesh_summary, Mapping):
        if strict:
            raise ValueError("Mesh loading requires setup.mesh_summary to be a mapping.")
        return

    bundle_dir = str(mesh_summary.get("output_exchange_bundle_dir", "")).strip()
    if bundle_dir != "" and setup_state.mesh_bundle is None:
        setup_state.mesh_bundle = load_catchment_mesh_bundle(bundle_dir)
        if isinstance(mesh_summary, dict):
            mesh_summary.setdefault(
                "output_mesh",
                str(setup_state.mesh_bundle.mesh_path),
            )

    mesh_path = str(mesh_summary.get("output_mesh", "")).strip()
    if mesh_path == "":
        if strict and setup_state.mesh_bundle is None and setup_state.mesh_planar is None:
            raise ValueError(
                "Mesh loading requires one 'output_mesh' path or "
                "'output_exchange_bundle_dir' in setup.mesh_summary."
            )
        return

    mesh_path_obj = Path(mesh_path).expanduser()
    if not strict and not mesh_path_obj.exists():
        return
    if setup_state.mesh_planar is None:
        setup_state.mesh_planar = load_planar_mesh(mesh_path_obj)


# ---------------------------------------------------------------------------
# Step entry points (unified signature for workflow pipelines)
# ---------------------------------------------------------------------------

def step_mesh(
    ctx: LauncherRunState,
    *,
    mesh_section_data: MeshCatchmentConfigSchema | None = None,
    constraints_mode: str | None = None,
) -> None:
    """Run the optional catchment meshing phase embedded in simulation TOML."""
    run_mesh_phase(
        config_path=ctx.config_path,
        cfg=ctx.cfg,
        run_state=ctx,
        mesh_section_data=mesh_section_data,
        constraints_mode=constraints_mode,
    )


def step_mesh_input(
    ctx: LauncherRunState,
    *,
    external_mesh_input: dict[str, str] | None = None,
) -> None:
    """Load one pre-existing external mesh declared in ``[mesh_input]``."""
    run_mesh_input_phase(ctx, external_mesh_input)
