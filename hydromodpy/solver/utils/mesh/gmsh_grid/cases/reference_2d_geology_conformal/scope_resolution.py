"""Support and scope geometry helpers for the conformal reference case."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    clean_domain_geometry,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.domain import (
    load_zone_meshing_domain_payload,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalDomainConfig,
    ZoneConformalGeometryPayload,
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


def _load_domain_payload(
    *,
    domain_cfg: ZoneConformalDomainConfig,
    config_path: Path,
    domain_geographic: object | None,
    target_crs: object,
) -> ZoneConformalGeometryPayload:
    return load_zone_meshing_domain_payload(
        domain_cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=target_crs,
    )


def _load_geographic_watershed_payload(
    *,
    config_path: Path,
    domain_geographic: object | None,
    target_crs: object,
) -> ZoneConformalGeometryPayload:
    return _load_domain_payload(
        domain_cfg=ZoneConformalDomainConfig(kind="geographic_watershed"),
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=target_crs,
    )


def _maybe_smooth_geographic_watershed_scope_payload(
    payload: ZoneConformalGeometryPayload,
    *,
    scope_cfg: ZoneConformalDomainConfig | None,
    watershed_boundary_cfg: object | None,
) -> ZoneConformalGeometryPayload:
    if scope_cfg is None or str(scope_cfg.kind) != "geographic_watershed":
        return payload
    if watershed_boundary_cfg is None:
        return payload
    smoothing_cfg = getattr(watershed_boundary_cfg, "smoothing", None)
    if smoothing_cfg is None or not bool(getattr(smoothing_cfg, "enabled", False)):
        return payload
    cleaned_geometry, _ = clean_domain_geometry(
        payload.geometry,
        simplify_tolerance=float(getattr(smoothing_cfg, "simplify_tolerance", 0.0)),
        heal_tolerance=float(getattr(smoothing_cfg, "heal_tolerance", 0.0)),
        min_polygon_area=float(getattr(smoothing_cfg, "min_polygon_area", 0.0)),
    )
    summary = _update_scope_summary_geometry(
        dict(payload.summary),
        geometry=cleaned_geometry,
        feature_count_after_clip=1,
    )
    summary["watershed_boundary_smoothing_applied"] = True
    summary["watershed_boundary_smoothing"] = {
        "enabled": True,
        "simplify_tolerance": float(
            getattr(smoothing_cfg, "simplify_tolerance", 0.0)
        ),
        "heal_tolerance": float(getattr(smoothing_cfg, "heal_tolerance", 0.0)),
        "min_polygon_area": float(getattr(smoothing_cfg, "min_polygon_area", 0.0)),
    }
    return ZoneConformalGeometryPayload(
        geometry=cleaned_geometry,
        gdf=gpd.GeoDataFrame(geometry=[cleaned_geometry], crs=payload.gdf.crs),
        summary=summary,
    )


def _resolve_scope_payload(
    *,
    scope_cfg: ZoneConformalDomainConfig | None,
    fallback_payload: ZoneConformalGeometryPayload,
    config_path: Path,
    domain_geographic: object | None,
    target_crs: object,
    watershed_boundary_cfg: object | None = None,
) -> ZoneConformalGeometryPayload:
    if scope_cfg is None:
        return fallback_payload
    scope_payload = _load_domain_payload(
        domain_cfg=scope_cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=target_crs,
    )
    scope_payload = _maybe_smooth_geographic_watershed_scope_payload(
        scope_payload,
        scope_cfg=scope_cfg,
        watershed_boundary_cfg=watershed_boundary_cfg,
    )
    clipped = gpd.clip(scope_payload.gdf, fallback_payload.gdf)
    clipped = clipped[_valid_geometry_mask(clipped.geometry)].copy()
    if clipped.empty:
        raise ValueError("Scope geometry does not intersect the support domain.")
    clipped_geometry = clipped.geometry.union_all()
    summary = _update_scope_summary_geometry(
        dict(scope_payload.summary),
        geometry=clipped_geometry,
        feature_count_after_clip=int(len(clipped)),
    )
    summary["scope_clipped_to_support_domain"] = True
    return ZoneConformalGeometryPayload(
        geometry=clipped_geometry,
        gdf=clipped,
        summary=summary,
    )


__all__ = [
    "_load_domain_payload",
    "_load_geographic_watershed_payload",
    "_maybe_smooth_geographic_watershed_scope_payload",
    "_resolve_scope_payload",
    "_update_scope_summary_geometry",
    "_valid_geometry_mask",
]
