"""Geometry validation, cleaning and partition helpers for zone-conformal meshing.

This module isolates all Shapely-based geometry manipulation so that
``conformal.py`` can focus on the high-level partition and Gmsh workflow.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Polygon,
)
from shapely.ops import polygonize, snap, unary_union

try:  # Shapely >= 2
    from shapely import make_valid as _shapely_make_valid
except ImportError:  # pragma: no cover - depends on environment
    from shapely.validation import make_valid as _shapely_make_valid  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Metric tolerance
# ---------------------------------------------------------------------------

def as_metric_tolerance(raw: float | None, *, default: float = 0.0) -> float:
    if raw is None:
        return float(default)
    value = float(raw)
    if not np.isfinite(value) or value < 0.0:
        raise ValueError("tolerances must be finite and >= 0")
    return value


# ---------------------------------------------------------------------------
# Geometry validation / repair
# ---------------------------------------------------------------------------

def is_invalid_nonempty_geometry(geometry) -> bool:
    if geometry is None:
        return False
    if getattr(geometry, "is_empty", False):
        return False
    return bool(not getattr(geometry, "is_valid", True))


def make_valid_geometry(geometry):
    if geometry is None:
        return GeometryCollection()
    if geometry.is_empty:
        return geometry
    fixed = _shapely_make_valid(geometry)
    if fixed.is_empty:
        return fixed
    try:
        repaired = fixed.buffer(0)
    except Exception:  # pragma: no cover - defensive only
        repaired = fixed
    return repaired


def make_valid_linework(geometry):
    if geometry is None:
        return GeometryCollection()
    if geometry.is_empty:
        return geometry
    return _shapely_make_valid(geometry)


# ---------------------------------------------------------------------------
# Geometry iteration
# ---------------------------------------------------------------------------

def iter_polygon_parts(geometry):
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
        return
    if isinstance(geometry, MultiPolygon):
        for polygon in geometry.geoms:
            if not polygon.is_empty:
                yield polygon
        return
    if isinstance(geometry, GeometryCollection):
        for sub_geometry in geometry.geoms:
            yield from iter_polygon_parts(sub_geometry)


def iter_line_parts(geometry):
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, LineString):
        yield geometry
        return
    if isinstance(geometry, MultiLineString):
        for line in geometry.geoms:
            if not line.is_empty:
                yield line
        return
    if isinstance(geometry, GeometryCollection):
        for sub_geometry in geometry.geoms:
            yield from iter_line_parts(sub_geometry)


# ---------------------------------------------------------------------------
# Domain cleaning
# ---------------------------------------------------------------------------

def clean_domain_geometry(
    domain_geometry,
    *,
    simplify_tolerance: float,
    heal_tolerance: float,
    min_polygon_area: float,
) -> tuple[Any, dict[str, Any]]:
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
    polygons = [
        polygon
        for polygon in all_parts
        if float(polygon.area) > float(min_polygon_area)
    ]
    if not polygons:
        raise ValueError("domain_geometry produced no usable polygon after cleaning")
    cleaned_domain = unary_union(polygons)
    diagnostics = {
        "domain_invalid_geometry_count": int(1 if invalid_before else 0),
        "domain_invalid_geometries_repaired_count": int(repaired_count),
        "domain_polygon_parts_before_area_filter_count": int(len(all_parts)),
        "domain_polygon_parts_removed_by_area_threshold_count": int(
            len(all_parts) - len(polygons)
        ),
        "domain_polygon_parts_kept_count": int(len(polygons)),
    }
    return cleaned_domain, diagnostics


# ---------------------------------------------------------------------------
# Zone row cleaning
# ---------------------------------------------------------------------------

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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    diagnostics = {
        "source_feature_count": int(len(gdf)),
        "source_invalid_geometry_count": 0,
        "invalid_geometries_repaired_count": 0,
        "features_skipped_empty_zone_key_count": 0,
        "features_skipped_empty_geometry_count": 0,
        "features_outside_domain_count": 0,
        "features_after_domain_clip_count": 0,
        "features_dropped_after_cleaning_count": 0,
        "polygon_parts_before_area_filter_count": 0,
        "polygons_removed_by_area_threshold_count": 0,
        "polygon_parts_kept_count": 0,
    }

    for _, row in gdf.iterrows():
        raw_zone_key = row[zone_key_column]
        zone_key = normalize_zone_key_fn(raw_zone_key)
        if zone_key == "":
            diagnostics["features_skipped_empty_zone_key_count"] += 1
            continue
        raw_geometry = row.geometry
        if raw_geometry is None or raw_geometry.is_empty:
            diagnostics["features_skipped_empty_geometry_count"] += 1
            continue
        invalid_before = is_invalid_nonempty_geometry(raw_geometry)
        if invalid_before:
            diagnostics["source_invalid_geometry_count"] += 1

        geometry = make_valid_geometry(raw_geometry)
        invalid_after = is_invalid_nonempty_geometry(geometry)
        if invalid_before and (not invalid_after):
            diagnostics["invalid_geometries_repaired_count"] += 1
        if geometry.is_empty:
            diagnostics["features_dropped_after_cleaning_count"] += 1
            continue
        if domain_geometry is not None:
            geometry = make_valid_geometry(geometry.intersection(domain_geometry))
            if geometry.is_empty:
                diagnostics["features_outside_domain_count"] += 1
                continue
        diagnostics["features_after_domain_clip_count"] += 1
        if heal_tolerance > 0.0:
            geometry = snap(geometry, geometry, heal_tolerance)
            geometry = make_valid_geometry(geometry)
            if geometry.is_empty:
                diagnostics["features_dropped_after_cleaning_count"] += 1
                continue
        if simplify_tolerance > 0.0:
            geometry = geometry.simplify(simplify_tolerance, preserve_topology=True)
            geometry = make_valid_geometry(geometry)
            if geometry.is_empty:
                diagnostics["features_dropped_after_cleaning_count"] += 1
                continue

        priority = None
        if priority_column is not None:
            priority = float(row[priority_column])
        for polygon in iter_polygon_parts(geometry):
            diagnostics["polygon_parts_before_area_filter_count"] += 1
            if float(polygon.area) <= float(min_polygon_area):
                diagnostics["polygons_removed_by_area_threshold_count"] += 1
                continue
            diagnostics["polygon_parts_kept_count"] += 1
            out.append(
                {
                    "zone_key": zone_key,
                    "priority": priority,
                    "polygon": polygon,
                }
            )
    diagnostics["cleaned_zone_polygon_count"] = int(len(out))
    return out, diagnostics


# ---------------------------------------------------------------------------
# Group / overlap resolution
# ---------------------------------------------------------------------------

def group_zone_geometries(
    clean_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, float]]:
    grouped_polygons: dict[str, list[Any]] = {}
    grouped_priority: dict[str, float] = {}
    for item in clean_rows:
        zone_key = str(item["zone_key"])
        grouped_polygons.setdefault(zone_key, []).append(item["polygon"])
        if item["priority"] is not None:
            grouped_priority[zone_key] = max(
                grouped_priority.get(zone_key, float("-inf")), float(item["priority"])
            )

    grouped_geometries = {
        zone_key: make_valid_geometry(unary_union(polygons))
        for zone_key, polygons in grouped_polygons.items()
    }
    return grouped_geometries, grouped_priority


def intersection_area(geometry_a, geometry_b) -> float:
    intersection = geometry_a.intersection(geometry_b)
    if intersection.is_empty:
        return 0.0
    return float(intersection.area)


def resolve_zone_overlaps(
    grouped_geometries: Mapping[str, Any],
    *,
    grouped_priority: Mapping[str, float],
    priority_column: str | None,
    overlap_tolerance: float,
) -> dict[str, Any]:
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
    resolved: dict[str, Any] = {}
    assigned_geometry = None
    for zone_key in ordered_zone_keys:
        geometry = grouped_geometries[zone_key]
        effective = (
            geometry
            if assigned_geometry is None
            else geometry.difference(assigned_geometry)
        )
        effective = make_valid_geometry(effective)
        if not effective.is_empty and float(effective.area) > overlap_tolerance:
            resolved[zone_key] = effective
            assigned_geometry = (
                effective
                if assigned_geometry is None
                else assigned_geometry.union(effective)
            )
        elif assigned_geometry is None:
            assigned_geometry = geometry
    return {zone_key: resolved[zone_key] for zone_key in sorted(resolved)}


# ---------------------------------------------------------------------------
# Constraint lines repartitioning
# ---------------------------------------------------------------------------

def split_partition_with_constraint_lines(
    partition,
    *,
    constraint_lines: list[LineString],
    tolerance: float,
    ZonePartitionFace_cls,
    ZoneConformalPartition_cls,
):
    """Re-partition faces when constraint lines (e.g. rivers) must be honoured."""
    if not constraint_lines:
        return partition

    valid_lines: list[LineString] = []
    for line in constraint_lines:
        if line is None or line.is_empty:
            continue
        repaired = make_valid_linework(line)
        valid_lines.extend(
            piece
            for piece in iter_line_parts(repaired)
            if float(piece.length) > 0.0
        )
    if not valid_lines:
        return partition

    zone_geometries: dict[str, Any] = {}
    for face in partition.faces:
        zone_key = str(face.zone_key)
        current = zone_geometries.get(zone_key)
        zone_geometries[zone_key] = (
            face.polygon
            if current is None
            else make_valid_geometry(current.union(face.polygon))
        )

    overlap_tolerance = max(float(tolerance) * float(tolerance), 1.0e-12)
    linework = [partition.domain_geometry.boundary]
    linework.extend(face.polygon.boundary for face in partition.faces)
    linework.extend(valid_lines)
    merged_boundaries = unary_union(linework)

    faces: list = []
    for polygonized in polygonize(merged_boundaries):
        polygon = make_valid_geometry(polygonized)
        for part in iter_polygon_parts(polygon):
            if float(part.area) <= overlap_tolerance:
                continue
            point = part.representative_point()
            if not partition.domain_geometry.covers(point):
                continue
            owners = [
                zone_key
                for zone_key, geometry in zone_geometries.items()
                if geometry.covers(point)
            ]
            if not owners:
                continue
            if len(owners) == 1:
                owner = owners[0]
            else:
                owner = max(
                    owners,
                    key=lambda zone_key: float(
                        part.intersection(zone_geometries[zone_key]).area
                    ),
                )
            faces.append(
                ZonePartitionFace_cls(
                    face_id=len(faces),
                    zone_key=str(owner),
                    polygon=part,
                )
            )

    if not faces:
        raise ValueError("Constraint repartition produced no face to mesh")

    covered_area = float(sum(face.area for face in faces))
    diagnostics = {
        "constraints_partitioning_enabled": True,
        "constraint_line_count_input": int(len(constraint_lines)),
        "constraint_line_count_used": int(len(valid_lines)),
        "partition_faces_before_constraints": int(partition.n_faces),
        "partition_faces_after_constraints": int(len(faces)),
    }
    base_cleaning = (
        {}
        if partition.cleaning_diagnostics is None
        else {str(key): value for key, value in partition.cleaning_diagnostics.items()}
    )
    base_cleaning.update(diagnostics)
    return ZoneConformalPartition_cls(
        faces=tuple(faces),
        zone_keys=tuple(sorted(zone_geometries)),
        domain_geometry=partition.domain_geometry,
        covered_area=covered_area,
        cleaning_diagnostics=base_cleaning,
    )


# ---------------------------------------------------------------------------
# Linework matching
# ---------------------------------------------------------------------------

def segment_matches_linework(
    *,
    segment: LineString | None,
    linework,
    tolerance: float,
) -> bool:
    if segment is None or linework is None:
        return False
    if segment.is_empty:
        return False
    segment_length = float(segment.length)
    if segment_length <= 0.0:
        return False
    try:
        overlap_length = float(segment.intersection(linework).length)
    except Exception:
        overlap_length = 0.0
    if overlap_length >= 0.995 * segment_length:
        return True
    try:
        return float(segment.distance(linework)) <= max(float(tolerance), 1.0e-9)
    except Exception:
        return False


def segment_intersects_refinement_scope(
    *,
    segment: LineString | None,
    scope_geometry,
    tolerance: float,
) -> bool:
    if scope_geometry is None:
        return True
    if segment is None or segment.is_empty:
        return False
    try:
        intersection_geom = segment.intersection(scope_geometry)
        if not intersection_geom.is_empty and float(
            getattr(intersection_geom, "length", 0.0)
        ) > max(float(tolerance), 1.0e-9):
            return True
    except Exception:
        pass
    try:
        if bool(scope_geometry.covers(segment.representative_point())):
            return True
    except Exception:
        pass
    try:
        return float(segment.distance(scope_geometry)) <= max(float(tolerance), 1.0e-9)
    except Exception:
        return False
