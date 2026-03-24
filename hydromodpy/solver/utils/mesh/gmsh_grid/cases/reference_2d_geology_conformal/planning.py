"""Planning helpers for the reference 2D zone-conformal meshing case.

This layer deliberately keeps the public meshing contract small before Gmsh:

- one effective support domain,
- one zonation dataframe already clipped to that domain,
- one normalized list of linear constraints such as rivers or an optional
  smoothed watershed boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from math import hypot
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
from shapely.ops import unary_union

from hydromodpy.data_managers.variables.geology.io import load_vector_geology_dataframe
from hydromodpy.geographic.core.river_mesh_trace import (
    build_river_mesh_trace_from_vector,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalCaseConfig,
    ZoneConformalConstraintFamilies,
    ZoneConformalGeometryPayload,
    ZoneConformalMeshingDiagnostics,
    ZoneConformalMeshingInputs,
    ZoneRegionalSizeField,
    ZoneConformalRiversConfig,
    ZoneConformalSourcePayload,
    ZoneConformalWatershedBoundaryConfig,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.scope_resolution import (
    _load_domain_payload,
    _valid_geometry_mask,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing import ZoneLinearConstraint
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    iter_polygon_parts,
    make_valid_geometry,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementPolicySchema,
    ZoneMeshingSettings,
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
    if rivers_cfg is not None:
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


def _load_geology_dataframe(
    *,
    geology_cfg,
    config_path: Path,
    effective_domain_payload: ZoneConformalGeometryPayload,
) -> tuple[ZoneConformalSourcePayload, gpd.GeoDataFrame]:
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
    clipped = gpd.clip(gdf, effective_domain_payload.gdf)
    clipped = clipped[_valid_geometry_mask(clipped.geometry)].copy()
    if clipped.empty:
        raise ValueError(
            "The effective domain does not intersect the geology source"
        )
    return source_payload, clipped


def _build_domain_zone_dataframe(
    *,
    effective_domain_payload: ZoneConformalGeometryPayload,
) -> tuple[ZoneConformalSourcePayload, gpd.GeoDataFrame]:
    domain_gdf = effective_domain_payload.gdf[["geometry"]].copy()
    domain_gdf = domain_gdf.explode(index_parts=False).reset_index(drop=True)
    domain_gdf = domain_gdf[_valid_geometry_mask(domain_gdf.geometry)].copy()
    if domain_gdf.empty:
        raise ValueError("effective domain geometry produced no usable polygon")
    domain_gdf["zone_key"] = "domain"
    source_path = effective_domain_payload.summary.get("domain_source_path")
    source_payload = ZoneConformalSourcePayload(
        field_id="domain_zones",
        source_kind="domain",
        source_path="<domain>" if source_path is None else str(source_path),
        n_source_features_before_domain_clip=int(len(domain_gdf)),
    )
    return source_payload, domain_gdf


def _load_effective_domain_payload(
    *,
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    domain_geographic: object | None,
    target_crs: object,
) -> ZoneConformalGeometryPayload:
    return _load_domain_payload(
        domain_cfg=cfg.domain,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=target_crs,
    )


def _load_watershed_geometry(
    *,
    domain_geographic: object | None,
    target_crs: object,
):
    if domain_geographic is None:
        raise ValueError(
            "watershed_boundary.enabled requires one domain_geographic context with watershed_shp."
        )
    watershed_shp = getattr(domain_geographic, "watershed_shp", None)
    if watershed_shp is None:
        raise ValueError(
            "watershed_boundary.enabled requires domain_geographic.watershed_shp."
        )
    watershed_gdf = gpd.read_file(str(watershed_shp))
    if watershed_gdf.empty:
        raise ValueError("watershed_shp produced no polygon geometry.")
    if target_crs is not None and watershed_gdf.crs != target_crs:
        watershed_gdf = watershed_gdf.to_crs(target_crs)
    watershed_gdf = watershed_gdf[_valid_geometry_mask(watershed_gdf.geometry)].copy()
    if watershed_gdf.empty:
        raise ValueError("watershed_shp produced no valid polygon geometry.")
    watershed_geometry = make_valid_geometry(unary_union(list(watershed_gdf.geometry)))
    polygons = list(iter_polygon_parts(watershed_geometry))
    if not polygons:
        raise ValueError("watershed_shp produced no usable polygon geometry.")
    return make_valid_geometry(unary_union(polygons))


def _build_watershed_boundary_geometry(
    *,
    watershed_geometry,
    effective_domain_geometry,
    river_trace: object | None,
    watershed_boundary_cfg: ZoneConformalWatershedBoundaryConfig,
    zone_meshing_cfg: ZoneMeshingSettings,
):
    geometry = make_valid_geometry(watershed_geometry)
    smoothing_cfg = watershed_boundary_cfg.smoothing
    if smoothing_cfg.enabled:
        river_buffer_distance = float(smoothing_cfg.river_buffer_distance or 0.0)
        river_lines = _iter_river_lines(river_trace)
        if river_lines and river_buffer_distance > 0.0:
            river_corridor = make_valid_geometry(
                unary_union(list(river_lines)).buffer(river_buffer_distance)
            )
            geometry = make_valid_geometry(geometry.union(river_corridor))

        simplification_tolerance = float(
            zone_meshing_cfg.global_size
            if smoothing_cfg.distance is None
            else smoothing_cfg.distance
        )
        outer_bias_distance = float(smoothing_cfg.outer_bias_distance or 0.0)
        if outer_bias_distance > 0.0:
            geometry = make_valid_geometry(geometry.buffer(outer_bias_distance))
        if simplification_tolerance > 0.0:
            geometry = make_valid_geometry(
                geometry.simplify(
                    simplification_tolerance,
                    preserve_topology=True,
                )
            )

    geometry = make_valid_geometry(geometry.intersection(effective_domain_geometry))
    polygons = list(iter_polygon_parts(geometry))
    if not polygons:
        raise ValueError(
            "watershed boundary regularization produced no usable polygon inside the effective domain."
        )
    return make_valid_geometry(unary_union(polygons))


def _build_watershed_boundary_constraint(
    *,
    watershed_geometry,
    effective_domain_payload: ZoneConformalGeometryPayload,
) -> ZoneLinearConstraint | None:
    return _normalize_linear_constraint(
        name="watershed::boundary",
        kind="watershed_boundary",
        lines=_iter_line_geometries((watershed_geometry.boundary,)),
        domain_geometry=effective_domain_payload.geometry,
        min_segment_length=0.0,
        participates_in_refinement=True,
        clip_to_domain=False,
    )


def _build_watershed_boundary_plot_gdf(
    *,
    watershed_geometry,
    effective_domain_payload: ZoneConformalGeometryPayload,
) -> gpd.GeoDataFrame:
    boundary_lines = _iter_line_geometries((watershed_geometry.boundary,))
    return gpd.GeoDataFrame(
        {"name": ["watershed::boundary"] * len(boundary_lines)},
        geometry=boundary_lines,
        crs=effective_domain_payload.gdf.crs,
    )


def _build_watershed_outside_size_field(
    *,
    region_geometry,
    watershed_boundary_cfg: ZoneConformalWatershedBoundaryConfig,
    zone_meshing_cfg: ZoneMeshingSettings,
) -> ZoneRegionalSizeField | None:
    outside_cfg = watershed_boundary_cfg.outside_coarsening
    if not outside_cfg.enabled:
        return None
    if region_geometry is None:
        raise ValueError(
            "watershed_boundary.outside_coarsening.enabled requires one watershed-derived interior geometry."
        )

    inside_size = float(zone_meshing_cfg.global_size)
    outside_size = float(inside_size * float(outside_cfg.size_factor))
    grid_resolution = float(
        zone_meshing_cfg.global_size
        if outside_cfg.grid_resolution is None
        else outside_cfg.grid_resolution
    )
    transition_distance = float(
        zone_meshing_cfg.global_size
        if outside_cfg.transition_distance is None
        else outside_cfg.transition_distance
    )
    return ZoneRegionalSizeField(
        name="watershed::outside_coarsening",
        region_geometry=region_geometry,
        inside_size=inside_size,
        outside_size=outside_size,
        transition_distance=transition_distance,
        grid_resolution=grid_resolution,
    )


def _build_buffered_watershed_envelope_geometry(
    *,
    watershed_geometry,
    effective_domain_geometry,
    watershed_boundary_cfg: ZoneConformalWatershedBoundaryConfig,
    zone_meshing_cfg: ZoneMeshingSettings,
):
    geology_conformity_cfg = watershed_boundary_cfg.geology_conformity
    buffer_distance = float(
        zone_meshing_cfg.global_size
        if geology_conformity_cfg.buffer_distance is None
        else geology_conformity_cfg.buffer_distance
    )
    geometry = make_valid_geometry(watershed_geometry)
    if buffer_distance > 0.0:
        geometry = make_valid_geometry(geometry.buffer(buffer_distance))
    geometry = make_valid_geometry(geometry.intersection(effective_domain_geometry))
    polygons = list(iter_polygon_parts(geometry))
    if not polygons:
        raise ValueError(
            "watershed geology-conformity envelope produced no usable polygon inside the effective domain."
        )
    return make_valid_geometry(unary_union(polygons)), float(buffer_distance)


def _clip_zone_dataframe_to_geometry(
    *,
    zone_gdf: gpd.GeoDataFrame,
    clip_geometry,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, object]] = []
    value_columns = [column for column in zone_gdf.columns if str(column) != "geometry"]
    for _, row in zone_gdf.iterrows():
        geometry = row.geometry
        if geometry is None or bool(getattr(geometry, "is_empty", True)):
            continue
        try:
            clipped = make_valid_geometry(geometry.intersection(clip_geometry))
        except Exception:
            continue
        for polygon in iter_polygon_parts(clipped):
            record = {column: row[column] for column in value_columns}
            record["geometry"] = polygon
            rows.append(record)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=zone_gdf.crs)


def _apply_geology_conformity_mode(
    *,
    zone_gdf: gpd.GeoDataFrame,
    effective_domain_payload: ZoneConformalGeometryPayload,
    zone_meshing_cfg: ZoneMeshingSettings,
    watershed_boundary_cfg: ZoneConformalWatershedBoundaryConfig,
    watershed_geometry,
) -> tuple[gpd.GeoDataFrame, object | None, dict[str, object] | None]:
    if zone_gdf.empty:
        return zone_gdf, watershed_geometry, None

    mode = str(watershed_boundary_cfg.geology_conformity.mode)
    if mode == "full_domain":
        return zone_gdf, watershed_geometry, None

    if watershed_geometry is None:
        raise ValueError(
            "watershed_boundary.geology_conformity.mode='buffered_watershed_envelope' requires one watershed geometry."
        )

    conformity_geometry, buffer_distance = _build_buffered_watershed_envelope_geometry(
        watershed_geometry=watershed_geometry,
        effective_domain_geometry=effective_domain_payload.geometry,
        watershed_boundary_cfg=watershed_boundary_cfg,
        zone_meshing_cfg=zone_meshing_cfg,
    )
    inside_gdf = _clip_zone_dataframe_to_geometry(
        zone_gdf=zone_gdf,
        clip_geometry=conformity_geometry,
    )
    if inside_gdf.empty:
        raise ValueError(
            "buffered watershed geology-conformity mode clipped away the whole geology source."
        )

    inside_rows = inside_gdf.to_dict("records")
    for row in inside_rows:
        row["_mesh_priority"] = 1.0

    outside_geometry = make_valid_geometry(
        effective_domain_payload.geometry.difference(conformity_geometry)
    )
    outside_rows: list[dict[str, object]] = []
    for polygon in iter_polygon_parts(outside_geometry):
        outside_rows.append(
            {
                "zone_key": "outside_background",
                "_mesh_priority": 0.0,
                "geometry": polygon,
            }
        )

    combined_rows = inside_rows + outside_rows
    combined = gpd.GeoDataFrame(
        combined_rows,
        geometry="geometry",
        crs=zone_gdf.crs,
    )
    summary = {
        "mode": "buffered_watershed_envelope",
        "buffer_distance": float(buffer_distance),
        "conformity_area": float(getattr(conformity_geometry, "area", 0.0)),
        "outside_background_polygon_count": int(len(outside_rows)),
    }
    return combined, conformity_geometry, summary


def _derive_watershed_runtime_zone_meshing_config(
    *,
    zone_meshing_cfg: ZoneMeshingSettings,
    watershed_boundary_cfg: ZoneConformalWatershedBoundaryConfig,
    watershed_geometry,
) -> ZoneMeshingSettings:
    runtime_payload = zone_meshing_cfg.to_mapping()
    if not bool(runtime_payload.get("refine_interfaces", False)):
        return zone_meshing_cfg

    refinement_policy = runtime_payload.get("refinement_policy")
    if refinement_policy is None:
        refinement_policy = ZoneMeshingRefinementPolicySchema(
            enabled=True
        ).model_dump(mode="python")
    else:
        refinement_policy = dict(refinement_policy)
        refinement_policy["enabled"] = True

    families = dict(refinement_policy.get("families", {}))
    watershed_family = dict(families.get("watershed_boundary", {}))
    watershed_family["enabled"] = True
    if watershed_family.get("interface_size") is None:
        watershed_family["interface_size"] = float(runtime_payload["interface_size"])

    minx, miny, maxx, maxy = watershed_geometry.bounds
    fallback_distance = max(hypot(maxx - minx, maxy - miny), zone_meshing_cfg.global_size)
    boundary_distance = (
        fallback_distance
        if watershed_boundary_cfg.boundary_refinement_distance is None
        else float(watershed_boundary_cfg.boundary_refinement_distance)
    )
    if watershed_family.get("interface_distance") is None:
        watershed_family["interface_distance"] = float(boundary_distance)
    families["watershed_boundary"] = watershed_family
    refinement_policy["families"] = families
    runtime_payload["refinement_policy"] = refinement_policy
    return ZoneMeshingSettings.from_mapping(runtime_payload)


def _build_watershed_boundary_inputs(
    *,
    cfg: ZoneConformalCaseConfig,
    domain_geographic: object | None,
    river_trace: object | None,
    effective_domain_payload: ZoneConformalGeometryPayload,
    target_crs: object | None,
    zone_meshing_cfg: ZoneMeshingSettings,
) -> tuple[
    object | None,
    tuple[ZoneLinearConstraint, ...],
    ZoneMeshingSettings,
    gpd.GeoDataFrame | None,
    dict[str, object] | None,
]:
    if (
        not cfg.watershed_boundary.enabled
        and not cfg.watershed_boundary.outside_coarsening.enabled
        and str(cfg.watershed_boundary.geology_conformity.mode) == "full_domain"
    ):
        return None, (), zone_meshing_cfg, None, None

    watershed_geometry = _load_watershed_geometry(
        domain_geographic=domain_geographic,
        target_crs=target_crs,
    )
    watershed_geometry = _build_watershed_boundary_geometry(
        watershed_geometry=watershed_geometry,
        effective_domain_geometry=effective_domain_payload.geometry,
        river_trace=river_trace,
        watershed_boundary_cfg=cfg.watershed_boundary,
        zone_meshing_cfg=zone_meshing_cfg,
    )
    plot_gdf = _build_watershed_boundary_plot_gdf(
        watershed_geometry=watershed_geometry,
        effective_domain_payload=effective_domain_payload,
    )
    runtime_cfg = zone_meshing_cfg
    boundary_constraints: tuple[ZoneLinearConstraint, ...] = ()
    boundary_summary: dict[str, object] | None = None
    if cfg.watershed_boundary.enabled:
        boundary_constraint = _build_watershed_boundary_constraint(
            watershed_geometry=watershed_geometry,
            effective_domain_payload=effective_domain_payload,
        )
        if boundary_constraint is not None:
            boundary_constraints = (boundary_constraint,)
            runtime_cfg = _derive_watershed_runtime_zone_meshing_config(
                zone_meshing_cfg=zone_meshing_cfg,
                watershed_boundary_cfg=cfg.watershed_boundary,
                watershed_geometry=watershed_geometry,
            )
            boundary_summary = {
                "enabled": True,
                "smoothing_enabled": bool(cfg.watershed_boundary.smoothing.enabled),
                "boundary_length": float(
                    getattr(watershed_geometry.boundary, "length", 0.0)
                ),
                "boundary_area_source": float(getattr(watershed_geometry, "area", 0.0)),
            }
            if cfg.watershed_boundary.boundary_refinement_distance is not None:
                boundary_summary["boundary_refinement_distance"] = float(
                    cfg.watershed_boundary.boundary_refinement_distance
                )
            if cfg.watershed_boundary.smoothing.enabled:
                boundary_summary["smoothing"] = {
                    "distance": float(
                        zone_meshing_cfg.global_size
                        if cfg.watershed_boundary.smoothing.distance is None
                        else cfg.watershed_boundary.smoothing.distance
                    ),
                    "river_buffer_distance": float(
                        cfg.watershed_boundary.smoothing.river_buffer_distance or 0.0
                    ),
                    "outer_bias_distance": float(
                        cfg.watershed_boundary.smoothing.outer_bias_distance or 0.0
                    ),
                }

    return (
        watershed_geometry,
        boundary_constraints,
        runtime_cfg,
        plot_gdf,
        boundary_summary,
    )


def _normalize_linear_constraint(
    *,
    name: str,
    kind: str,
    lines: Iterable[object],
    domain_geometry: object,
    min_segment_length: float,
    participates_in_refinement: bool,
    clip_to_domain: bool = True,
) -> ZoneLinearConstraint | None:
    normalized_lines = list(lines)
    if clip_to_domain:
        normalized_lines = _clip_line_constraint_to_domain(
            lines=normalized_lines,
            domain_geometry=domain_geometry,
        )
    normalized_lines = _filter_line_constraint_by_min_segment_length(
        lines=normalized_lines,
        min_segment_length=min_segment_length,
    )
    if not normalized_lines:
        return None
    return ZoneLinearConstraint(
        name=name,
        kind=kind,
        lines=tuple(normalized_lines),
        participates_in_refinement=participates_in_refinement,
    )


def _build_linear_constraint_inputs(
    *,
    constraint_families: ZoneConformalConstraintFamilies,
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    river_trace: object | None,
    domain_geographic: object | None,
    effective_domain_payload: ZoneConformalGeometryPayload,
) -> tuple[object | None, tuple[ZoneLinearConstraint, ...]]:
    constraints: list[ZoneLinearConstraint] = []
    resolved_river_trace = None

    if constraint_families.river:
        rivers_cfg = cfg.rivers
        if rivers_cfg is None:
            raise ValueError("river constraints require one rivers configuration.")
        resolved_river_trace = _resolve_river_trace_for_meshing(
            river_trace=river_trace,
            domain_geographic=domain_geographic,
            rivers_cfg=rivers_cfg,
            config_path=config_path,
        )
        resolved_river_trace = (
            _clip_river_trace_to_domain(
                river_trace=resolved_river_trace,
                domain_geometry=effective_domain_payload.geometry,
            )
            if rivers_cfg.clip_to_domain
            else resolved_river_trace
        )
        resolved_river_trace = _filter_river_trace_by_min_segment_length(
            river_trace=resolved_river_trace,
            min_segment_length=rivers_cfg.min_segment_length,
        )
        if resolved_river_trace is None:
            raise ValueError(
                "river constraints mode requires one usable river trace. Provide rivers.source='file', "
                "or provide domain_geographic with one river_mesh_trace, or pass an explicit river_trace."
            )
        river_constraint = _normalize_linear_constraint(
            name="river::trace",
            kind="river_trace",
            lines=_iter_river_lines(resolved_river_trace),
            domain_geometry=effective_domain_payload.geometry,
            min_segment_length=0.0,
            participates_in_refinement=True,
            clip_to_domain=False,
        )
        if river_constraint is not None:
            constraints.append(river_constraint)

    return resolved_river_trace, tuple(constraints)


def _build_zone_source_inputs(
    *,
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    domain_geographic: object | None,
) -> tuple[
    ZoneConformalSourcePayload,
    gpd.GeoDataFrame,
    ZoneConformalGeometryPayload,
    gpd.GeoDataFrame,
]:
    if cfg.geology is not None:
        source_probe = load_vector_geology_dataframe(
            cfg.geology.to_mapping(),
            config_path=config_path,
            zone_key_column="zone_key",
        )
        target_crs = source_probe["gdf"].crs
        effective_domain_payload = _load_effective_domain_payload(
            cfg=cfg,
            config_path=config_path,
            domain_geographic=domain_geographic,
            target_crs=target_crs,
        )
        source_payload, zone_gdf = _load_geology_dataframe(
            geology_cfg=cfg.geology,
            config_path=config_path,
            effective_domain_payload=effective_domain_payload,
        )
        return (
            source_payload,
            zone_gdf,
            effective_domain_payload,
            zone_gdf.copy(),
        )

    effective_domain_payload = _load_effective_domain_payload(
        cfg=cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=None,
    )
    source_payload, zone_gdf = _build_domain_zone_dataframe(
        effective_domain_payload=effective_domain_payload,
    )
    return (
        source_payload,
        zone_gdf,
        effective_domain_payload,
        zone_gdf.copy(),
    )


def _build_zone_conformal_meshing_inputs(
    *,
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    river_trace: object | None,
    domain_geographic: object | None,
) -> ZoneConformalMeshingInputs:
    (
        source_payload,
        zone_gdf,
        effective_domain_payload,
        source_plot_gdf,
    ) = _build_zone_source_inputs(
        cfg=cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
    )
    resolved_river_trace, linear_constraints = _build_linear_constraint_inputs(
        constraint_families=cfg.constraint_families,
        cfg=cfg,
        config_path=config_path,
        river_trace=river_trace,
        domain_geographic=domain_geographic,
        effective_domain_payload=effective_domain_payload,
    )
    (
        watershed_geometry,
        watershed_boundary_constraints,
        runtime_zone_meshing_cfg,
        watershed_boundary_plot_gdf,
        watershed_boundary_summary,
    ) = _build_watershed_boundary_inputs(
        cfg=cfg,
        domain_geographic=domain_geographic,
        river_trace=resolved_river_trace,
        effective_domain_payload=effective_domain_payload,
        target_crs=effective_domain_payload.gdf.crs,
        zone_meshing_cfg=cfg.zone_meshing,
    )
    outside_region_geometry = watershed_geometry
    geology_conformity_summary: dict[str, object] | None = None
    if cfg.geology is not None:
        zone_gdf, outside_region_geometry, geology_conformity_summary = (
            _apply_geology_conformity_mode(
                zone_gdf=zone_gdf,
                effective_domain_payload=effective_domain_payload,
                zone_meshing_cfg=runtime_zone_meshing_cfg,
                watershed_boundary_cfg=cfg.watershed_boundary,
                watershed_geometry=watershed_geometry,
            )
        )
    regional_size_fields: tuple[ZoneRegionalSizeField, ...] = ()
    outside_coarsening_summary: dict[str, object] | None = None
    outside_field = _build_watershed_outside_size_field(
        region_geometry=outside_region_geometry,
        watershed_boundary_cfg=cfg.watershed_boundary,
        zone_meshing_cfg=runtime_zone_meshing_cfg,
    )
    if outside_field is not None:
        regional_size_fields = (outside_field,)
        outside_coarsening_summary = {
            "enabled": True,
            "inside_size": float(outside_field.inside_size),
            "outside_size": float(outside_field.outside_size),
            "size_factor": float(cfg.watershed_boundary.outside_coarsening.size_factor),
            "grid_resolution": float(outside_field.grid_resolution),
            "transition_distance": float(outside_field.transition_distance or 0.0),
        }

    return ZoneConformalMeshingInputs(
        constraint_families=cfg.constraint_families,
        constraints_mode_label=cfg.constraints_mode_label,
        source_payload=source_payload,
        zone_gdf=zone_gdf,
        effective_domain_payload=effective_domain_payload,
        zone_meshing_cfg=runtime_zone_meshing_cfg,
        linear_constraints=tuple(watershed_boundary_constraints) + linear_constraints,
        regional_size_fields=tuple(regional_size_fields),
        diagnostics=ZoneConformalMeshingDiagnostics(
            source_plot_gdf=source_plot_gdf,
            rivers_cfg=cfg.rivers,
            river_trace=resolved_river_trace,
            watershed_boundary_plot_gdf=watershed_boundary_plot_gdf,
            watershed_boundary_summary=watershed_boundary_summary,
            outside_coarsening_summary=outside_coarsening_summary,
            geology_conformity_summary=geology_conformity_summary,
        ),
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
            for part in getattr(geometry, "geoms", ()):
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
    "ZoneConformalConstraintFamilies",
    "ZoneConformalMeshingInputs",
    "_build_linear_constraint_inputs",
    "_build_zone_conformal_meshing_inputs",
    "_clip_line_constraint_to_domain",
    "_clip_river_trace_to_domain",
    "_filter_line_constraint_by_min_segment_length",
    "_filter_river_trace_by_min_segment_length",
    "_iter_line_geometries",
    "_iter_river_lines",
    "_resolve_river_trace_for_meshing",
]
