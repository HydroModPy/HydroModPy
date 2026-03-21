"""Shared runtime helpers for catchment meshing workflows.

This module is the bridge between the dedicated launcher contract and the lower
level meshing/geographic machinery. The launcher has already validated the
TOML when control reaches this file; the role here is therefore operational
rather than declarative.

The main runtime stages are:

- interpret launcher-only options such as output layout and cleanup policy;
- ensure the geographic config is compatible with the requested constraints;
- build or reuse a ``domain_geographic`` context;
- resolve final output paths with the right precedence rules;
- call the authoritative zone-conformal meshing case;
- optionally export a reusable exchange bundle and clean runtime artifacts.

Keeping these mechanics here avoids leaking dedicated-launcher behavior into
the generic meshing case while still making the overall execution path easy to
follow from the launcher entry point.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Any

import hydromodpy as hmp
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.geographic.core.domain_geographic_pipeline import (
    build_domain_geographic_context,
)
from hydromodpy.solver.utils.mesh.gmsh_grid import export_catchment_mesh_bundle
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.run_case_zone_conformal import (
    run_reference_2d_zone_conformal_case_from_toml,
)
from launchers.mesh_catchment.config import validate_mesh_catchment_config_data


DEFAULT_SECTION_NAME = "mesh_catchment"
_RIVER_TRACE_CONSTRAINT_MODES = {"rivers_only", "geology_rivers"}
_OUTPUT_LAYOUTS = {"standard", "flat"}


# ---------------------------------------------------------------------------
# Small normalization helpers
# ---------------------------------------------------------------------------

def _optional_text(raw_value: object) -> str | None:
    """Return one stripped string, or ``None`` for null/empty values."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


def _clone_config_like(config: object, *, updates: Mapping[str, Any]) -> object:
    """Clone a config-like object while preserving Pydantic validation when available."""
    model_dump = getattr(config, "model_dump", None)
    model_validate = getattr(config.__class__, "model_validate", None)
    if callable(model_dump) and callable(model_validate):
        payload = dict(model_dump(mode="python"))
        payload.update(dict(updates))
        return config.__class__.model_validate(payload)
    payload = dict(vars(config))
    payload.update(dict(updates))
    return SimpleNamespace(**payload)


# ---------------------------------------------------------------------------
# Launcher section validation and derived flags
# ---------------------------------------------------------------------------

def require_mesh_section(
    payload: Mapping[str, Any],
    *,
    section_name: str = DEFAULT_SECTION_NAME,
) -> Mapping[str, Any]:
    """Return one validated launcher section and fail fast when it is missing.

    The returned mapping is already normalized by the Pydantic schema, which
    means defaults such as the implicit support domain are materialized here
    instead of being rediscovered later from the raw TOML.
    """
    section = payload.get(section_name)
    if not isinstance(section, Mapping):
        raise ValueError(
            f"Missing [{section_name}] section in launcher TOML. "
            "Expected one mapping compatible with the conformal meshing case schema."
        )
    return validate_mesh_catchment_config_data(section)


def get_optional_mesh_section(
    payload: Mapping[str, Any],
    *,
    section_name: str = DEFAULT_SECTION_NAME,
) -> Mapping[str, Any] | None:
    """Return one validated optional mesh section, or ``None`` when absent/blank."""
    section = payload.get(section_name)
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise ValueError(f"[{section_name}] configuration must be a mapping when provided.")
    raw_cm = section.get("constraints_mode")
    if raw_cm is None or str(raw_cm).strip() == "":
        return None
    return validate_mesh_catchment_config_data(section)


def resolve_constraints_mode(
    raw_value: Any,
    *,
    section_name: str = DEFAULT_SECTION_NAME,
) -> str:
    """Normalize one launcher constraints mode."""
    token = "" if raw_value is None else str(raw_value).strip().lower()
    if token == "":
        raise ValueError(
            f"{section_name}.constraints_mode is required and must be one of: "
            "geology_only, rivers_only, geology_rivers."
        )
    allowed = {"geology_only", "rivers_only", "geology_rivers"}
    if token not in allowed:
        raise ValueError(
            f"{section_name}.constraints_mode must be one of: "
            "geology_only, rivers_only, geology_rivers."
        )
    return token


