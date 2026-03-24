"""Internal polygon-partition builder for zone-conformal meshing.

This module owns the geometric construction of the clean planar partition used
as input to the Gmsh stage.  It keeps the polygon cleaning and face ownership
logic outside ``conformal.py`` so the public entry point can focus on high
level orchestration.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

import numpy as np
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_contracts import (
    ZoneDomainCleaningDiagnostics,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_utils import (
    as_metric_tolerance,
    iter_polygon_parts,
    make_valid_geometry,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._polygon_cleaning import (
    clean_domain_geometry,
    clean_zone_rows,
    group_zone_geometries,
    resolve_zone_overlaps,
)


def _select_partition_face_owner(
    *,
    part: BaseGeometry,
    point: BaseGeometry,
    resolved_geometries: Mapping[str, BaseGeometry],
    grouped_priorities: Mapping[str, float],
    overlap_tolerance: float,
    probe_radius: float,
) -> str | None:
    """Pick one stable owner for one polygonized face.

    The nominal path is unambiguous ownership through ``geometry.covers(point)``.
    When the representative point falls exactly on a shared boundary or a tiny
    numerical sliver is created by polygonization, fall back progressively to:

    1. largest face/zone overlap area;
    2. largest local overlap around a tiny buffered probe at the point;
    3. highest configured zone priority among direct point owners.
    """

    owners = [
        zone_key
        for zone_key, geometry in resolved_geometries.items()
        if geometry.covers(point)
    ]
    if len(owners) == 1:
        return str(owners[0])

    owner_by_overlap: list[tuple[float, float, float, str]] = []
    for zone_key, geometry in resolved_geometries.items():
        overlap_area = float(part.intersection(geometry).area)
        if overlap_area > overlap_tolerance:
            owner_by_overlap.append(
                (
                    overlap_area,
                    float(grouped_priorities.get(zone_key, 0.0)),
                    float(getattr(geometry, "area", 0.0)),
                    str(zone_key),
                )
            )
    if owner_by_overlap:
        return max(owner_by_overlap, key=lambda item: item[:3])[3]

    if owners:
        owner_by_priority = [
            (
                float(grouped_priorities.get(zone_key, 0.0)),
                float(getattr(resolved_geometries[zone_key], "area", 0.0)),
                str(zone_key),
            )
            for zone_key in owners
        ]
        return max(owner_by_priority, key=lambda item: item[:2])[2]

    local_probe_radius = max(float(probe_radius), np.sqrt(overlap_tolerance), 1.0e-9)
    local_probe = point.buffer(local_probe_radius)
    owner_by_probe: list[tuple[float, float, float, str]] = []
    for zone_key, geometry in resolved_geometries.items():
        local_overlap = float(local_probe.intersection(geometry).area)
        if local_overlap > 0.0:
            owner_by_probe.append(
                (
                    local_overlap,
                    float(grouped_priorities.get(zone_key, 0.0)),
                    float(getattr(geometry, "area", 0.0)),
                    str(zone_key),
                )
            )
    if owner_by_probe:
        return max(owner_by_probe, key=lambda item: item[:3])[3]

    return None


def build_partition_from_dataframe_impl(
    gdf,
    *,
    zone_key_column: str,
    priority_column: str | None,
    domain_geometry,
    simplify_tolerance: float,
    heal_tolerance: float,
    min_polygon_area: float,
    normalize_zone_key_fn: Callable[[str], str],
    partition_face_cls,
    partition_cls,
):
    """Build one clean planar partition from one GeoDataFrame of polygon zones."""
    if zone_key_column not in gdf.columns:
        raise KeyError(f"Missing zone_key column '{zone_key_column}'")
    if gdf.empty:
        raise ValueError(
            "Cannot build a conformal partition from an empty GeoDataFrame"
        )
    if priority_column is not None and priority_column not in gdf.columns:
        raise KeyError(f"Missing priority column '{priority_column}'")

    simplify_tol = as_metric_tolerance(simplify_tolerance)
    heal_tol = as_metric_tolerance(heal_tolerance)
    min_area = float(min_polygon_area)
    if min_area < 0.0:
        raise ValueError("min_polygon_area must be >= 0")
    overlap_tolerance = max(heal_tol * heal_tol, 1.0e-12)

    cleaned_domain = None
    domain_cleaning_diagnostics = ZoneDomainCleaningDiagnostics()
    if domain_geometry is not None:
        cleaned_domain, domain_cleaning_diagnostics = clean_domain_geometry(
            domain_geometry,
            simplify_tolerance=simplify_tol,
            heal_tolerance=heal_tol,
            min_polygon_area=min_area,
        )

    cleaned_rows, zone_cleaning_diagnostics = clean_zone_rows(
        gdf,
        zone_key_column=zone_key_column,
        priority_column=priority_column,
        domain_geometry=cleaned_domain,
        simplify_tolerance=simplify_tol,
        heal_tolerance=heal_tol,
        min_polygon_area=min_area,
        normalize_zone_key_fn=normalize_zone_key_fn,
    )
    if not cleaned_rows:
        raise ValueError("Zone cleaning produced no usable polygon")

    grouped = group_zone_geometries(cleaned_rows)
    resolved_geometries = resolve_zone_overlaps(
        grouped.geometries,
        grouped_priority=grouped.priorities,
        priority_column=priority_column,
        overlap_tolerance=overlap_tolerance,
    )
    if not resolved_geometries:
        raise ValueError("No zone geometry remains after overlap resolution")

    domain = (
        cleaned_domain
        if cleaned_domain is not None
        else unary_union(list(resolved_geometries.values()))
    )
    domain = make_valid_geometry(domain)
    if domain.is_empty:
        raise ValueError("Resolved zones produced an empty meshing domain")

    linework = [domain.boundary]
    linework.extend(geometry.boundary for geometry in resolved_geometries.values())
    merged_boundaries = unary_union(linework)
    owner_probe_radius = max(heal_tol, simplify_tol, 0.0)

    faces: list[Any] = []
    for polygonized in polygonize(merged_boundaries):
        polygon = make_valid_geometry(polygonized)
        for part in iter_polygon_parts(polygon):
            if float(part.area) <= overlap_tolerance:
                continue
            point = part.representative_point()
            if not domain.covers(point):
                continue
            owner = _select_partition_face_owner(
                part=part,
                point=point,
                resolved_geometries=resolved_geometries,
                grouped_priorities=grouped.priorities,
                overlap_tolerance=overlap_tolerance,
                probe_radius=owner_probe_radius,
            )
            if owner is None:
                continue
            faces.append(
                partition_face_cls(
                    face_id=len(faces),
                    zone_key=str(owner),
                    polygon=part,
                )
            )

    if not faces:
        raise ValueError("Partitioning produced no face to mesh")

    covered_area = float(sum(face.area for face in faces))
    cleaning_diagnostics = {
        "cleaning_mode": "tolerant",
        "tolerances": {
            "simplify_tolerance": float(simplify_tol),
            "heal_tolerance": float(heal_tol),
            "min_polygon_area": float(min_area),
            "overlap_tolerance": float(overlap_tolerance),
        },
        "operations_enabled": {
            "repair_invalid_geometries": True,
            "heal_snap": bool(heal_tol > 0.0),
            "simplify": bool(simplify_tol > 0.0),
            "drop_small_polygons": bool(min_area > 0.0),
        },
    }
    cleaning_diagnostics.update(zone_cleaning_diagnostics.to_mapping())
    cleaning_diagnostics.update(domain_cleaning_diagnostics.to_mapping())
    return partition_cls(
        faces=tuple(faces),
        zone_keys=tuple(sorted(resolved_geometries)),
        domain_geometry=domain,
        covered_area=covered_area,
        cleaning_diagnostics=cleaning_diagnostics,
    )
