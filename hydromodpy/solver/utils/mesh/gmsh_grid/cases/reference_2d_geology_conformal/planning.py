"""Planning helpers for the reference 2D zone-conformal meshing case.

This module isolates the "prepare everything before calling Gmsh" logic from
the case runner. It resolves scopes, clips source geometries, normalizes
constraint inputs, and assembles the meshing contract consumed by the lower
level conformal mesher.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
import pandas as pd

from hydromodpy.data_managers.variables.geology.io import load_vector_geology_dataframe
from hydromodpy.geographic.core.river_mesh_trace import (
    build_river_mesh_trace_from_vector,
)
from hydromodpy.solver.utils.mesh.gmsh_grid import load_zone_meshing_domain_geometry
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing import ZoneLinearConstraint
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    clean_domain_geometry,
)


@dataclass(frozen=True)
class ZoneConformalConstraintUsage:
    """Resolved constraint switches for one conformal meshing run."""

    constraints_mode: str
    uses_geology_constraints: bool
    uses_river_constraints: bool


@dataclass(frozen=True)
class ZoneConformalMeshingInputs:
    """Common meshing contract assembled before calling the Gmsh core."""

    usage: ZoneConformalConstraintUsage
    source_payload: Mapping[str, Any]
    zone_gdf: gpd.GeoDataFrame
    domain_payload: Mapping[str, Any]
    interface_scope_payload: Mapping[str, Any]
    refinement_scope_payload: Mapping[str, Any]
    interface_scope_is_custom: bool
    refinement_scope_is_custom: bool
    zone_meshing_cfg: Mapping[str, Any]
    rivers_cfg: Mapping[str, Any] | None
    watershed_boundary_cfg: Mapping[str, Any] | None
    resolved_river_trace: object | None
    linear_constraints: tuple[ZoneLinearConstraint, ...]


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


def _valid_geometry_mask(geometries) -> object:
    """Return one stable non-empty/non-missing mask across GeoPandas versions."""
    return (~geometries.is_empty) & (~geometries.isna())


def _update_scope_summary_geometry(
    summary: Mapping[str, Any],
    *,
    geometry,
    feature_count_after_clip: int,
) -> dict[str, Any]:
    updated = dict(summary)
    updated["domain_area"] = round(float(geometry.area), 12)
    updated["domain_bounds"] = [round(float(v), 6) for v in geometry.bounds]
    updated["domain_geometry_type"] = str(geometry.geom_type)
    updated["scope_feature_count_after_support_clip"] = int(feature_count_after_clip)
    return updated


def _resolve_river_trace_for_meshing(
    *,
    river_trace: object | None,
    domain_geographic: object | None,
    rivers_cfg: Mapping[str, Any] | None,
    config_path: Path,
) -> object | None:
    """Resolve the in-memory river trace payload passed to the mesher."""
    if river_trace is not None:
        return river_trace
    cfg = dict(rivers_cfg or {})
    source = str(cfg.get("source", "domain_geographic")).strip().lower()

    if source == "file":
        raw_path = cfg.get("path")
        if raw_path is None:
            return None
        file_path = Path(str(raw_path)).expanduser()
        if not file_path.is_absolute():
            file_path = (config_path.parent / file_path).resolve()
        if not file_path.exists():
            return None
        try:
            return build_river_mesh_trace_from_vector(
                vector_path=file_path,
                source_kind="file",
                clip_polygon_path=None,
            )
        except Exception:
            try:
                rivers = gpd.read_file(str(file_path))
                if rivers.empty:
                    return None
                rivers = rivers[_valid_geometry_mask(rivers.geometry)].copy()
                if rivers.empty:
                    return None
                return SimpleNamespace(lines=tuple(rivers.geometry.tolist()))
            except Exception:
                return None

    if domain_geographic is None:
        return None
    return getattr(domain_geographic, "river_mesh_trace", None)


def _clip_river_trace_to_domain(
    *,
    river_trace: object | None,
    domain_geometry: object,
) -> object | None:
    if river_trace is None:
        return None
    lines_attr = getattr(river_trace, "lines", None)
    if lines_attr is None:
        return river_trace

    clipped_lines = _clip_line_constraint_to_domain(
        lines=lines_attr,
        domain_geometry=domain_geometry,
    )
    if not clipped_lines:
        return None
    return SimpleNamespace(lines=tuple(clipped_lines))


def _filter_river_trace_by_min_segment_length(
    *,
    river_trace: object | None,
    min_segment_length: float,
) -> object | None:
    if river_trace is None:
        return None
    if min_segment_length <= 0.0:
        return river_trace
    lines_attr = getattr(river_trace, "lines", None)
    if lines_attr is None:
        return river_trace

    kept_lines = _filter_line_constraint_by_min_segment_length(
        lines=lines_attr,
        min_segment_length=min_segment_length,
    )
    if not kept_lines:
        return None
    return SimpleNamespace(lines=tuple(kept_lines))


def _clip_line_constraint_to_domain(
    *,
    lines: Iterable[object],
    domain_geometry: object,
) -> list[object]:
    clipped_lines: list[object] = []
    for geometry in lines:
        if geometry is None:
            continue
        try:
            clipped = geometry.intersection(domain_geometry)
        except Exception:
            clipped = geometry
        clipped_lines.extend(_iter_line_geometries((clipped,)))
    return clipped_lines


def _filter_line_constraint_by_min_segment_length(
    *,
    lines: Iterable[object],
    min_segment_length: float,
) -> list[object]:
    if min_segment_length <= 0.0:
        return _iter_line_geometries(lines)
    kept_lines: list[object] = []
    for line in _iter_line_geometries(lines):
        length = float(getattr(line, "length", 0.0))
        if length >= min_segment_length:
            kept_lines.append(line)
    return kept_lines


def _validate_rivers_case_config(
    config_data: Mapping[str, Any],
    *,
    section: str,
) -> dict[str, Any]:
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

    return {
        "source": source,
        "path": None if not path_text else path_text,
        "clip_to_domain": clip_to_domain,
        "min_segment_length": min_segment_length,
        "snap_tolerance": snap_tolerance,
    }


def _validate_watershed_boundary_case_config(
    config_data: Mapping[str, Any],
    *,
    section: str,
) -> dict[str, Any]:
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

    return {
        "enabled": enabled,
        "source": source,
        "clip_to_domain": clip_to_domain,
        "min_segment_length": _parse_non_negative("min_segment_length", 0.0),
        "participates_in_refinement": participates_in_refinement,
        "smoothing": {
            "enabled": smoothing_enabled,
            "simplify_tolerance": _parse_smoothing_non_negative(
                "simplify_tolerance", 0.0
            ),
            "heal_tolerance": _parse_smoothing_non_negative(
                "heal_tolerance", 0.0
            ),
            "min_polygon_area": _parse_smoothing_non_negative(
                "min_polygon_area", 0.0
            ),
        },
    }


def _build_domain_zone_dataframe(
    *,
    domain_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], gpd.GeoDataFrame]:
    domain_gdf = domain_payload["gdf"][["geometry"]].copy()
    domain_gdf = domain_gdf.explode(index_parts=False).reset_index(drop=True)
    domain_gdf = domain_gdf[_valid_geometry_mask(domain_gdf.geometry)].copy()
    if domain_gdf.empty:
        raise ValueError("domain geometry produced no usable polygon for meshing")
    domain_gdf["zone_key"] = "domain"
    summary = dict(domain_payload.get("summary", {}))
    source_path = summary.get("domain_source_path")
    source_payload = {
        "field_id": "domain_zones",
        "source_kind": "domain",
        "source_path": "<domain>" if source_path is None else str(source_path),
        "n_source_features_before_domain_clip": int(len(domain_gdf)),
    }
    return source_payload, domain_gdf


def _load_clipped_geology_dataframe(
    *,
    geology_cfg: Mapping[str, Any],
    domain_cfg: Mapping[str, Any],
    config_path: Path,
    domain_geographic: object | None,
):
    payload = load_vector_geology_dataframe(
        geology_cfg,
        config_path=config_path,
        zone_key_column="zone_key",
    )
    gdf = payload["gdf"].copy()
    payload["n_source_features_before_domain_clip"] = int(len(gdf))
    domain_payload = load_zone_meshing_domain_geometry(
        domain_cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=gdf.crs,
        validate=False,
    )
    clipped = gpd.clip(gdf, domain_payload["gdf"])
    clipped = clipped[_valid_geometry_mask(clipped.geometry)].copy()
    if clipped.empty:
        raise ValueError(
            "The selected domain geometry does not intersect the geology source"
        )
    return payload, clipped, domain_payload


def _resolve_scope_payload(
    *,
    scope_cfg: Mapping[str, Any] | None,
    fallback_payload: Mapping[str, Any],
    config_path: Path,
    domain_geographic: object | None,
    target_crs: object,
) -> Mapping[str, Any]:
    if scope_cfg is None:
        return fallback_payload
    scope_payload = load_zone_meshing_domain_geometry(
        scope_cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=target_crs,
        validate=False,
    )
    clipped = gpd.clip(scope_payload["gdf"], fallback_payload["gdf"])
    clipped = clipped[_valid_geometry_mask(clipped.geometry)].copy()
    if clipped.empty:
        raise ValueError("Scope geometry does not intersect the support domain.")
    clipped_geometry = clipped.geometry.union_all()
    summary = _update_scope_summary_geometry(
        dict(scope_payload.get("summary", {})),
        geometry=clipped_geometry,
        feature_count_after_clip=int(len(clipped)),
    )
    summary["scope_clipped_to_support_domain"] = True
    return {
        "geometry": clipped_geometry,
        "gdf": clipped,
        "summary": summary,
    }


def _append_background_zone_outside_scope(
    *,
    zone_gdf: gpd.GeoDataFrame,
    support_domain_payload: Mapping[str, Any],
    interface_scope_payload: Mapping[str, Any],
) -> gpd.GeoDataFrame:
    support_geometry = support_domain_payload["geometry"]
    interface_geometry = interface_scope_payload["geometry"]
    outside_geometry = support_geometry.difference(interface_geometry)
    outside_parts = [
        geometry
        for geometry in getattr(outside_geometry, "geoms", (outside_geometry,))
        if geometry is not None
        and (not bool(getattr(geometry, "is_empty", True)))
        and float(getattr(geometry, "area", 0.0)) > 0.0
    ]
    if not outside_parts:
        return zone_gdf
    background_gdf = gpd.GeoDataFrame(
        {"zone_key": ["domain_background"] * len(outside_parts)},
        geometry=outside_parts,
        crs=zone_gdf.crs,
    )
    merged = pd.concat([zone_gdf, background_gdf], ignore_index=True)
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=zone_gdf.crs)


def _build_zone_source_inputs(
    *,
    usage: ZoneConformalConstraintUsage,
    cfg: Mapping[str, Any],
    config_path: Path,
    domain_geographic: object | None,
) -> tuple[dict[str, Any], gpd.GeoDataFrame, Mapping[str, Any], Mapping[str, Any]]:
    support_domain_payload = load_zone_meshing_domain_geometry(
        cfg["domain"],
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=None,
        validate=False,
    )
    if usage.uses_geology_constraints:
        geology_cfg = cfg.get("geology")
        if geology_cfg is None:
            raise ValueError(
                "constraints_mode requires one geology configuration for "
                f"mode '{usage.constraints_mode}'."
            )
        source_payload, raw_zone_gdf, _ = _load_clipped_geology_dataframe(
            geology_cfg=geology_cfg,
            domain_cfg=cfg["domain"],
            config_path=config_path,
            domain_geographic=domain_geographic,
        )
        support_domain_payload = load_zone_meshing_domain_geometry(
            cfg["domain"],
            config_path=config_path,
            domain_geographic=domain_geographic,
            target_crs=raw_zone_gdf.crs,
            validate=False,
        )
        interface_scope_payload = _resolve_scope_payload(
            scope_cfg=cfg.get("interface_scope"),
            fallback_payload=support_domain_payload,
            config_path=config_path,
            domain_geographic=domain_geographic,
            target_crs=raw_zone_gdf.crs,
        )
        zone_gdf = gpd.clip(raw_zone_gdf, interface_scope_payload["gdf"])
        zone_gdf = zone_gdf[_valid_geometry_mask(zone_gdf.geometry)].copy()
        if zone_gdf.empty:
            raise ValueError(
                "The selected interface scope does not intersect the geology source"
            )
        if not bool(
            interface_scope_payload["geometry"].equals(
                support_domain_payload["geometry"]
            )
        ):
            zone_gdf = _append_background_zone_outside_scope(
                zone_gdf=zone_gdf,
                support_domain_payload=support_domain_payload,
                interface_scope_payload=interface_scope_payload,
            )
        return source_payload, zone_gdf, support_domain_payload, interface_scope_payload

    interface_scope_payload = _resolve_scope_payload(
        scope_cfg=cfg.get("interface_scope"),
        fallback_payload=support_domain_payload,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=None,
    )
    source_payload, zone_gdf = _build_domain_zone_dataframe(
        domain_payload=support_domain_payload,
    )
    return source_payload, zone_gdf, support_domain_payload, interface_scope_payload


def _build_river_constraint_inputs(
    *,
    usage: ZoneConformalConstraintUsage,
    cfg: Mapping[str, Any],
    config_path: Path,
    river_trace: object | None,
    domain_geographic: object | None,
    interface_scope_payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, object | None, ZoneLinearConstraint | None]:
    if not usage.uses_river_constraints:
        return None, None, None

    rivers_cfg = dict(cfg.get("rivers") or {})
    resolved_river_trace = _resolve_river_trace_for_meshing(
        river_trace=river_trace,
        domain_geographic=domain_geographic,
        rivers_cfg=rivers_cfg,
        config_path=config_path,
    )
    if bool(rivers_cfg.get("clip_to_domain", True)):
        resolved_river_trace = _clip_river_trace_to_domain(
            river_trace=resolved_river_trace,
            domain_geometry=interface_scope_payload["geometry"],
        )
    resolved_river_trace = _filter_river_trace_by_min_segment_length(
        river_trace=resolved_river_trace,
        min_segment_length=float(rivers_cfg.get("min_segment_length", 0.0)),
    )
    if resolved_river_trace is None:
        raise ValueError(
            "constraints_mode requires one usable river trace for mode "
            f"'{usage.constraints_mode}'. Provide rivers.source='file', "
            "or provide domain_geographic with one river_mesh_trace, "
            "or pass an explicit river_trace."
        )
    river_lines = tuple(_iter_river_lines(resolved_river_trace))
    return (
        rivers_cfg,
        resolved_river_trace,
        ZoneLinearConstraint(
            name="river::trace",
            kind="river_trace",
            lines=river_lines,
            participates_in_refinement=True,
        ),
    )


def _build_watershed_boundary_constraint_inputs(
    *,
    cfg: Mapping[str, Any],
    config_path: Path,
    domain_geographic: object | None,
    zone_crs: object,
    domain_payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, ZoneLinearConstraint | None]:
    boundary_cfg = dict(cfg.get("watershed_boundary") or {})
    if not bool(boundary_cfg.get("enabled", False)):
        return None, None

    if domain_geographic is None:
        raise ValueError(
            "watershed_boundary.enabled=true requires one domain_geographic context with watershed_shp."
        )

    watershed_payload = load_zone_meshing_domain_geometry(
        {"kind": "geographic_watershed"},
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=zone_crs,
        validate=False,
    )
    watershed_geometry = watershed_payload["geometry"]
    smoothing_cfg = dict(boundary_cfg.get("smoothing") or {})
    if bool(smoothing_cfg.get("enabled", False)):
        watershed_geometry, _ = clean_domain_geometry(
            watershed_geometry,
            simplify_tolerance=float(smoothing_cfg.get("simplify_tolerance", 0.0)),
            heal_tolerance=float(smoothing_cfg.get("heal_tolerance", 0.0)),
            min_polygon_area=float(smoothing_cfg.get("min_polygon_area", 0.0)),
        )

    boundary_lines = _iter_line_geometries((watershed_geometry.boundary,))
    if bool(boundary_cfg.get("clip_to_domain", True)):
        boundary_lines = _clip_line_constraint_to_domain(
            lines=boundary_lines,
            domain_geometry=domain_payload["geometry"],
        )
    boundary_lines = _filter_line_constraint_by_min_segment_length(
        lines=boundary_lines,
        min_segment_length=float(boundary_cfg.get("min_segment_length", 0.0)),
    )
    if not boundary_lines:
        raise ValueError(
            "watershed_boundary.enabled=true produced no usable watershed-boundary segments "
            "after smoothing/clipping. Check domain_geographic.watershed_shp and the support domain."
        )

    return (
        boundary_cfg,
        ZoneLinearConstraint(
            name="watershed::boundary",
            kind="watershed_boundary",
            lines=tuple(boundary_lines),
            participates_in_refinement=bool(
                boundary_cfg.get("participates_in_refinement", False)
            ),
        ),
    )


def _build_linear_constraint_inputs(
    *,
    usage: ZoneConformalConstraintUsage,
    cfg: Mapping[str, Any],
    config_path: Path,
    river_trace: object | None,
    domain_geographic: object | None,
    zone_crs: object,
    domain_payload: Mapping[str, Any],
    interface_scope_payload: Mapping[str, Any],
) -> tuple[
    Mapping[str, Any] | None,
    Mapping[str, Any] | None,
    object | None,
    tuple[ZoneLinearConstraint, ...],
]:
    rivers_cfg, resolved_river_trace, river_constraint = _build_river_constraint_inputs(
        usage=usage,
        cfg=cfg,
        config_path=config_path,
        river_trace=river_trace,
        domain_geographic=domain_geographic,
        interface_scope_payload=interface_scope_payload,
    )
    watershed_boundary_cfg, watershed_boundary_constraint = (
        _build_watershed_boundary_constraint_inputs(
            cfg=cfg,
            config_path=config_path,
            domain_geographic=domain_geographic,
            zone_crs=zone_crs,
            domain_payload=domain_payload,
        )
    )
    constraints = tuple(
        constraint
        for constraint in (river_constraint, watershed_boundary_constraint)
        if constraint is not None
    )
    return (
        rivers_cfg,
        watershed_boundary_cfg,
        resolved_river_trace,
        constraints,
    )


def _build_zone_conformal_meshing_inputs(
    *,
    cfg: Mapping[str, Any],
    config_path: Path,
    river_trace: object | None,
    domain_geographic: object | None,
) -> ZoneConformalMeshingInputs:
    usage = _resolve_constraint_usage(str(cfg["constraints_mode"]))
    interface_scope_cfg = cfg.get("interface_scope")
    refinement_scope_cfg = cfg.get("refinement_scope")
    source_payload, zone_gdf, domain_payload, interface_scope_payload = (
        _build_zone_source_inputs(
            usage=usage,
            cfg=cfg,
            config_path=config_path,
            domain_geographic=domain_geographic,
        )
    )
    refinement_scope_payload = _resolve_scope_payload(
        scope_cfg=refinement_scope_cfg,
        fallback_payload=interface_scope_payload,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=zone_gdf.crs,
    )
    rivers_cfg, watershed_boundary_cfg, resolved_river_trace, linear_constraints = (
        _build_linear_constraint_inputs(
            usage=usage,
            cfg=cfg,
            config_path=config_path,
            river_trace=river_trace,
            domain_geographic=domain_geographic,
            zone_crs=zone_gdf.crs,
            domain_payload=domain_payload,
            interface_scope_payload=interface_scope_payload,
        )
    )
    return ZoneConformalMeshingInputs(
        usage=usage,
        source_payload=source_payload,
        zone_gdf=zone_gdf,
        domain_payload=domain_payload,
        interface_scope_payload=interface_scope_payload,
        refinement_scope_payload=refinement_scope_payload,
        interface_scope_is_custom=interface_scope_cfg is not None,
        refinement_scope_is_custom=refinement_scope_cfg is not None,
        zone_meshing_cfg=dict(cfg["zone_meshing"]),
        rivers_cfg=rivers_cfg,
        watershed_boundary_cfg=watershed_boundary_cfg,
        resolved_river_trace=resolved_river_trace,
        linear_constraints=linear_constraints,
    )


def _iter_line_geometries(geometries: Iterable[object]) -> list[object]:
    out: list[object] = []
    for geometry in geometries:
        if geometry is None:
            continue
        geom_type = str(getattr(geometry, "geom_type", ""))
        if geom_type == "LineString":
            if not bool(getattr(geometry, "is_empty", True)):
                out.append(geometry)
            continue
        if geom_type == "MultiLineString":
            parts = getattr(geometry, "geoms", ())
            for part in parts:
                if not bool(getattr(part, "is_empty", True)):
                    out.append(part)
            continue
        if geom_type == "GeometryCollection":
            out.extend(_iter_line_geometries(getattr(geometry, "geoms", ())))
    return out


def _iter_river_lines(river_trace: object | None) -> list[object]:
    if river_trace is None:
        return []
    lines = getattr(river_trace, "lines", None)
    if lines is None:
        return []
    return _iter_line_geometries(lines)


__all__ = [
    "ZoneConformalConstraintUsage",
    "ZoneConformalMeshingInputs",
    "_append_background_zone_outside_scope",
    "_build_domain_zone_dataframe",
    "_build_linear_constraint_inputs",
    "_build_river_constraint_inputs",
    "_build_watershed_boundary_constraint_inputs",
    "_build_zone_conformal_meshing_inputs",
    "_build_zone_source_inputs",
    "_clip_line_constraint_to_domain",
    "_clip_river_trace_to_domain",
    "_filter_line_constraint_by_min_segment_length",
    "_filter_river_trace_by_min_segment_length",
    "_iter_line_geometries",
    "_iter_river_lines",
    "_load_clipped_geology_dataframe",
    "_resolve_constraint_usage",
    "_resolve_constraints_mode",
    "_resolve_river_trace_for_meshing",
    "_resolve_scope_payload",
    "_update_scope_summary_geometry",
    "_valid_geometry_mask",
    "_validate_rivers_case_config",
    "_validate_watershed_boundary_case_config",
]