def constraints_mode_requires_river_trace(constraints_mode: str) -> bool:
    """Tell whether the chosen constraints mode needs an explicit river trace."""
    return str(constraints_mode).strip().lower() in _RIVER_TRACE_CONSTRAINT_MODES


def prepare_geographic_config_for_meshing(
    geographic_cfg: GeographicConfig,
    *,
    constraints_mode: str,
    section_name: str = DEFAULT_SECTION_NAME,
) -> GeographicConfig:
    """Enable river-network preprocessing when the mesh contract needs it.

    River-constrained meshing depends on an in-memory river trace built by the
    geographic pipeline. Users should ideally enable that pipeline explicitly
    in their TOML, but the dedicated launcher is more forgiving: if the chosen
    constraints mode requires rivers and the config forgot to switch the river
    network on, this helper patches the config before runtime execution.
    """
    if not constraints_mode_requires_river_trace(constraints_mode):
        return geographic_cfg
    if geographic_cfg.uses_synthetic_geographic():
        return geographic_cfg
    if bool(getattr(geographic_cfg.river_network, "enabled", False)):
        return geographic_cfg

    # The launcher accepts river-constrained modes even when the TOML forgot to
    # enable the geographic river network explicitly. Patch the config here so
    # the downstream geographic pipeline produces the river trace required by
    # conformal meshing.
    updated_river_network = _clone_config_like(
        geographic_cfg.river_network,
        updates={"enabled": True},
    )
    updated = _clone_config_like(
        geographic_cfg,
        updates={"river_network": updated_river_network},
    )

    model_validate = getattr(geographic_cfg.__class__, "model_validate", None)
    if callable(model_validate):
        payload = dict(updated.model_dump(mode="python"))
        return geographic_cfg.__class__.model_validate(payload)
    try:
        return GeographicConfig.model_validate(dict(updated.model_dump(mode="python")))
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise ValueError(
            f"{section_name}.constraints_mode requires river_network support, "
            "but the geographic config could not be revalidated after enabling it."
        ) from exc


# ---------------------------------------------------------------------------
# Output-path and cleanup helpers
# ---------------------------------------------------------------------------

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


def resolve_output_layout(section_data: Mapping[str, Any]) -> str:
    """Return the requested dedicated-launcher output layout."""
    raw_value = section_data.get("output_layout", "standard")
    token = str(raw_value).strip().lower()
    return token if token in _OUTPUT_LAYOUTS else "standard"


def _default_mesh_output_dir(workspace: object) -> Path:
    """Return the canonical mesh output directory inside one workspace."""
    return Path(getattr(workspace, "stable_folder")) / "mesh"


def _derive_flat_runtime_project_root(*, final_project_root: Path) -> Path:
    """Build the temporary runtime root used by the dedicated ``flat`` layout."""
    return final_project_root.parent / "_mesh_runtime" / final_project_root.name


def _resolve_geographic_outputs_mode(section_data: Mapping[str, Any]) -> str:
    """Return whether geographic intermediate folders should be kept or cleaned."""
    raw_value = section_data.get("geographic_outputs_mode", "keep")
    token = str(raw_value).strip().lower()
    return token if token in {"keep", "cleanup"} else "keep"


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
    section_data: Mapping[str, Any],
    workspace: object,
    explicit_overrides: Mapping[str, Path | str | None] | None = None,
    default_output_dir: Path | None = None,
) -> tuple[Path, Path, Path | None, Path | None, bool]:
    """Resolve output paths after applying launcher/runtime precedence rules.

    The precedence is intentionally simple and stable:

    1. explicit runtime overrides (for example batch-derived per-outlet files);
    2. optional paths declared in ``[mesh_catchment]``;
    3. launcher defaults derived from the active workspace and output layout.

    This keeps the generic meshing case independent from dedicated-launcher
    naming rules while still letting the caller force precise destinations when
    needed.
    """
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
            raw_value=section_data.get("output_mesh"),
        )
    output_mesh = Path(output_mesh) if output_mesh is not None else mesh_dir / "mesh_catchment.msh"

    output_summary_json = overrides.get("output_summary_json")
    if output_summary_json is None:
        output_summary_json = _resolve_optional_path(
            config_dir=config_path.parent,
            raw_value=section_data.get("output_summary_json"),
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
            raw_value=section_data.get("output_figure"),
        )
    output_figure_path = None if output_figure is None else Path(output_figure)

    output_figure_regional = overrides.get("output_figure_regional")
    if output_figure_regional is None:
        output_figure_regional = _resolve_optional_path(
            config_dir=config_path.parent,
            raw_value=section_data.get("output_figure_regional"),
        )
    output_figure_regional_path = (
        None
        if output_figure_regional is None
        else Path(output_figure_regional)
    )
    if output_figure_regional_path is None:
        output_figure_regional_path = _derive_regional_figure_path(output_figure_path)

    raw_show_plot = section_data.get("show_plot", False)
    show_plot = bool(raw_show_plot) if isinstance(raw_show_plot, bool) else False
    return (
        output_mesh,
        output_summary_json,
        output_figure_path,
        output_figure_regional_path,
        show_plot,
    )


