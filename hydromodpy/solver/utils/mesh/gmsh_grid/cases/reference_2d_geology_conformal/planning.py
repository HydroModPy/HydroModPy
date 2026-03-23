"""Planning helpers for the reference 2D zone-conformal meshing case.

This layer now assembles one deliberately small meshing contract before Gmsh:

- one effective support domain,
- one zonation dataframe already clipped to that domain,
- one normalized list of river constraints when river meshing is enabled.

Everything else stays out of the public case contract so the conformal runner
focuses strictly on geology and/or rivers.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd

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
    ZoneConformalRiversConfig,
    ZoneConformalSourcePayload,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.scope_resolution import (
    _load_domain_payload,
    _valid_geometry_mask,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing import ZoneLinearConstraint


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
        return source_payload, zone_gdf, effective_domain_payload, zone_gdf.copy()

    effective_domain_payload = _load_effective_domain_payload(
        cfg=cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=None,
    )
    source_payload, zone_gdf = _build_domain_zone_dataframe(
        effective_domain_payload=effective_domain_payload,
    )
    return source_payload, zone_gdf, effective_domain_payload, zone_gdf.copy()


def _build_zone_conformal_meshing_inputs(
    *,
    cfg: ZoneConformalCaseConfig,
    config_path: Path,
    river_trace: object | None,
    domain_geographic: object | None,
) -> ZoneConformalMeshingInputs:
    source_payload, zone_gdf, effective_domain_payload, source_plot_gdf = (
        _build_zone_source_inputs(
            cfg=cfg,
            config_path=config_path,
            domain_geographic=domain_geographic,
        )
    )
    resolved_river_trace, linear_constraints = _build_linear_constraint_inputs(
        constraint_families=cfg.constraint_families,
        cfg=cfg,
        config_path=config_path,
        river_trace=river_trace,
        domain_geographic=domain_geographic,
        effective_domain_payload=effective_domain_payload,
    )

    return ZoneConformalMeshingInputs(
        constraint_families=cfg.constraint_families,
        constraints_mode_label=cfg.constraints_mode_label,
        source_payload=source_payload,
        zone_gdf=zone_gdf,
        effective_domain_payload=effective_domain_payload,
        zone_meshing_cfg=cfg.zone_meshing,
        linear_constraints=linear_constraints,
        diagnostics=ZoneConformalMeshingDiagnostics(
            source_plot_gdf=source_plot_gdf,
            rivers_cfg=cfg.rivers,
            river_trace=resolved_river_trace,
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
