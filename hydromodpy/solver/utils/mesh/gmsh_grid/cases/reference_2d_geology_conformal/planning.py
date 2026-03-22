"""Planning helpers for the reference 2D zone-conformal meshing case.

This module isolates the "prepare everything before calling Gmsh" logic from
the case runner. It resolves scopes, clips source geometries, normalizes
constraint inputs, and assembles the meshing contract consumed by the lower
level conformal mesher.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd

from hydromodpy.data_managers.variables.geology.io import load_vector_geology_dataframe
from hydromodpy.geographic.core.river_mesh_trace import (
    build_river_mesh_trace_from_vector,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing import ZoneLinearConstraint
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.case_config import (
    _resolve_constraint_usage,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalCaseConfig,
    ZoneConformalConstraintUsage,
    ZoneConformalDomainConfig,
    ZoneConformalGeologyConfig,
    ZoneConformalGeometryPayload,
    ZoneConformalMeshingInputs,
    ZoneConformalRiversConfig,
    ZoneConformalSourcePayload,
    ZoneConformalWatershedBoundaryConfig,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.scope_resolution import (
    _load_domain_payload,
    _load_geographic_watershed_payload,
    _resolve_scope_payload,
    _update_scope_summary_geometry,
    _valid_geometry_mask,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    clean_domain_geometry,
)


def _resolve_river_trace_for_meshing(
    *,
    river_trace: object | None,
    domain_geographic: object | None,
    rivers_cfg: ZoneConformalRiversConfig | None,
    config_path: Path,
) -> object | None:
    """Resolve the in-memory river trace payload passed to the mesher."""
    if river_trace is not None:
        return river_trace
    if rivers_cfg is None:
        return None
    source = rivers_cfg.source

    if source == "file":
        raw_path = rivers_cfg.path
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


def _build_domain_zone_dataframe(
    *,
    domain_payload: ZoneConformalGeometryPayload,
) -> tuple[ZoneConformalSourcePayload, gpd.GeoDataFrame]:
    domain_gdf = domain_payload.gdf[["geometry"]].copy()
    domain_gdf = domain_gdf.explode(index_parts=False).reset_index(drop=True)
    domain_gdf = domain_gdf[_valid_geometry_mask(domain_gdf.geometry)].copy()
    if domain_gdf.empty:
        raise ValueError("domain geometry produced no usable polygon for meshing")
    domain_gdf["zone_key"] = "domain"
    source_path = domain_payload.summary.get("domain_source_path")
    source_payload = ZoneConformalSourcePayload(
        field_id="domain_zones",
        source_kind="domain",
        source_path="<domain>" if source_path is None else str(source_path),
        n_source_features_before_domain_clip=int(len(domain_gdf)),
    )
    return source_payload, domain_gdf


def _load_clipped_geology_dataframe(
    *,
    geology_cfg: ZoneConformalGeologyConfig,
    domain_cfg: ZoneConformalDomainConfig,
    config_path: Path,
    domain_geographic: object | None,
) -> tuple[ZoneConformalSourcePayload, gpd.GeoDataFrame, ZoneConformalGeometryPayload]:
    payload = load_vector_geology_dataframe(
        geology_cfg.to_mapping(),
        config_path=config_path,
        zone_key_column="zone_key",
    )
    gdf = payload["gdf"].copy()
    source_payload = ZoneConformalSourcePayload(
        field_id=str(payload["field_id"]),
        source_kind=str(payload["source_kind"]),
        source_path=str(payload["source_path"]),
        n_source_features_before_domain_clip=int(len(gdf)),
    )
    domain_payload = _load_domain_payload(
        domain_cfg=domain_cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=gdf.crs,
    )
    clipped = gpd.clip(gdf, domain_payload.gdf)
    clipped = clipped[_valid_geometry_mask(clipped.geometry)].copy()
    if clipped.empty:
        raise ValueError(
            "The selected domain geometry does not intersect the geology source"
        )
    return source_payload, clipped, domain_payload


def _append_background_zone_outside_scope(
    *,
    zone_gdf: gpd.GeoDataFrame,
    support_domain_payload: ZoneConformalGeometryPayload,
    interface_scope_payload: ZoneConformalGeometryPayload,
) -> gpd.GeoDataFrame:
    support_geometry = support_domain_payload.geometry
    interface_geometry = interface_scope_payload.geometry
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
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    domain_geographic: object | None,
) -> tuple[
    ZoneConformalSourcePayload,
    gpd.GeoDataFrame,
    ZoneConformalGeometryPayload,
    ZoneConformalGeometryPayload,
]:
    support_domain_payload = _load_domain_payload(
        domain_cfg=cfg.domain,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=None,
    )
    if usage.uses_geology_constraints:
        geology_cfg = cfg.geology
        if geology_cfg is None:
            raise ValueError(
                "constraints_mode requires one geology configuration for "
                f"mode '{usage.constraints_mode}'."
            )
        source_payload, raw_zone_gdf, _ = _load_clipped_geology_dataframe(
            geology_cfg=geology_cfg,
            domain_cfg=cfg.domain,
            config_path=config_path,
            domain_geographic=domain_geographic,
        )
        support_domain_payload = _load_domain_payload(
            domain_cfg=cfg.domain,
            config_path=config_path,
            domain_geographic=domain_geographic,
            target_crs=raw_zone_gdf.crs,
        )
        interface_scope_payload = _resolve_scope_payload(
            scope_cfg=cfg.interface_scope,
            fallback_payload=support_domain_payload,
            config_path=config_path,
            domain_geographic=domain_geographic,
            target_crs=raw_zone_gdf.crs,
        )
        zone_gdf = gpd.clip(raw_zone_gdf, interface_scope_payload.gdf)
        zone_gdf = zone_gdf[_valid_geometry_mask(zone_gdf.geometry)].copy()
        if zone_gdf.empty:
            raise ValueError(
                "The selected interface scope does not intersect the geology source"
            )
        if not bool(
            interface_scope_payload.geometry.equals(support_domain_payload.geometry)
        ):
            zone_gdf = _append_background_zone_outside_scope(
                zone_gdf=zone_gdf,
                support_domain_payload=support_domain_payload,
                interface_scope_payload=interface_scope_payload,
            )
        return source_payload, zone_gdf, support_domain_payload, interface_scope_payload

    interface_scope_payload = _resolve_scope_payload(
        scope_cfg=cfg.interface_scope,
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
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    river_trace: object | None,
    domain_geographic: object | None,
    interface_scope_payload: ZoneConformalGeometryPayload,
) -> tuple[
    ZoneConformalRiversConfig | None,
    object | None,
    ZoneLinearConstraint | None,
]:
    if not usage.uses_river_constraints:
        return None, None, None

    rivers_cfg = cfg.rivers
    resolved_river_trace = _resolve_river_trace_for_meshing(
        river_trace=river_trace,
        domain_geographic=domain_geographic,
        rivers_cfg=rivers_cfg,
        config_path=config_path,
    )
    if rivers_cfg is None:
        raise ValueError(
            "constraints_mode requires one rivers configuration for mode "
            f"'{usage.constraints_mode}'."
        )
    if rivers_cfg.clip_to_domain:
        resolved_river_trace = _clip_river_trace_to_domain(
            river_trace=resolved_river_trace,
            domain_geometry=interface_scope_payload.geometry,
        )
    resolved_river_trace = _filter_river_trace_by_min_segment_length(
        river_trace=resolved_river_trace,
        min_segment_length=rivers_cfg.min_segment_length,
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
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    domain_geographic: object | None,
    zone_crs: object,
    domain_payload: ZoneConformalGeometryPayload,
) -> tuple[
    ZoneConformalWatershedBoundaryConfig | None,
    ZoneLinearConstraint | None,
]:
    boundary_cfg = cfg.watershed_boundary
    if boundary_cfg is None or not boundary_cfg.enabled:
        return None, None

    if domain_geographic is None:
        raise ValueError(
            "watershed_boundary.enabled=true requires one domain_geographic context with watershed_shp."
        )

    watershed_payload = _load_geographic_watershed_payload(
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=zone_crs,
    )
    watershed_geometry = watershed_payload.geometry
    smoothing_cfg = boundary_cfg.smoothing
    if smoothing_cfg.enabled:
        watershed_geometry, _ = clean_domain_geometry(
            watershed_geometry,
            simplify_tolerance=smoothing_cfg.simplify_tolerance,
            heal_tolerance=smoothing_cfg.heal_tolerance,
            min_polygon_area=smoothing_cfg.min_polygon_area,
        )

    boundary_lines = _iter_line_geometries((watershed_geometry.boundary,))
    if boundary_cfg.clip_to_domain:
        boundary_lines = _clip_line_constraint_to_domain(
            lines=boundary_lines,
            domain_geometry=domain_payload.geometry,
        )
    boundary_lines = _filter_line_constraint_by_min_segment_length(
        lines=boundary_lines,
        min_segment_length=boundary_cfg.min_segment_length,
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
            participates_in_refinement=boundary_cfg.participates_in_refinement,
        ),
    )


def _build_linear_constraint_inputs(
    *,
    usage: ZoneConformalConstraintUsage,
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    river_trace: object | None,
    domain_geographic: object | None,
    zone_crs: object,
    domain_payload: ZoneConformalGeometryPayload,
    interface_scope_payload: ZoneConformalGeometryPayload,
) -> tuple[
    ZoneConformalRiversConfig | None,
    ZoneConformalWatershedBoundaryConfig | None,
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
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    river_trace: object | None,
    domain_geographic: object | None,
) -> ZoneConformalMeshingInputs:
    usage = _resolve_constraint_usage(cfg.constraints_mode)
    interface_scope_cfg = cfg.interface_scope
    refinement_scope_cfg = cfg.refinement_scope
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
        zone_meshing_cfg=cfg.zone_meshing,
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
    "_resolve_river_trace_for_meshing",
    "_resolve_scope_payload",
    "_update_scope_summary_geometry",
    "_valid_geometry_mask",
]
