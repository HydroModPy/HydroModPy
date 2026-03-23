"""Internal mono-run execution helpers for the dedicated mesh-catchment launcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Any

from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.solver.utils.mesh.gmsh_grid._bundle_export_contracts import (
    CatchmentBundleGeologyExportConfig,
    CatchmentBundleHydraulicPropertiesConfig,
    CatchmentBundleSummaryReference,
)
from launchers.mesh_catchment.config import MeshCatchmentConfigSchema


_RIVER_TRACE_CONSTRAINT_MODES = {"rivers_only", "geology_rivers"}


def clone_config_like(config: object, *, updates: Mapping[str, Any]) -> object:
    """Clone a config-like object while preserving Pydantic validation when available."""
    model_copy = getattr(config, "model_copy", None)
    if callable(model_copy):
        return model_copy(update=dict(updates), deep=True)

    model_dump = getattr(config, "model_dump", None)
    if callable(model_dump):
        payload = dict(model_dump(mode="python"))
    else:
        payload = dict(vars(config))
    payload.update(dict(updates))
    return SimpleNamespace(**payload)


def constraints_mode_requires_river_trace(constraints_mode: str) -> bool:
    """Tell whether the chosen constraints mode needs an explicit river trace."""
    return str(constraints_mode).strip().lower() in _RIVER_TRACE_CONSTRAINT_MODES


@dataclass(frozen=True)
class ResolvedMeshCatchmentOutputs:
    """Resolved final output destinations for one mono-catchment mesh run."""

    output_mesh: Path
    output_summary_json: Path
    output_figure: Path | None
    output_figure_regional: Path | None
    show_plot: bool


@dataclass(frozen=True)
class MeshCatchmentSingleRunDependencies:
    """Concrete collaborators required to execute one mono-catchment run."""

    workspace_factory: Callable[..., object]
    build_domain_geographic_context_fn: Callable[..., object]
    run_reference_case_fn: Callable[..., Any]
    export_catchment_mesh_bundle_fn: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class PreparedMeshCatchmentRuntime:
    """Resolved runtime artifacts shared by the mono-run workflow."""

    effective_output_layout: str
    final_project_root: Path
    runtime_project_root: Path | None
    runtime_workspace_cfg: object
    workspace: object
    domain_geographic: object
    built_domain_geographic_locally: bool


@dataclass(frozen=True)
class MeshCatchmentWorkflowRuntimeArtifacts:
    """Summary plus in-memory artifacts produced by one mono-catchment run."""

    summary: dict[str, Any]
    mesh_planar: object | None = None


def _resolve_optional_path(*, config_dir: Path, raw_value: Any) -> Path | None:
    """Resolve one optional file path relative to the launcher TOML when needed."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if text == "":
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (config_dir / path).resolve()
    return path


def _derive_regional_figure_path(output_figure: Path | None) -> Path | None:
    """Derive the sibling regional figure path from the main overview figure path."""
    if output_figure is None:
        return None
    return output_figure.with_name(
        f"{output_figure.stem}_regional{output_figure.suffix}"
    )


def _default_mesh_output_dir(workspace: object) -> Path:
    """Return the canonical mesh output directory inside one workspace."""
    return Path(getattr(workspace, "stable_folder")) / "mesh"


def _derive_flat_runtime_project_root(*, final_project_root: Path) -> Path:
    """Build the temporary runtime root used by the dedicated ``flat`` layout."""
    return final_project_root.parent / "_mesh_runtime" / final_project_root.name


def _cleanup_geographic_artifacts(*, workspace: object) -> list[str]:
    """Delete intermediate geographic folders from one workspace."""
    stable_folder = Path(getattr(workspace, "stable_folder"))
    deleted: list[str] = []
    for folder in (stable_folder / "geographic", stable_folder / "demcorrecflow"):
        if not folder.exists():
            continue
        shutil.rmtree(folder)
        deleted.append(str(folder))
    return deleted


def _cleanup_runtime_workspace_root(*, runtime_project_root: Path) -> list[str]:
    """Delete the temporary runtime workspace created for the ``flat`` layout."""
    deleted: list[str] = []
    if runtime_project_root.exists():
        shutil.rmtree(runtime_project_root)
        deleted.append(str(runtime_project_root))
    runtime_parent = runtime_project_root.parent
    if runtime_parent.name == "_mesh_runtime" and runtime_parent.exists():
        try:
            next(runtime_parent.iterdir())
        except StopIteration:
            runtime_parent.rmdir()
            deleted.append(str(runtime_parent))
    return deleted


