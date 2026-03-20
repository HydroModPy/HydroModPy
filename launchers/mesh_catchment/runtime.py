"""Shared runtime helpers for catchment meshing workflows."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
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


def _optional_text(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


def _clone_config_like(config: object, *, updates: Mapping[str, Any]) -> object:
    model_dump = getattr(config, "model_dump", None)
    model_validate = getattr(config.__class__, "model_validate", None)
    if callable(model_dump) and callable(model_validate):
        payload = dict(model_dump(mode="python"))
        payload.update(dict(updates))
        return config.__class__.model_validate(payload)
    payload = dict(vars(config))
    payload.update(dict(updates))
    return SimpleNamespace(**payload)


def require_mesh_section(
    payload: Mapping[str, Any],
    *,
    section_name: str = DEFAULT_SECTION_NAME,
) -> Mapping[str, Any]:
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
    return str(constraints_mode).strip().lower() in _RIVER_TRACE_CONSTRAINT_MODES


def prepare_geographic_config_for_meshing(
    geographic_cfg: GeographicConfig,
    *,
    constraints_mode: str,
    section_name: str = DEFAULT_SECTION_NAME,
) -> GeographicConfig:
    if not constraints_mode_requires_river_trace(constraints_mode):
        return geographic_cfg
    if geographic_cfg.uses_synthetic_geographic():
        return geographic_cfg
    if bool(getattr(geographic_cfg.river_network, "enabled", False)):
        return geographic_cfg

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


def _resolve_optional_path(*, config_dir: Path, raw_value: Any) -> Path | None:
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
    if output_figure is None:
        return None
    return output_figure.with_name(
        f"{output_figure.stem}_regional{output_figure.suffix}"
    )


def _resolve_output_overrides(
    *,
    config_path: Path,
    section_data: Mapping[str, Any],
    workspace: object,
    explicit_overrides: Mapping[str, Path | str | None] | None = None,
) -> tuple[Path, Path, Path | None, Path | None, bool]:
    overrides = dict(explicit_overrides or {})
    mesh_dir = Path(getattr(workspace, "stable_folder")) / "mesh" / "gmsh"

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
    constraints_mode: str,
    output_overrides: Mapping[str, Path | str | None] | None = None,
    workspace: object | None = None,
    domain_geographic: object | None = None,
    section_name: str = DEFAULT_SECTION_NAME,
) -> dict[str, Any]:
    """Run one mono-catchment mesh workflow and return the summary payload."""
    config_path = Path(config_path).resolve()
    local_workspace = workspace if workspace is not None else hmp.Workspace(config=workspace_cfg)
    local_domain_geographic = domain_geographic
    if local_domain_geographic is None:
        local_domain_geographic = build_domain_geographic_context(
            config=geographic_cfg,
            workspace=local_workspace,
        )

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
    )
    summary = run_reference_2d_zone_conformal_case_from_toml(
        config_path,
        section=section_name,
        output_mesh=output_mesh,
        output_summary_json=output_summary_json,
        output_figure=output_figure,
        output_figure_regional=output_figure_regional,
        river_trace=river_trace,
        domain_geographic=local_domain_geographic,
        show_plot=show_plot,
    )
    summary_dict = dict(summary)
    if Path(output_mesh).exists():
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
    return summary_dict


__all__ = [
    "DEFAULT_SECTION_NAME",
    "constraints_mode_requires_river_trace",
    "get_optional_mesh_section",
    "prepare_geographic_config_for_meshing",
    "require_mesh_section",
    "resolve_constraints_mode",
    "run_single_mesh_catchment_workflow",
]