def _resolve_river_trace(
    *,
    constraints_mode: str,
    geographic_cfg: GeographicConfig,
    domain_geographic: object | None,
) -> object | None:
    """Return the in-memory river trace required by river-constrained meshing."""
    river_trace = None if domain_geographic is None else getattr(domain_geographic, "river_mesh_trace", None)
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


def run_single_mesh_catchment_workflow(
    *,
    config_path: str | Path,
    section_data: Mapping[str, Any],
    workspace_cfg: object,
    geographic_cfg: GeographicConfig,
    domain_cfg: object | None,
    constraints_mode: str,
    output_overrides: Mapping[str, Path | str | None] | None = None,
    workspace: object | None = None,
    domain_geographic: object | None = None,
    section_name: str = DEFAULT_SECTION_NAME,
) -> dict[str, Any]:
    """Run one mono-catchment mesh workflow and return the summary payload.

    Conceptually this function executes one dedicated launcher run in five
    phases:

    1. decide where the runtime workspace and final outputs should live;
    2. build or reuse the geographic context;
    3. resolve the river trace and output paths expected by the meshing case;
    4. call the conformal meshing case and enrich its summary;
    5. optionally export the exchange bundle and clean temporary artifacts.

    The goal is to keep launcher behavior explicit without duplicating the
    actual meshing logic, which remains owned by the generic zone-conformal
    case.
    """
    config_path = Path(config_path).resolve()
    requested_output_layout = resolve_output_layout(section_data)
    dedicated_flat_layout = requested_output_layout == "flat" and workspace is None
    effective_output_layout = "flat" if dedicated_flat_layout else "standard"
    final_project_root = Path(getattr(workspace_cfg, "project_root")).resolve()
    runtime_project_root: Path | None = None
    runtime_workspace_cfg = workspace_cfg
    if dedicated_flat_layout:
        # In flat mode, final artifacts are written directly under the target
        # project root, but geographic preprocessing still needs its own normal
        # workspace structure. We therefore run the heavy steps in a temporary
        # sibling workspace and clean it after export.
        runtime_project_root = _derive_flat_runtime_project_root(
            final_project_root=final_project_root,
        )
        runtime_workspace_cfg = _clone_config_like(
            workspace_cfg,
            updates={
                "project_root": runtime_project_root,
                "output_root": None,
            },
        )
    local_workspace = (
        workspace
        if workspace is not None
        else hmp.Workspace(config=runtime_workspace_cfg)
    )
    local_domain_geographic = domain_geographic
    geographic_outputs_mode = _resolve_geographic_outputs_mode(section_data)
    built_domain_geographic_locally = False
    if local_domain_geographic is None:
        # Rebuild the geographic context only when the caller did not already
        # provide one. This keeps the runtime reusable inside larger pipelines
        # where a parent launcher may already have prepared delineation outputs.
        local_domain_geographic = build_domain_geographic_context(
            config=geographic_cfg,
            workspace=local_workspace,
        )
        built_domain_geographic_locally = True

    river_trace = _resolve_river_trace(
        constraints_mode=constraints_mode,
        geographic_cfg=geographic_cfg,
        domain_geographic=local_domain_geographic,
    )
    (
        output_mesh,
        output_summary_json,
        output_figure,
        output_figure_regional,
        show_plot,
    ) = _resolve_output_overrides(
        config_path=config_path,
        section_data=section_data,
        workspace=local_workspace,
        explicit_overrides=output_overrides,
        default_output_dir=final_project_root if dedicated_flat_layout else None,
    )
    # The conformal meshing case remains the authoritative producer of the
    # `.msh`, summary JSON, and figures. This runtime resolves launcher-level
    # inputs and output locations around that case, then forwards the already
    # normalized launcher section so case-level defaults are not lost.
    summary = run_reference_2d_zone_conformal_case_from_toml(
        config_path,
        section=section_name,
        section_data_override=section_data,
        output_mesh=output_mesh,
        output_summary_json=output_summary_json,
        output_figure=output_figure,
        output_figure_regional=output_figure_regional,
        river_trace=river_trace,
        domain_geographic=local_domain_geographic,
        show_plot=show_plot,
    )
    summary_dict = dict(summary)
    summary_dict["output_layout"] = effective_output_layout
    summary_dict["geographic_outputs_mode"] = geographic_outputs_mode
    summary_dict["geographic_outputs_cleanup_applied"] = False
    if Path(output_mesh).exists():
        # Export the exchange bundle only after the final mesh exists on disk,
        # because the bundle is derived from that mesh plus the geographic
        # context used to build it. A missing mesh means the meshing case
        # failed early enough that bundle export would only hide the real issue.
        geology_cfg = section_data.get("geology")
        if not isinstance(geology_cfg, Mapping):
            geology_cfg = None
        hydraulic_properties_cfg = section_data.get("hydraulic_properties")
        if not isinstance(hydraulic_properties_cfg, Mapping):
            hydraulic_properties_cfg = None
        try:
            bundle_summary = export_catchment_mesh_bundle(
                mesh_path=output_mesh,
                domain_geographic=local_domain_geographic,
                domain_cfg=domain_cfg,
                geology_cfg=geology_cfg,
                hydraulic_properties_cfg=hydraulic_properties_cfg,
                river_trace=river_trace,
                summary=summary_dict,
                config_path=config_path,
            )
            summary_dict["exchange_bundle"] = bundle_summary
            summary_dict["output_exchange_bundle_dir"] = str(bundle_summary["bundle_dir"])
        except Exception as exc:  # pragma: no cover - defensive only
            summary_dict["exchange_bundle_error"] = str(exc)
    if (
        geographic_outputs_mode == "cleanup"
        and built_domain_geographic_locally
        and not dedicated_flat_layout
    ):
        # Cleanup is only safe when this runtime created the geographic outputs
        # itself and when we are not already relying on the dedicated flat-mode
        # runtime workspace cleanup below.
        try:
            deleted_paths = _cleanup_geographic_artifacts(workspace=local_workspace)
            summary_dict["geographic_outputs_cleanup_applied"] = bool(deleted_paths)
            if deleted_paths:
                summary_dict["geographic_outputs_cleanup_deleted"] = deleted_paths
        except Exception as exc:  # pragma: no cover - defensive only
            summary_dict["geographic_outputs_cleanup_error"] = str(exc)
    if dedicated_flat_layout and runtime_project_root is not None:
        try:
            # Remove the temporary runtime workspace once final artifacts have
            # been copied/exported under the flat target directory. In flat
            # mode the user-facing folder should contain only final artifacts,
            # not the full geographic preprocessing tree.
            deleted_runtime_paths = _cleanup_runtime_workspace_root(
                runtime_project_root=runtime_project_root,
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
    return summary_dict


__all__ = [
    "DEFAULT_SECTION_NAME",
    "constraints_mode_requires_river_trace",
    "get_optional_mesh_section",
    "prepare_geographic_config_for_meshing",
    "require_mesh_section",
    "resolve_constraints_mode",
    "resolve_output_layout",
    "run_single_mesh_catchment_workflow",
]
