"""Polygon cleaning, grouping and overlap resolution for zone meshing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shapely.ops import snap, unary_union

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._geometry_contracts import (
    CleanedZonePolygonRow,
    ZoneDomainCleaningDiagnostics,
    ZoneGeometry,
    ZoneGeometryGrouping,
    ZoneRowCleaningDiagnostics,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.geometry_utils import (
    is_invalid_nonempty_geometry,
    iter_polygon_parts,
    make_valid_geometry,
)


def clean_domain_geometry(
    domain_geometry,
    *,
    simplify_tolerance: float,
    heal_tolerance: float,
    min_polygon_area: float,
) -> tuple[Any, ZoneDomainCleaningDiagnostics]:
    """Clean the support-domain geometry before it is used for clipping."""
    invalid_before = is_invalid_nonempty_geometry(domain_geometry)
    domain_valid = make_valid_geometry(domain_geometry)
    invalid_after_repair = is_invalid_nonempty_geometry(domain_valid)
    repaired_count = 1 if (invalid_before and (not invalid_after_repair)) else 0

    if heal_tolerance > 0.0:
        domain_valid = snap(domain_valid, domain_valid, heal_tolerance)
        domain_valid = make_valid_geometry(domain_valid)
    if simplify_tolerance > 0.0:
        domain_valid = domain_valid.simplify(simplify_tolerance, preserve_topology=True)
        domain_valid = make_valid_geometry(domain_valid)

    all_parts = [polygon for polygon in iter_polygon_parts(domain_valid)]
    polygons = [polygon for polygon in all_parts if float(polygon.area) > float(min_polygon_area)]
    if not polygons:
        raise ValueError("domain_geometry produced no usable polygon after cleaning")
    cleaned_domain = unary_union(polygons)
    diagnostics = ZoneDomainCleaningDiagnostics(
        invalid_geometry_count=int(1 if invalid_before else 0),
        invalid_geometries_repaired_count=int(repaired_count),
        polygon_parts_before_area_filter_count=int(len(all_parts)),
        polygon_parts_removed_by_area_threshold_count=int(len(all_parts) - len(polygons)),
        polygon_parts_kept_count=int(len(polygons)),
    )
    return cleaned_domain, diagnostics


def clean_zone_rows(
    gdf,
    *,
    zone_key_column: str,
    priority_column: str | None,
    domain_geometry,
    simplify_tolerance: float,
    heal_tolerance: float,
    min_polygon_area: float,
    normalize_zone_key_fn,
) -> tuple[list[CleanedZonePolygonRow], ZoneRowCleaningDiagnostics]:
    """Clean, clip and explode raw geology rows into independent polygon parts."""
    out: list[CleanedZonePolygonRow] = []
    diagnostics = ZoneRowCleaningDiagnostics(source_feature_count=int(len(gdf)))
    counters = diagnostics.to_mapping()

    for _, row in gdf.iterrows():
        raw_zone_key = row[zone_key_column]
        zone_key = normalize_zone_key_fn(raw_zone_key)
        if zone_key == "":
            counters["features_skipped_empty_zone_key_count"] += 1
            continue
        raw_geometry = row.geometry
        if raw_geometry is None or raw_geometry.is_empty:
            counters["features_skipped_empty_geometry_count"] += 1
            continue
        invalid_before = is_invalid_nonempty_geometry(raw_geometry)
        if invalid_before:
            counters["source_invalid_geometry_count"] += 1

        geometry = make_valid_geometry(raw_geometry)
        invalid_after = is_invalid_nonempty_geometry(geometry)
        if invalid_before and (not invalid_after):
            counters["invalid_geometries_repaired_count"] += 1
        if geometry.is_empty:
            counters["features_dropped_after_cleaning_count"] += 1
            continue
        if domain_geometry is not None:
            geometry = make_valid_geometry(geometry.intersection(domain_geometry))
            if geometry.is_empty:
                counters["features_outside_domain_count"] += 1
                continue
        counters["features_after_domain_clip_count"] += 1
        if heal_tolerance > 0.0:
            geometry = snap(geometry, geometry, heal_tolerance)
            geometry = make_valid_geometry(geometry)
            if geometry.is_empty:
                counters["features_dropped_after_cleaning_count"] += 1
                continue
        if simplify_tolerance > 0.0:
            geometry = geometry.simplify(simplify_tolerance, preserve_topology=True)
            geometry = make_valid_geometry(geometry)
            if geometry.is_empty:
                counters["features_dropped_after_cleaning_count"] += 1
                continue

        priority = None
        if priority_column is not None:
            priority = float(row[priority_column])
        for polygon in iter_polygon_parts(geometry):
            counters["polygon_parts_before_area_filter_count"] += 1
            if float(polygon.area) <= float(min_polygon_area):
                counters["polygons_removed_by_area_threshold_count"] += 1
                continue
            counters["polygon_parts_kept_count"] += 1
            out.append(
                CleanedZonePolygonRow(
                    zone_key=zone_key,
                    priority=priority,
                    polygon=polygon,
                )
            )
    counters["cleaned_zone_polygon_count"] = int(len(out))
    return (
        out,
        ZoneRowCleaningDiagnostics(
            source_feature_count=int(counters["source_feature_count"]),
            source_invalid_geometry_count=int(counters["source_invalid_geometry_count"]),
            invalid_geometries_repaired_count=int(counters["invalid_geometries_repaired_count"]),
            features_skipped_empty_zone_key_count=int(
                counters["features_skipped_empty_zone_key_count"]
            ),
            features_skipped_empty_geometry_count=int(
                counters["features_skipped_empty_geometry_count"]
            ),
            features_outside_domain_count=int(counters["features_outside_domain_count"]),
            features_after_domain_clip_count=int(counters["features_after_domain_clip_count"]),
            features_dropped_after_cleaning_count=int(
                counters["features_dropped_after_cleaning_count"]
            ),
            polygon_parts_before_area_filter_count=int(
                counters["polygon_parts_before_area_filter_count"]
            ),
            polygons_removed_by_area_threshold_count=int(
                counters["polygons_removed_by_area_threshold_count"]
            ),
            polygon_parts_kept_count=int(counters["polygon_parts_kept_count"]),
            cleaned_zone_polygon_count=int(counters["cleaned_zone_polygon_count"]),
        ),
    )


def group_zone_geometries(
    clean_rows: list[CleanedZonePolygonRow],
) -> ZoneGeometryGrouping:
    """Union cleaned rows by zone key and keep the strongest priority per zone."""
    grouped_polygons: dict[str, list] = {}
    grouped_priority: dict[str, float] = {}
    for item in clean_rows:
        zone_key = str(item.zone_key)
        grouped_polygons.setdefault(zone_key, []).append(item.polygon)
        if item.priority is not None:
            grouped_priority[zone_key] = max(
                grouped_priority.get(zone_key, float("-inf")), float(item.priority)
            )

    grouped_geometries = {
        zone_key: make_valid_geometry(unary_union(polygons))
        for zone_key, polygons in grouped_polygons.items()
    }
    return ZoneGeometryGrouping(
        geometries=grouped_geometries,
        priorities=grouped_priority,
    )


def intersection_area(geometry_a, geometry_b) -> float:
    """Return the overlap area between two geometries."""
    intersection = geometry_a.intersection(geometry_b)
    if intersection.is_empty:
        return 0.0
    return float(intersection.area)


def resolve_zone_overlaps(
    grouped_geometries: Mapping[str, ZoneGeometry],
    *,
    grouped_priority: Mapping[str, float],
    priority_column: str | None,
    overlap_tolerance: float,
) -> dict[str, ZoneGeometry]:
    """Resolve overlaps between zone geometries, optionally using priorities."""
    zone_keys = sorted(str(key) for key in grouped_geometries)
    if priority_column is None:
        for idx, zone_key_a in enumerate(zone_keys):
            geometry_a = grouped_geometries[zone_key_a]
            for zone_key_b in zone_keys[idx + 1 :]:
                geometry_b = grouped_geometries[zone_key_b]
                if intersection_area(geometry_a, geometry_b) > overlap_tolerance:
                    raise ValueError(
                        "Overlapping zones detected without priority resolution: "
                        f"{zone_key_a!r} vs {zone_key_b!r}"
                    )
        return {zone_key: grouped_geometries[zone_key] for zone_key in zone_keys}

    ordered_zone_keys = sorted(
        zone_keys,
        key=lambda zone_key: (float(grouped_priority.get(zone_key, 0.0)), zone_key),
        reverse=True,
    )
    resolved: dict[str, ZoneGeometry] = {}
    assigned_geometry = None
    for zone_key in ordered_zone_keys:
        geometry = grouped_geometries[zone_key]
        effective = (
            geometry if assigned_geometry is None else geometry.difference(assigned_geometry)
        )
        effective = make_valid_geometry(effective)
        if not effective.is_empty and float(effective.area) > overlap_tolerance:
            resolved[zone_key] = effective
            assigned_geometry = (
                effective if assigned_geometry is None else assigned_geometry.union(effective)
            )
        elif assigned_geometry is None:
            assigned_geometry = geometry
    return {zone_key: resolved[zone_key] for zone_key in sorted(resolved)}


__all__ = [
    "clean_domain_geometry",
    "clean_zone_rows",
    "group_zone_geometries",
    "intersection_area",
    "resolve_zone_overlaps",
]
