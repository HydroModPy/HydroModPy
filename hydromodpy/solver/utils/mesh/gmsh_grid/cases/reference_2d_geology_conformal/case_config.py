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
    ZoneConformalConstraintUsage,
    ZoneConformalDomainConfig,
    ZoneConformalGeologyConfig,
    ZoneConformalRiversConfig,
    ZoneConformalWatershedBoundaryConfig,
    ZoneConformalWatershedBoundarySmoothingConfig,
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


def _resolve_constraint_usage(
    constraints_mode: str,
) -> ZoneConformalConstraintUsage:
    mode = _resolve_constraints_mode(constraints_mode)
    return ZoneConformalConstraintUsage(
        constraints_mode=mode,
        uses_geology_constraints=mode in {"geology_only", "geology_rivers"},
        uses_river_constraints=mode in {"rivers_only", "geology_rivers"},
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


def _validate_watershed_boundary_case_config(
    config_data: Mapping[str, Any],
    *,
    section: str,
) -> ZoneConformalWatershedBoundaryConfig:
    if not isinstance(config_data, Mapping):
        raise ValueError(
            f"[{section}.watershed_boundary] configuration must be a mapping"
        )
    raw = dict(config_data)
    enabled = bool(raw.get("enabled", False))
    source = str(raw.get("source", "domain_geographic")).strip().lower()
    if source != "domain_geographic":
        raise ValueError(
            f"[{section}.watershed_boundary].source must be 'domain_geographic', got '{source}'."
        )

    clip_to_domain = raw.get("clip_to_domain", True)
    if not isinstance(clip_to_domain, bool):
        raise ValueError(
            f"[{section}.watershed_boundary].clip_to_domain must be a boolean."
        )
    participates_in_refinement = raw.get("participates_in_refinement", False)
    if not isinstance(participates_in_refinement, bool):
        raise ValueError(
            f"[{section}.watershed_boundary].participates_in_refinement must be a boolean."
        )

    def _parse_non_negative(name: str, default: float) -> float:
        raw_value = raw.get(name, default)
        try:
            value = float(raw_value)
        except Exception as exc:
            raise ValueError(
                f"[{section}.watershed_boundary].{name} must be a number, got '{raw_value}'."
            ) from exc
        if value < 0.0:
            raise ValueError(
                f"[{section}.watershed_boundary].{name} must be >= 0."
            )
        return value

    smoothing_raw = raw.get("smoothing", {})
    if smoothing_raw is None:
        smoothing_raw = {}
    if not isinstance(smoothing_raw, Mapping):
        raise ValueError(
            f"[{section}.watershed_boundary.smoothing] configuration must be a mapping."
        )
    smoothing_enabled = bool(smoothing_raw.get("enabled", False))

    def _parse_smoothing_non_negative(name: str, default: float) -> float:
        raw_value = smoothing_raw.get(name, default)
        try:
            value = float(raw_value)
        except Exception as exc:
            raise ValueError(
                f"[{section}.watershed_boundary.smoothing].{name} must be a number, got '{raw_value}'."
            ) from exc
        if value < 0.0:
            raise ValueError(
                f"[{section}.watershed_boundary.smoothing].{name} must be >= 0."
            )
        return value

    return ZoneConformalWatershedBoundaryConfig(
        enabled=enabled,
        source=source,
        clip_to_domain=clip_to_domain,
        min_segment_length=_parse_non_negative("min_segment_length", 0.0),
        participates_in_refinement=participates_in_refinement,
        smoothing=ZoneConformalWatershedBoundarySmoothingConfig(
            enabled=smoothing_enabled,
            simplify_tolerance=_parse_smoothing_non_negative(
                "simplify_tolerance", 0.0
            ),
            heal_tolerance=_parse_smoothing_non_negative("heal_tolerance", 0.0),
            min_polygon_area=_parse_smoothing_non_negative(
                "min_polygon_area", 0.0
            ),
        ),
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
    usage = _resolve_constraint_usage(str(section_cfg.get("constraints_mode", "")))
    domain_cfg = _validate_domain_case_config(
        dict(section_cfg.get("domain", {}))
    )
    interface_scope_cfg = None
    if isinstance(section_cfg.get("interface_scope"), Mapping):
        interface_scope_cfg = _validate_domain_case_config(
            dict(section_cfg.get("interface_scope", {}))
        )
    refinement_scope_cfg = None
    if isinstance(section_cfg.get("refinement_scope"), Mapping):
        refinement_scope_cfg = _validate_domain_case_config(
            dict(section_cfg.get("refinement_scope", {}))
        )
    zone_meshing_cfg = _validate_zone_meshing_case_config(
        dict(section_cfg.get("zone_meshing", {}))
    )
    geology_cfg = None
    if usage.uses_geology_constraints:
        geology_cfg = _validate_geology_case_config(
            dict(section_cfg.get("geology", {}))
        )
    rivers_cfg = None
    if usage.uses_river_constraints:
        rivers_cfg = _validate_rivers_case_config(
            dict(section_cfg.get("rivers", {})),
            section=section,
        )
    watershed_boundary_cfg = None
    if isinstance(section_cfg.get("watershed_boundary"), Mapping):
        watershed_boundary_cfg = _validate_watershed_boundary_case_config(
            dict(section_cfg.get("watershed_boundary", {})),
            section=section,
        )
        if (
            watershed_boundary_cfg.enabled
            and domain_cfg.kind == "geographic_watershed"
        ):
            raise ValueError(
                "watershed_boundary is redundant when domain.kind='geographic_watershed'; "
                "use a larger support domain such as geographic_box_buffer if you need the catchment boundary as an internal constraint."
            )

    return ZoneConformalCaseConfig(
        constraints_mode=usage.constraints_mode,
        geology=geology_cfg,
        rivers=rivers_cfg,
        watershed_boundary=watershed_boundary_cfg,
        domain=domain_cfg,
        interface_scope=interface_scope_cfg,
        refinement_scope=refinement_scope_cfg,
        zone_meshing=zone_meshing_cfg,
        output_mesh=section_cfg.get("output_mesh"),
        output_summary_json=section_cfg.get("output_summary_json"),
        output_figure=section_cfg.get("output_figure"),
        output_figure_regional=section_cfg.get("output_figure_regional"),
    )


__all__ = [
    "_resolve_case_config",
    "_resolve_constraint_usage",
    "_resolve_constraints_mode",
    "_validate_rivers_case_config",
    "_validate_watershed_boundary_case_config",
]