def _resolve_output_overrides(
    *,
    config_path: Path,
    section_cfg: MeshCatchmentConfigSchema,
    workspace: object,
    explicit_overrides: Mapping[str, Path | str | None] | None = None,
    default_output_dir: Path | None = None,
) -> ResolvedMeshCatchmentOutputs:
    """Resolve final output paths after applying launcher/runtime precedence rules."""
    overrides = dict(explicit_overrides or {})
    mesh_dir = (
        Path(default_output_dir)
        if default_output_dir is not None
        else _default_mesh_output_dir(workspace)
    )

    output_mesh = overrides.get("output_mesh")
    if output_mesh is None:
        output_mesh = _resolve_optional_path(
            config_dir=config_path.parent,
            raw_value=section_cfg.output_mesh,
        )
    output_mesh = (
        Path(output_mesh)
        if output_mesh is not None
        else mesh_dir / "mesh_catchment.msh"
    )

    output_summary_json = overrides.get("output_summary_json")
    if output_summary_json is None:
        output_summary_json = _resolve_optional_path(
            config_dir=config_path.parent,
            raw_value=section_cfg.output_summary_json,
        )
    output_summary_json = (
        Path(output_summary_json)
        if output_summary_json is not None
        else mesh_dir / "mesh_catchment_summary.json"
    )

    output_figure = overrides.get("output_figure")
    if output_figure is None:
        output_figure = _resolve_optional_path(
            config_dir=config_path.parent,
            raw_value=section_cfg.output_figure,
        )
    output_figure_path = None if output_figure is None else Path(output_figure)

    output_figure_regional = overrides.get("output_figure_regional")
    if output_figure_regional is None:
        output_figure_regional = _resolve_optional_path(
            config_dir=config_path.parent,
            raw_value=section_cfg.output_figure_regional,
        )
    output_figure_regional_path = (
        None
        if output_figure_regional is None
        else Path(output_figure_regional)
    )
    if output_figure_regional_path is None:
        output_figure_regional_path = _derive_regional_figure_path(output_figure_path)

    return ResolvedMeshCatchmentOutputs(
        output_mesh=output_mesh,
        output_summary_json=output_summary_json,
        output_figure=output_figure_path,
        output_figure_regional=output_figure_regional_path,
        show_plot=bool(section_cfg.show_plot),
    )


def _resolve_river_trace(
    *,
    constraints_mode: str,
    geographic_cfg: GeographicConfig,
    domain_geographic: object | None,
) -> object | None:
    """Return the in-memory river trace required by river-constrained meshing."""
    river_trace = (
        None if domain_geographic is None else getattr(domain_geographic, "river_mesh_trace", None)
    )
    if not constraints_mode_requires_river_trace(constraints_mode):
        return river_trace
    if river_trace is not None:
        return river_trace
    if geographic_cfg.uses_synthetic_geographic():
        raise ValueError(
            "mesh_catchment.constraints_mode requires river_trace, but synthetic geographic "
            "mode does not generate river networks."
        )
    raise ValueError(
        "mesh_catchment.constraints_mode requires river_trace, but no in-memory "
        "river trace was generated. Ensure [geographic.river_network] is enabled "
        "with valid threshold parameters."
    )


