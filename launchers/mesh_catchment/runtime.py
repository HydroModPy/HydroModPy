"""Shared public runtime helpers for catchment meshing workflows.

This module now acts mainly as the public validation/normalization facade used
by the dedicated launcher and by embedded launcher integrations. The concrete
mono-run execution pipeline lives in ``runtime_single_run`` so that the public
entry points here stay short and easy to follow.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import hydromodpy as hmp
from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import (
    build_geographic_derived_features,
    build_domain_geographic_context,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.solver.utils.mesh.gmsh_grid import export_catchment_mesh_bundle
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal import (
    run_reference_2d_zone_conformal_case_from_toml,
)
from launchers.mesh_catchment.config import (
    MeshCatchmentConfigSchema,
    parse_mesh_catchment_config_data,
)
from launchers.mesh_catchment.runtime_single_run import (
    MeshCatchmentWorkflowRuntimeArtifacts,
    MeshCatchmentSingleRunDependencies,
    clone_config_like,
    constraints_mode_requires_river_trace,
    run_single_mesh_catchment_workflow_typed,
)


DEFAULT_SECTION_NAME = "mesh_catchment"


def _optional_text(raw_value: object) -> str | None:
    """Return one stripped string, or ``None`` for null/empty values."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


def require_mesh_section(
    payload: Mapping[str, Any],
    *,
    section_name: str = DEFAULT_SECTION_NAME,
) -> MeshCatchmentConfigSchema:
    """Return one validated launcher section and fail fast when it is missing."""
    section = payload.get(section_name)
    if not isinstance(section, Mapping):
        raise ValueError(
            f"Missing [{section_name}] section in launcher TOML. "
            "Expected one mapping compatible with the conformal meshing case schema."
        )
    return parse_mesh_catchment_config_data(section)


def get_optional_mesh_section(
    payload: Mapping[str, Any],
    *,
    section_name: str = DEFAULT_SECTION_NAME,
) -> MeshCatchmentConfigSchema | None:
    """Return one validated optional mesh section, or ``None`` when absent/blank."""
    section = payload.get(section_name)
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise ValueError(f"[{section_name}] configuration must be a mapping when provided.")
    raw_cm = section.get("constraints_mode")
    if raw_cm is None or str(raw_cm).strip() == "":
        return None
    return parse_mesh_catchment_config_data(section)

def prepare_geographic_config_for_meshing(
    geographic_cfg: GeographicConfig,
    *,
    constraints_mode: str,
    section_name: str = DEFAULT_SECTION_NAME,
) -> GeographicConfig:
    """Enable river-network preprocessing when the mesh contract needs it."""
    if not constraints_mode_requires_river_trace(constraints_mode):
        return geographic_cfg
    if geographic_cfg.uses_synthetic_geographic():
        return geographic_cfg
    if bool(getattr(geographic_cfg.river_network, "enabled", False)):
        return geographic_cfg

    updated_river_network = clone_config_like(
        geographic_cfg.river_network,
        updates={"enabled": True},
    )
    updated = clone_config_like(
        geographic_cfg,
        updates={"river_network": updated_river_network},
    )
    if isinstance(updated, GeographicConfig):
        return updated

    model_dump = getattr(updated, "model_dump", None)
    if callable(model_dump):
        try:
            return GeographicConfig.model_validate(dict(model_dump(mode="python")))
        except Exception as exc:  # pragma: no cover - defensive fallback
            raise ValueError(
                f"{section_name}.constraints_mode requires river_network support, "
                "but the geographic config could not be revalidated after enabling it."
            ) from exc

    return updated


def run_single_mesh_catchment_workflow(
    *,
    config_path: str | Path,
    section_data: MeshCatchmentConfigSchema,
    workspace_cfg: object,
    geographic_cfg: GeographicConfig,
    domain_cfg: object | None,
    constraints_mode: str,
    output_overrides: Mapping[str, Path | str | None] | None = None,
    workspace: object | None = None,
    geographic_features: object | None = None,
    domain_geographic: object | None = None,
    section_name: str = DEFAULT_SECTION_NAME,
) -> dict[str, Any]:
    """Run one mono-catchment mesh workflow and return the summary payload."""
    return run_single_mesh_catchment_workflow_typed(
        config_path=Path(config_path).resolve(),
        section_cfg=section_data,
        workspace_cfg=workspace_cfg,
        geographic_cfg=geographic_cfg,
        domain_cfg=domain_cfg,
        constraints_mode=constraints_mode,
        output_overrides=output_overrides,
        workspace=workspace,
        geographic_features=geographic_features,
        domain_geographic=domain_geographic,
        section_name=section_name,
        deps=MeshCatchmentSingleRunDependencies(
            workspace_factory=hmp.Workspace,
            build_domain_geographic_context_fn=build_domain_geographic_context,
            build_geographic_derived_features_fn=build_geographic_derived_features,
            run_reference_case_fn=run_reference_2d_zone_conformal_case_from_toml,
            export_catchment_mesh_bundle_fn=export_catchment_mesh_bundle,
        ),
    )


def run_single_mesh_catchment_workflow_with_runtime_artifacts(
    *,
    config_path: str | Path,
    section_data: MeshCatchmentConfigSchema,
    workspace_cfg: object,
    geographic_cfg: GeographicConfig,
    domain_cfg: object | None,
    constraints_mode: str,
    output_overrides: Mapping[str, Path | str | None] | None = None,
    workspace: object | None = None,
    geographic_features: object | None = None,
    domain_geographic: object | None = None,
    section_name: str = DEFAULT_SECTION_NAME,
) -> MeshCatchmentWorkflowRuntimeArtifacts:
    """Run one mono-catchment mesh workflow and keep the runtime mesh in memory."""
    result = run_single_mesh_catchment_workflow_typed(
        config_path=Path(config_path).resolve(),
        section_cfg=section_data,
        workspace_cfg=workspace_cfg,
        geographic_cfg=geographic_cfg,
        domain_cfg=domain_cfg,
        constraints_mode=constraints_mode,
        output_overrides=output_overrides,
        workspace=workspace,
        geographic_features=geographic_features,
        domain_geographic=domain_geographic,
        section_name=section_name,
        deps=MeshCatchmentSingleRunDependencies(
            workspace_factory=hmp.Workspace,
            build_domain_geographic_context_fn=build_domain_geographic_context,
            build_geographic_derived_features_fn=build_geographic_derived_features,
            run_reference_case_fn=run_reference_2d_zone_conformal_case_from_toml,
            export_catchment_mesh_bundle_fn=export_catchment_mesh_bundle,
        ),
        return_runtime_artifacts=True,
    )
    if not isinstance(result, MeshCatchmentWorkflowRuntimeArtifacts):
        raise TypeError(
            "Expected mesh-catchment runtime execution to return runtime artifacts."
        )
    return result


__all__ = [
    "DEFAULT_SECTION_NAME",
    "constraints_mode_requires_river_trace",
    "get_optional_mesh_section",
    "MeshCatchmentWorkflowRuntimeArtifacts",
    "prepare_geographic_config_for_meshing",
    "require_mesh_section",
    "run_single_mesh_catchment_workflow",
    "run_single_mesh_catchment_workflow_with_runtime_artifacts",
]
