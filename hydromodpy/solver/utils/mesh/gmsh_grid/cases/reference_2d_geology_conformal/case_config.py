"""Configuration normalization for the reference 2D zone-conformal case."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.config.toml_loader import load_toml_with_base_config
from hydromodpy.data_managers.variables.geology.config import validate_geology_config_data
from hydromodpy.solver.utils._config_helpers import get_nested_section
from hydromodpy.solver.utils.mesh.gmsh_grid import (
    parse_zone_meshing_domain_config,
    parse_zone_meshing_settings,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalCaseConfig,
    ZoneConformalConstraintFamilies,
    ZoneConformalDomainConfig,
    ZoneConformalGeologyConfig,
    ZoneConformalRiversConfig,
    ZoneConformalZoneMeshingConfig,
)


def _resolve_constraints_mode(raw_value: Any) -> str:
    token = str(raw_value).strip().lower()
    if token == "":
        raise ValueError(
            "constraints_mode is required and must be one of: "
            "geology_only, rivers_only, geology_rivers."
        )
    allowed = {
        "geology_only",
        "rivers_only",
        "geology_rivers",
    }
    if token not in allowed:
        raise ValueError(
            "constraints_mode must be one of: "
            "geology_only, rivers_only, geology_rivers."
        )
    return token


def _resolve_constraint_families(
    constraints_mode: str,
) -> ZoneConformalConstraintFamilies:
    mode = _resolve_constraints_mode(constraints_mode)
    return ZoneConformalConstraintFamilies(
        geology_interface=mode in {"geology_only", "geology_rivers"},
        river=mode in {"rivers_only", "geology_rivers"},
    )


def _validate_rivers_case_config(
    config_data: Mapping[str, Any],
    *,
    section: str,
) -> ZoneConformalRiversConfig:
    if not isinstance(config_data, Mapping):
        raise ValueError(f"[{section}.rivers] configuration must be a mapping")
    raw = dict(config_data)
    source = str(raw.get("source", "domain_geographic")).strip().lower()
    if source not in {"domain_geographic", "file"}:
        raise ValueError(
            f"[{section}.rivers].source must be 'domain_geographic' or 'file', got '{source}'."
        )

    path_value = raw.get("path")
    path_text = None if path_value is None else str(path_value).strip()
    if source == "file" and not path_text:
        raise ValueError(f"[{section}.rivers].path is required when source='file'.")

    clip_to_domain = raw.get("clip_to_domain", True)
    if not isinstance(clip_to_domain, bool):
        raise ValueError(f"[{section}.rivers].clip_to_domain must be a boolean.")

    min_segment_length_raw = raw.get("min_segment_length", 0.0)
    try:
        min_segment_length = float(min_segment_length_raw)
    except Exception as exc:
        raise ValueError(
            f"[{section}.rivers].min_segment_length must be a number, got '{min_segment_length_raw}'."
        ) from exc
    if min_segment_length < 0.0:
        raise ValueError(f"[{section}.rivers].min_segment_length must be >= 0.")

    snap_tolerance_raw = raw.get("snap_tolerance", 0.0)
    try:
        snap_tolerance = float(snap_tolerance_raw)
    except Exception as exc:
        raise ValueError(
            f"[{section}.rivers].snap_tolerance must be a number, got '{snap_tolerance_raw}'."
        ) from exc
    if snap_tolerance < 0.0:
        raise ValueError(f"[{section}.rivers].snap_tolerance must be >= 0.")

    return ZoneConformalRiversConfig(
        source=source,
        path=None if not path_text else path_text,
        clip_to_domain=clip_to_domain,
        min_segment_length=min_segment_length,
        snap_tolerance=snap_tolerance,
    )


def _validate_zone_meshing_case_config(
    config_data: Mapping[str, Any],
) -> ZoneConformalZoneMeshingConfig:
    return parse_zone_meshing_settings(config_data)


def _validate_domain_case_config(
    config_data: Mapping[str, Any],
) -> ZoneConformalDomainConfig:
    return parse_zone_meshing_domain_config(config_data)


def _validate_geology_case_config(
    config_data: Mapping[str, Any],
) -> ZoneConformalGeologyConfig:
    raw = validate_geology_config_data(dict(config_data))
    return ZoneConformalGeologyConfig.from_mapping(raw)


def _reject_removed_case_sections(
    section_cfg: Mapping[str, Any],
    *,
    section: str,
) -> None:
    removed_sections = (
        "watershed_boundary",
        "interface_scope",
        "refinement_scope",
    )
    for key in removed_sections:
        if key in section_cfg:
            raise ValueError(
                f"[{section}.{key}] is no longer supported. "
                "Use one single support domain and constrain the conformal case with geology and/or rivers only."
            )


def _resolve_case_config(
    config_toml: Path,
    *,
    section: str,
    section_data_override: Mapping[str, Any] | None = None,
) -> ZoneConformalCaseConfig:
    if section_data_override is None:
        payload = load_toml_with_base_config(config_toml)
        section_cfg = dict(get_nested_section(payload, section))
    else:
        section_cfg = dict(section_data_override)
    if "mesh_mode" in section_cfg:
        raise ValueError(
            "mesh_mode is no longer supported; use constraints_mode with one of: "
            "geology_only, rivers_only, geology_rivers."
        )
    _reject_removed_case_sections(section_cfg, section=section)
    constraints_mode_label = _resolve_constraints_mode(
        str(section_cfg.get("constraints_mode", ""))
    )
    constraint_families = _resolve_constraint_families(constraints_mode_label)
    domain_cfg = _validate_domain_case_config(
        dict(section_cfg.get("domain", {}))
    )
    zone_meshing_cfg = _validate_zone_meshing_case_config(
        dict(section_cfg.get("zone_meshing", {}))
    )
    geology_cfg = None
    if constraint_families.geology_interface:
        geology_cfg = _validate_geology_case_config(
            dict(section_cfg.get("geology", {}))
        )
    rivers_cfg = None
    if constraint_families.river:
        rivers_cfg = _validate_rivers_case_config(
            dict(section_cfg.get("rivers", {})),
            section=section,
        )

    return ZoneConformalCaseConfig(
        constraint_families=constraint_families,
        constraints_mode_label=constraints_mode_label,
        geology=geology_cfg,
        rivers=rivers_cfg,
        domain=domain_cfg,
        zone_meshing=zone_meshing_cfg,
        output_mesh=section_cfg.get("output_mesh"),
        output_summary_json=section_cfg.get("output_summary_json"),
        output_figure=section_cfg.get("output_figure"),
        output_figure_regional=section_cfg.get("output_figure_regional"),
    )


__all__ = [
    "_resolve_case_config",
    "_resolve_constraint_families",
    "_resolve_constraints_mode",
    "_validate_rivers_case_config",
]