def _prepare_runtime_environment(
    *,
    section_cfg: MeshCatchmentConfigSchema,
    workspace_cfg: object,
    geographic_cfg: GeographicConfig,
    workspace: object | None,
    domain_geographic: object | None,
    deps: MeshCatchmentSingleRunDependencies,
) -> PreparedMeshCatchmentRuntime:
    """Resolve the runtime workspace and domain_geographic context for one run."""

    dedicated_flat_layout = section_cfg.output_layout == "flat" and workspace is None
    effective_output_layout = "flat" if dedicated_flat_layout else "standard"
    final_project_root = Path(getattr(workspace_cfg, "project_root")).resolve()
    runtime_project_root: Path | None = None
    runtime_workspace_cfg = workspace_cfg
    if dedicated_flat_layout:
        runtime_project_root = _derive_flat_runtime_project_root(
            final_project_root=final_project_root,
        )
        runtime_workspace_cfg = clone_config_like(
            workspace_cfg,
            updates={
                "project_root": runtime_project_root,
                "output_root": None,
            },
        )

    local_workspace = (
        workspace
        if workspace is not None
        else deps.workspace_factory(config=runtime_workspace_cfg)
    )
    local_domain_geographic = domain_geographic
    built_domain_geographic_locally = False
    if local_domain_geographic is None:
        local_domain_geographic = deps.build_domain_geographic_context_fn(
            config=geographic_cfg,
            workspace=local_workspace,
        )
        built_domain_geographic_locally = True

    return PreparedMeshCatchmentRuntime(
        effective_output_layout=effective_output_layout,
        final_project_root=final_project_root,
        runtime_project_root=runtime_project_root,
        runtime_workspace_cfg=runtime_workspace_cfg,
        workspace=local_workspace,
        domain_geographic=local_domain_geographic,
        built_domain_geographic_locally=built_domain_geographic_locally,
    )


def _export_exchange_bundle_if_possible(
    *,
    summary_dict: dict[str, Any],
    resolved_outputs: ResolvedMeshCatchmentOutputs,
    prepared_runtime: PreparedMeshCatchmentRuntime,
    section_cfg: MeshCatchmentConfigSchema,
    domain_cfg: object | None,
    river_trace: object | None,
    config_path: Path,
    deps: MeshCatchmentSingleRunDependencies,
) -> None:
    """Export the catchment-mesh exchange bundle when the mesh file exists."""

    if not resolved_outputs.output_mesh.exists():
        return
    geology_cfg = (
        None
        if section_cfg.geology is None
        else CatchmentBundleGeologyExportConfig.from_mapping(
            section_cfg.geology.model_dump(mode="python")
        )
    )
    hydraulic_properties_cfg = (
        None
        if section_cfg.hydraulic_properties is None
        else CatchmentBundleHydraulicPropertiesConfig.from_mapping(
            section_cfg.hydraulic_properties.model_dump(mode="python")
        )
    )
    try:
        bundle_summary = deps.export_catchment_mesh_bundle_fn(
            mesh_path=resolved_outputs.output_mesh,
            domain_geographic=prepared_runtime.domain_geographic,
            domain_cfg=domain_cfg,
            geology_cfg=geology_cfg,
            hydraulic_properties_cfg=hydraulic_properties_cfg,
            river_trace=river_trace,
            summary=CatchmentBundleSummaryReference.from_mapping(summary_dict),
            config_path=config_path,
        )
        summary_dict["exchange_bundle"] = bundle_summary
        summary_dict["output_exchange_bundle_dir"] = str(bundle_summary["bundle_dir"])
    except (Exception, SystemExit) as exc:  # pragma: no cover - defensive only
        message = str(exc).strip()
        summary_dict["exchange_bundle_error"] = (
            type(exc).__name__
            if message == ""
            else f"{type(exc).__name__}: {message}"
        )


def _apply_post_run_cleanup(
    *,
    summary_dict: dict[str, Any],
    section_cfg: MeshCatchmentConfigSchema,
    prepared_runtime: PreparedMeshCatchmentRuntime,
) -> None:
    """Apply launcher-level cleanup policies after the meshing case returns."""

    if (
        section_cfg.geographic_outputs_mode == "cleanup"
        and prepared_runtime.built_domain_geographic_locally
        and prepared_runtime.effective_output_layout != "flat"
    ):
        try:
            deleted_paths = _cleanup_geographic_artifacts(
                workspace=prepared_runtime.workspace
            )
            summary_dict["geographic_outputs_cleanup_applied"] = bool(deleted_paths)
            if deleted_paths:
                summary_dict["geographic_outputs_cleanup_deleted"] = deleted_paths
        except Exception as exc:  # pragma: no cover - defensive only
            summary_dict["geographic_outputs_cleanup_error"] = str(exc)

    if (
        prepared_runtime.effective_output_layout == "flat"
        and prepared_runtime.runtime_project_root is not None
    ):
        try:
            deleted_runtime_paths = _cleanup_runtime_workspace_root(
                runtime_project_root=prepared_runtime.runtime_project_root,
            )
            summary_dict["runtime_workspace_cleanup_applied"] = bool(
                deleted_runtime_paths
            )
            if deleted_runtime_paths:
                summary_dict["runtime_workspace_cleanup_deleted"] = (
                    deleted_runtime_paths
                )
        except Exception as exc:  # pragma: no cover - defensive only
            summary_dict["runtime_workspace_cleanup_error"] = str(exc)


