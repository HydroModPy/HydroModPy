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
    ZoneConformalWatershedBoundaryConfig,
    ZoneConformalWatershedGeologyConformityConfig,
    ZoneConformalWatershedOutsideCoarseningConfig,
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

    def _optional_non_negative_float(key: str) -> float | None:
        value = raw.get(key)
        if value is None:
            return None
        try:
            out = float(value)
        except Exception as exc:
            raise ValueError(
                f"[{section}.watershed_boundary].{key} must be a number, got '{value}'."
            ) from exc
        if out < 0.0:
            raise ValueError(
                f"[{section}.watershed_boundary].{key} must be >= 0."
            )
        return out

    enabled = bool(raw.get("enabled", False))
    smoothing_raw = raw.get("smoothing", {})
    if smoothing_raw is None:
        smoothing_raw = {}
    if not isinstance(smoothing_raw, Mapping):
        raise ValueError(
            f"[{section}.watershed_boundary.smoothing] configuration must be a mapping"
        )
    smoothing_cfg = dict(smoothing_raw)
    smoothing_enabled = bool(smoothing_cfg.get("enabled", False))
    outside_coarsening_raw = raw.get("outside_coarsening", {})
    if outside_coarsening_raw is None:
        outside_coarsening_raw = {}
    if not isinstance(outside_coarsening_raw, Mapping):
        raise ValueError(
            f"[{section}.watershed_boundary.outside_coarsening] configuration must be a mapping"
        )
    outside_coarsening_cfg = dict(outside_coarsening_raw)
    outside_coarsening_enabled = bool(outside_coarsening_cfg.get("enabled", False))
    geology_conformity_raw = raw.get("geology_conformity", {})
    if geology_conformity_raw is None:
        geology_conformity_raw = {}
    if not isinstance(geology_conformity_raw, Mapping):
        raise ValueError(
            f"[{section}.watershed_boundary.geology_conformity] configuration must be a mapping"
        )
    geology_conformity_cfg = dict(geology_conformity_raw)

    def _optional_smoothing_float(key: str) -> float | None:
        value = smoothing_cfg.get(key)
        if value is None:
            return None
        try:
            out = float(value)
        except Exception as exc:
            raise ValueError(
                f"[{section}.watershed_boundary.smoothing].{key} must be a number, got '{value}'."
            ) from exc
        if out < 0.0:
            raise ValueError(
                f"[{section}.watershed_boundary.smoothing].{key} must be >= 0."
            )
        return out

    def _outside_coarsening_float(
        key: str,
        *,
        minimum: float,
        allow_equal: bool = True,
    ) -> float | None:
        value = outside_coarsening_cfg.get(key)
        if value is None:
            return None
        try:
            out = float(value)
        except Exception as exc:
            raise ValueError(
                f"[{section}.watershed_boundary.outside_coarsening].{key} must be a number, got '{value}'."
            ) from exc
        if (out < minimum) or ((not allow_equal) and out == minimum):
            comparator = ">=" if allow_equal else ">"
            raise ValueError(
                f"[{section}.watershed_boundary.outside_coarsening].{key} must be {comparator} {minimum}."
            )
        return out

    size_factor = _outside_coarsening_float("size_factor", minimum=1.0)
    if size_factor is None:
        size_factor = 2.0

    geology_conformity_mode = str(
        geology_conformity_cfg.get("mode", "full_domain")
    ).strip().lower()
    if geology_conformity_mode not in {"full_domain", "buffered_watershed_envelope"}:
        raise ValueError(
            f"[{section}.watershed_boundary.geology_conformity].mode must be 'full_domain' or 'buffered_watershed_envelope', got '{geology_conformity_mode}'."
        )

    return ZoneConformalWatershedBoundaryConfig(
        enabled=enabled,
        boundary_refinement_distance=_optional_non_negative_float(
            "boundary_refinement_distance"
        ),
        smoothing=ZoneConformalWatershedBoundarySmoothingConfig(
            enabled=smoothing_enabled,
            distance=None if not smoothing_enabled else _optional_smoothing_float("distance"),
            river_buffer_distance=(
                None
                if not smoothing_enabled
                else _optional_smoothing_float("river_buffer_distance")
            ),
            outer_bias_distance=(
                None
                if not smoothing_enabled
                else _optional_smoothing_float("outer_bias_distance")
            ),
        ),
        outside_coarsening=ZoneConformalWatershedOutsideCoarseningConfig(
            enabled=outside_coarsening_enabled,
            size_factor=float(size_factor),
            transition_distance=(
                None
                if not outside_coarsening_enabled
                else _outside_coarsening_float("transition_distance", minimum=0.0)
            ),
            grid_resolution=(
                None
                if not outside_coarsening_enabled
                else _outside_coarsening_float(
                    "grid_resolution",
                    minimum=0.0,
                    allow_equal=False,
                )
            ),
        ),
        geology_conformity=ZoneConformalWatershedGeologyConformityConfig(
            mode=geology_conformity_mode,
            buffer_distance=(
                None
                if geology_conformity_mode == "full_domain"
                else _outside_coarsening_float("buffer_distance", minimum=0.0)
            ),
        ),
    )


def _reject_removed_case_sections(
    section_cfg: Mapping[str, Any],
    *,
    section: str,
) -> None:
    removed_sections = (
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
    watershed_boundary_cfg = _validate_watershed_boundary_case_config(
        dict(section_cfg.get("watershed_boundary", {})),
        section=section,
    )

    return ZoneConformalCaseConfig(
        constraint_families=constraint_families,
        constraints_mode_label=constraints_mode_label,
        geology=geology_cfg,
        rivers=rivers_cfg,
        watershed_boundary=watershed_boundary_cfg,
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
    "_validate_watershed_boundary_case_config",
]