def run_single_mesh_catchment_workflow_typed(
    *,
    config_path: Path,
    section_cfg: MeshCatchmentConfigSchema,
    workspace_cfg: object,
    geographic_cfg: GeographicConfig,
    domain_cfg: object | None,
    constraints_mode: str,
    output_overrides: Mapping[str, Path | str | None] | None = None,
    workspace: object | None = None,
    domain_geographic: object | None = None,
    section_name: str,
    deps: MeshCatchmentSingleRunDependencies,
    return_runtime_artifacts: bool = False,
) -> dict[str, Any] | MeshCatchmentWorkflowRuntimeArtifacts:
    """Run one mono-catchment mesh workflow from an already typed launcher section."""
    prepared_runtime = _prepare_runtime_environment(
        section_cfg=section_cfg,
        workspace_cfg=workspace_cfg,
        geographic_cfg=geographic_cfg,
        workspace=workspace,
        domain_geographic=domain_geographic,
        deps=deps,
    )

    river_trace = _resolve_river_trace(
        constraints_mode=constraints_mode,
        geographic_cfg=geographic_cfg,
        domain_geographic=prepared_runtime.domain_geographic,
    )
    resolved_outputs = _resolve_output_overrides(
        config_path=config_path,
        section_cfg=section_cfg,
        workspace=prepared_runtime.workspace,
        explicit_overrides=output_overrides,
        default_output_dir=(
            prepared_runtime.final_project_root
            if prepared_runtime.effective_output_layout == "flat"
            else None
        ),
    )
    case_kwargs: dict[str, Any] = {
        "section": section_name,
        "section_data_override": section_cfg.model_dump(mode="python"),
        "output_mesh": resolved_outputs.output_mesh,
        "output_summary_json": resolved_outputs.output_summary_json,
        "output_figure": resolved_outputs.output_figure,
        "output_figure_regional": resolved_outputs.output_figure_regional,
        "river_trace": river_trace,
        "domain_geographic": prepared_runtime.domain_geographic,
        "show_plot": resolved_outputs.show_plot,
    }
    if return_runtime_artifacts:
        case_kwargs["return_runtime_artifacts"] = True
    case_result = deps.run_reference_case_fn(
        config_path,
        **case_kwargs,
    )
    runtime_mesh = None
    if return_runtime_artifacts:
        summary_payload = getattr(case_result, "summary", None)
        runtime_mesh = getattr(case_result, "mesh", None)
        if not isinstance(summary_payload, Mapping):
            raise TypeError(
                "Mesh runtime capture requires one case result exposing a mapping "
                "'summary' attribute."
            )
        if runtime_mesh is None:
            raise TypeError(
                "Mesh runtime capture requires one case result exposing a non-null "
                "'mesh' attribute."
            )
        summary_dict = dict(summary_payload)
    else:
        summary_dict = dict(case_result)
    summary_dict["output_layout"] = prepared_runtime.effective_output_layout
    summary_dict["geographic_outputs_mode"] = section_cfg.geographic_outputs_mode
    summary_dict["geographic_outputs_cleanup_applied"] = False
    _export_exchange_bundle_if_possible(
        summary_dict=summary_dict,
        resolved_outputs=resolved_outputs,
        prepared_runtime=prepared_runtime,
        section_cfg=section_cfg,
        domain_cfg=domain_cfg,
        river_trace=river_trace,
        config_path=config_path,
        deps=deps,
    )
    _apply_post_run_cleanup(
        summary_dict=summary_dict,
        section_cfg=section_cfg,
        prepared_runtime=prepared_runtime,
    )
    if return_runtime_artifacts:
        return MeshCatchmentWorkflowRuntimeArtifacts(
            summary=summary_dict,
            mesh_planar=runtime_mesh,
        )
    return summary_dict


__all__ = [
    "MeshCatchmentWorkflowRuntimeArtifacts",
    "MeshCatchmentSingleRunDependencies",
    "PreparedMeshCatchmentRuntime",
    "ResolvedMeshCatchmentOutputs",
    "clone_config_like",
    "constraints_mode_requires_river_trace",
    "run_single_mesh_catchment_workflow_typed",
]
