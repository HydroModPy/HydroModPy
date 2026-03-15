"""Generate 2D planar meshes that follow polygonal zone boundaries exactly.

This is the main algorithmic module for the zone-conformal extension. It takes
clean polygonal partitions, drives the Gmsh mesher, and returns meshes whose
edges respect the requested geological or zonal interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import polygonize, snap, unary_union

from hydromodpy.data_managers.geology.geology_io import load_vector_geology_dataframe
from hydromodpy.data_managers.geology.geology_processing import normalize_zone_key
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D

try:  # Shapely >= 2
    from shapely import make_valid as _shapely_make_valid
except ImportError:  # pragma: no cover - depends on environment
    from shapely.validation import make_valid as _shapely_make_valid  # type: ignore[no-redef]


_GMSH_ALGORITHM_BY_NAME = {
    "meshadapt": 1,
    "automatic": 2,
    "delaunay": 5,
    "frontal": 6,
}


@dataclass(frozen=True)
class ZonePartitionFace:
    """One partition face carrying one stable zone key."""

    face_id: int
    zone_key: str
    polygon: Polygon

    @property
    def area(self) -> float:
        return float(self.polygon.area)


@dataclass(frozen=True)
class ZoneConformalPartition:
    """One clean planar partition of polygonal zones."""

    faces: tuple[ZonePartitionFace, ...]
    zone_keys: tuple[str, ...]
    domain_geometry: Polygon | MultiPolygon
    covered_area: float
    cleaning_diagnostics: Mapping[str, Any] | None = None

    @property
    def n_faces(self) -> int:
        return int(len(self.faces))

    @property
    def domain_area(self) -> float:
        return float(self.domain_geometry.area)

    @property
    def face_counts_by_zone(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for face in self.faces:
            counts[face.zone_key] = counts.get(face.zone_key, 0) + 1
        return counts

    @property
    def face_areas_by_zone(self) -> dict[str, float]:
        areas: dict[str, float] = {}
        for face in self.faces:
            areas[face.zone_key] = areas.get(face.zone_key, 0.0) + float(face.area)
        return areas


@dataclass(frozen=True)
class ZoneConformalMeshResult:
    """Result bundle for one generated conformal planar mesh."""

    mesh: GmshPlanarMesh2D
    partition: ZoneConformalPartition
    output_path: Path
    physical_groups: tuple["ZoneConformalPhysicalGroup", ...]
    summary: Mapping[str, Any]


@dataclass(frozen=True)
class ZoneConformalPhysicalGroup:
    """Structured description of one physical group created during meshing."""

    dimension: int
    tag: int
    name: str
    group_kind: str
    entity_tags: tuple[int, ...]
    zone_keys: tuple[str, ...] = ()

    @property
    def entity_count(self) -> int:
        return int(len(self.entity_tags))

    def to_summary(self) -> dict[str, Any]:
        return {
            "dimension": int(self.dimension),
            "tag": int(self.tag),
            "name": str(self.name),
            "group_kind": str(self.group_kind),
            "entity_count": int(self.entity_count),
            "zone_keys": [str(zone_key) for zone_key in self.zone_keys],
        }


def _require_gmsh():
    try:
        import gmsh  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "gmsh is required for zone-conformal mesh generation. "
            "Install the 'gmsh' Python package to use this workflow."
        ) from exc
    return gmsh


def _is_running_under_pytest() -> bool:
    return ("PYTEST_CURRENT_TEST" in os.environ) or ("pytest" in sys.modules)


def _configure_gmsh_terminal_output(gmsh) -> None:
    """Silence verbose Gmsh terminal traces during pytest runs."""
    if not _is_running_under_pytest():
        return
    for option_name, option_value in (
        ("General.Terminal", 0.0),
        ("General.Verbosity", 0.0),
    ):
        try:
            gmsh.option.setNumber(option_name, option_value)
        except Exception:
            continue


def _as_metric_tolerance(raw: float | None, *, default: float = 0.0) -> float:
    if raw is None:
        return float(default)
    value = float(raw)
    if not np.isfinite(value) or value < 0.0:
        raise ValueError("tolerances must be finite and >= 0")
    return value


def _is_invalid_nonempty_geometry(geometry) -> bool:
    if geometry is None:
        return False
    if getattr(geometry, "is_empty", False):
        return False
    return bool(not getattr(geometry, "is_valid", True))


def _make_valid_geometry(geometry):
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


def _iter_polygon_parts(geometry):
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
            yield from _iter_polygon_parts(sub_geometry)


def _clean_domain_geometry(
    domain_geometry,
    *,
    simplify_tolerance: float,
    heal_tolerance: float,
    min_polygon_area: float,
) -> tuple[Any, dict[str, Any]]:
    invalid_before = _is_invalid_nonempty_geometry(domain_geometry)
    domain_valid = _make_valid_geometry(domain_geometry)
    invalid_after_repair = _is_invalid_nonempty_geometry(domain_valid)
    repaired_count = 1 if (invalid_before and (not invalid_after_repair)) else 0

    if heal_tolerance > 0.0:
        domain_valid = snap(domain_valid, domain_valid, heal_tolerance)
        domain_valid = _make_valid_geometry(domain_valid)
    if simplify_tolerance > 0.0:
        domain_valid = domain_valid.simplify(simplify_tolerance, preserve_topology=True)
        domain_valid = _make_valid_geometry(domain_valid)

    all_parts = [polygon for polygon in _iter_polygon_parts(domain_valid)]
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


def _clean_zone_rows(
    gdf,
    *,
    zone_key_column: str,
    priority_column: str | None,
    domain_geometry,
    simplify_tolerance: float,
    heal_tolerance: float,
    min_polygon_area: float,
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
        zone_key = normalize_zone_key(raw_zone_key)
        if zone_key == "":
            diagnostics["features_skipped_empty_zone_key_count"] += 1
            continue
        raw_geometry = row.geometry
        if raw_geometry is None or raw_geometry.is_empty:
            diagnostics["features_skipped_empty_geometry_count"] += 1
            continue
        invalid_before = _is_invalid_nonempty_geometry(raw_geometry)
        if invalid_before:
            diagnostics["source_invalid_geometry_count"] += 1

        geometry = _make_valid_geometry(raw_geometry)
        invalid_after = _is_invalid_nonempty_geometry(geometry)
        if invalid_before and (not invalid_after):
            diagnostics["invalid_geometries_repaired_count"] += 1
        if geometry.is_empty:
            diagnostics["features_dropped_after_cleaning_count"] += 1
            continue
        if domain_geometry is not None:
            geometry = _make_valid_geometry(geometry.intersection(domain_geometry))
            if geometry.is_empty:
                diagnostics["features_outside_domain_count"] += 1
                continue
        diagnostics["features_after_domain_clip_count"] += 1
        if heal_tolerance > 0.0:
            geometry = snap(geometry, geometry, heal_tolerance)
            geometry = _make_valid_geometry(geometry)
            if geometry.is_empty:
                diagnostics["features_dropped_after_cleaning_count"] += 1
                continue
        if simplify_tolerance > 0.0:
            geometry = geometry.simplify(simplify_tolerance, preserve_topology=True)
            geometry = _make_valid_geometry(geometry)
            if geometry.is_empty:
                diagnostics["features_dropped_after_cleaning_count"] += 1
                continue

        priority = None
        if priority_column is not None:
            priority = float(row[priority_column])
        for polygon in _iter_polygon_parts(geometry):
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


def _group_zone_geometries(
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
        zone_key: _make_valid_geometry(unary_union(polygons))
        for zone_key, polygons in grouped_polygons.items()
    }
    return grouped_geometries, grouped_priority


def _intersection_area(geometry_a, geometry_b) -> float:
    intersection = geometry_a.intersection(geometry_b)
    if intersection.is_empty:
        return 0.0
    return float(intersection.area)


def _resolve_zone_overlaps(
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
                if _intersection_area(geometry_a, geometry_b) > overlap_tolerance:
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
        effective = _make_valid_geometry(effective)
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


def build_zone_conformal_partition_from_dataframe(
    gdf,
    *,
    zone_key_column: str = "zone_key",
    priority_column: str | None = None,
    domain_geometry=None,
    simplify_tolerance: float = 0.0,
    heal_tolerance: float = 0.0,
    min_polygon_area: float = 0.0,
) -> ZoneConformalPartition:
    """Build one clean planar partition from one GeoDataFrame of polygon zones."""
    if zone_key_column not in gdf.columns:
        raise KeyError(f"Missing zone_key column '{zone_key_column}'")
    if gdf.empty:
        raise ValueError(
            "Cannot build a conformal partition from an empty GeoDataFrame"
        )
    if priority_column is not None and priority_column not in gdf.columns:
        raise KeyError(f"Missing priority column '{priority_column}'")

    simplify_tol = _as_metric_tolerance(simplify_tolerance)
    heal_tol = _as_metric_tolerance(heal_tolerance)
    min_area = float(min_polygon_area)
    if min_area < 0.0:
        raise ValueError("min_polygon_area must be >= 0")
    overlap_tolerance = max(heal_tol * heal_tol, 1.0e-12)

    cleaned_domain = None
    domain_cleaning_diagnostics: dict[str, Any] = {
        "domain_invalid_geometry_count": 0,
        "domain_invalid_geometries_repaired_count": 0,
        "domain_polygon_parts_before_area_filter_count": 0,
        "domain_polygon_parts_removed_by_area_threshold_count": 0,
        "domain_polygon_parts_kept_count": 0,
    }
    if domain_geometry is not None:
        cleaned_domain, domain_cleaning_diagnostics = _clean_domain_geometry(
            domain_geometry,
            simplify_tolerance=simplify_tol,
            heal_tolerance=heal_tol,
            min_polygon_area=min_area,
        )

    cleaned_rows, zone_cleaning_diagnostics = _clean_zone_rows(
        gdf,
        zone_key_column=zone_key_column,
        priority_column=priority_column,
        domain_geometry=cleaned_domain,
        simplify_tolerance=simplify_tol,
        heal_tolerance=heal_tol,
        min_polygon_area=min_area,
    )
    if not cleaned_rows:
        raise ValueError("Zone cleaning produced no usable polygon")

    grouped_geometries, grouped_priority = _group_zone_geometries(cleaned_rows)
    resolved_geometries = _resolve_zone_overlaps(
        grouped_geometries,
        grouped_priority=grouped_priority,
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
    domain = _make_valid_geometry(domain)
    if domain.is_empty:
        raise ValueError("Resolved zones produced an empty meshing domain")

    linework = [domain.boundary]
    linework.extend(geometry.boundary for geometry in resolved_geometries.values())
    merged_boundaries = unary_union(linework)

    faces: list[ZonePartitionFace] = []
    for polygonized in polygonize(merged_boundaries):
        polygon = _make_valid_geometry(polygonized)
        for part in _iter_polygon_parts(polygon):
            if float(part.area) <= overlap_tolerance:
                continue
            point = part.representative_point()
            if not domain.covers(point):
                continue
            owners = [
                zone_key
                for zone_key, geometry in resolved_geometries.items()
                if geometry.covers(point)
            ]
            if len(owners) == 0:
                continue
            if len(owners) > 1:
                raise ValueError(
                    f"Ambiguous partition face ownership for point {point.wkt}"
                )
            faces.append(
                ZonePartitionFace(
                    face_id=len(faces),
                    zone_key=str(owners[0]),
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
    cleaning_diagnostics.update(
        {str(key): value for key, value in zone_cleaning_diagnostics.items()}
    )
    cleaning_diagnostics.update(
        {str(key): value for key, value in domain_cleaning_diagnostics.items()}
    )
    return ZoneConformalPartition(
        faces=tuple(faces),
        zone_keys=tuple(sorted(resolved_geometries)),
        domain_geometry=domain,
        covered_area=covered_area,
        cleaning_diagnostics=cleaning_diagnostics,
    )


def _rounded_coord(value: float, *, tolerance: float) -> float:
    if tolerance > 0.0:
        snapped = round(float(value) / tolerance) * tolerance
        return float(np.round(snapped, 12))
    return float(np.round(float(value), 12))


def _point_key(x: float, y: float, *, tolerance: float) -> tuple[float, float]:
    return (
        _rounded_coord(float(x), tolerance=tolerance),
        _rounded_coord(float(y), tolerance=tolerance),
    )


def _add_ring_loop(
    occ,
    ring_coords,
    *,
    point_registry: dict[tuple[float, float], int],
    line_registry: dict[tuple[tuple[float, float], tuple[float, float]], int],
    point_size: float,
    tolerance: float,
) -> tuple[int, list[int]]:
    coords = np.asarray(ring_coords, dtype=float)
    if coords.shape[0] < 4:
        raise ValueError("Linear rings must contain at least 4 coordinates")
    oriented_curve_tags: list[int] = []
    curve_tags_abs: list[int] = []
    for idx in range(coords.shape[0] - 1):
        x0, y0 = float(coords[idx, 0]), float(coords[idx, 1])
        x1, y1 = float(coords[idx + 1, 0]), float(coords[idx + 1, 1])
        key0 = _point_key(x0, y0, tolerance=tolerance)
        key1 = _point_key(x1, y1, tolerance=tolerance)
        if key0 == key1:
            continue
        point_tag_0 = point_registry.get(key0)
        if point_tag_0 is None:
            point_tag_0 = occ.addPoint(key0[0], key0[1], 0.0, point_size)
            point_registry[key0] = int(point_tag_0)
        point_tag_1 = point_registry.get(key1)
        if point_tag_1 is None:
            point_tag_1 = occ.addPoint(key1[0], key1[1], 0.0, point_size)
            point_registry[key1] = int(point_tag_1)

        canonical = (key0, key1) if key0 <= key1 else (key1, key0)
        line_tag = line_registry.get(canonical)
        if line_tag is None:
            line_tag = occ.addLine(point_tag_0, point_tag_1)
            line_registry[canonical] = int(line_tag)
            oriented_curve_tags.append(int(line_tag))
        else:
            oriented_curve_tags.append(
                int(line_tag) if canonical == (key0, key1) else -int(line_tag)
            )
        curve_tags_abs.append(abs(int(line_tag)))

    if not oriented_curve_tags:
        raise ValueError("Cannot build a Gmsh curve loop from a degenerate ring")
    return occ.addCurveLoop(oriented_curve_tags), curve_tags_abs


def _apply_mesh_options(
    gmsh,
    *,
    algorithm: str,
    global_size: float,
    min_size: float | None,
    max_size: float | None,
) -> None:
    algorithm_key = str(algorithm).strip().lower()
    if algorithm_key not in _GMSH_ALGORITHM_BY_NAME:
        allowed = ", ".join(sorted(_GMSH_ALGORITHM_BY_NAME))
        raise ValueError(
            f"Unsupported Gmsh 2D algorithm '{algorithm}'. Allowed: {allowed}"
        )
    gmsh.option.setNumber(
        "Mesh.Algorithm", float(_GMSH_ALGORITHM_BY_NAME[algorithm_key])
    )
    gmsh.option.setNumber(
        "Mesh.MeshSizeMin", float(min_size if min_size is not None else global_size)
    )
    gmsh.option.setNumber(
        "Mesh.MeshSizeMax", float(max_size if max_size is not None else global_size)
    )


def _build_curve_group_name(zone_keys: set[str]) -> tuple[str, str, tuple[str, ...]]:
    zone_names = tuple(sorted(str(zone_key) for zone_key in zone_keys))
    if len(zone_names) >= 2:
        return ("interface::" + "::".join(zone_names), "interface_curve", zone_names)
    if len(zone_names) == 1:
        return (f"boundary::{zone_names[0]}", "boundary_curve", zone_names)
    raise ValueError("curve groups require at least one owning zone")


def _apply_interface_refinement_field(
    gmsh,
    *,
    interface_curve_tags: list[int],
    global_size: float,
    refine_interfaces: bool,
    interface_size: float | None,
    interface_distance: float | None,
    interface_sampling: int,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "enabled": bool(refine_interfaces),
        "interface_size": None if interface_size is None else float(interface_size),
        "interface_distance": (
            None if interface_distance is None else float(interface_distance)
        ),
        "interface_sampling": int(interface_sampling),
        "interface_curve_count": int(
            len(sorted(set(int(tag) for tag in interface_curve_tags)))
        ),
        "background_field": None,
    }
    if (not refine_interfaces) or (not interface_curve_tags):
        return summary
    if interface_size is None or interface_distance is None:
        raise ValueError(
            "interface_size and interface_distance are required when interface refinement is enabled."
        )

    field_api = gmsh.model.mesh.field
    unique_curves = sorted(set(int(tag) for tag in interface_curve_tags))

    distance_field = int(field_api.add("Distance"))
    field_api.setNumbers(distance_field, "CurvesList", unique_curves)
    field_api.setNumber(distance_field, "Sampling", float(interface_sampling))

    threshold_field = int(field_api.add("Threshold"))
    field_api.setNumber(threshold_field, "IField", float(distance_field))
    field_api.setNumber(threshold_field, "LcMin", float(interface_size))
    field_api.setNumber(threshold_field, "LcMax", float(global_size))
    field_api.setNumber(threshold_field, "DistMin", 0.0)
    field_api.setNumber(threshold_field, "DistMax", float(interface_distance))

    background_field = int(field_api.add("Min"))
    field_api.setNumbers(background_field, "FieldsList", [threshold_field])
    field_api.setAsBackgroundMesh(background_field)

    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0.0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0.0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0.0)

    summary["background_field"] = {
        "distance_field_tag": int(distance_field),
        "threshold_field_tag": int(threshold_field),
        "background_field_tag": int(background_field),
    }
    return summary


def generate_zone_conformal_mesh_from_dataframe(
    gdf,
    *,
    output_path: str | Path,
    zone_key_column: str = "zone_key",
    priority_column: str | None = None,
    domain_geometry=None,
    global_size: float = 100.0,
    min_size: float | None = None,
    max_size: float | None = None,
    simplify_tolerance: float = 0.0,
    heal_tolerance: float = 0.0,
    min_polygon_area: float = 0.0,
    algorithm: str = "delaunay",
    refine_interfaces: bool = False,
    interface_size: float | None = None,
    interface_distance: float | None = None,
    interface_sampling: int = 64,
    model_name: str = "zone_conformal_mesh",
) -> ZoneConformalMeshResult:
    """Generate one conformal planar mesh from polygon zones."""
    global_size_value = float(global_size)
    if not np.isfinite(global_size_value) or global_size_value <= 0.0:
        raise ValueError("global_size must be finite and > 0")
    if interface_sampling < 2:
        raise ValueError("interface_sampling must be >= 2")

    refine_interfaces_value = bool(refine_interfaces)
    interface_size_value = None if interface_size is None else float(interface_size)
    interface_distance_value = (
        None if interface_distance is None else float(interface_distance)
    )
    if refine_interfaces_value:
        if (
            interface_size_value is None
            or (not np.isfinite(interface_size_value))
            or interface_size_value <= 0.0
        ):
            raise ValueError(
                "interface_size must be finite and > 0 when refine_interfaces=true"
            )
        if interface_size_value > global_size_value:
            raise ValueError(
                "interface_size must be <= global_size when refine_interfaces=true"
            )
        if (
            interface_distance_value is None
            or (not np.isfinite(interface_distance_value))
            or interface_distance_value <= 0.0
        ):
            raise ValueError(
                "interface_distance must be finite and > 0 when refine_interfaces=true"
            )

    partition = build_zone_conformal_partition_from_dataframe(
        gdf,
        zone_key_column=zone_key_column,
        priority_column=priority_column,
        domain_geometry=domain_geometry,
        simplify_tolerance=simplify_tolerance,
        heal_tolerance=heal_tolerance,
        min_polygon_area=min_polygon_area,
    )

    gmsh = _require_gmsh()
    output_path_obj = Path(output_path).resolve()
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    point_registry: dict[tuple[float, float], int] = {}
    line_registry: dict[tuple[tuple[float, float], tuple[float, float]], int] = {}
    curve_usage: dict[int, set[str]] = {}
    surface_tags_by_zone: dict[str, list[int]] = {
        zone_key: [] for zone_key in partition.zone_keys
    }
    physical_groups: list[ZoneConformalPhysicalGroup] = []
    point_tolerance = _as_metric_tolerance(heal_tolerance)

    gmsh.initialize()
    try:
        _configure_gmsh_terminal_output(gmsh)
        gmsh.model.add(str(model_name).strip() or "zone_conformal_mesh")
        occ = gmsh.model.occ

        for face in partition.faces:
            outer_loop, outer_curve_tags = _add_ring_loop(
                occ,
                np.asarray(face.polygon.exterior.coords, dtype=float),
                point_registry=point_registry,
                line_registry=line_registry,
                point_size=global_size_value,
                tolerance=point_tolerance,
            )
            hole_loops: list[int] = []
            hole_curve_tags: list[int] = []
            for interior in face.polygon.interiors:
                hole_loop, hole_curve_tags_one = _add_ring_loop(
                    occ,
                    np.asarray(interior.coords, dtype=float),
                    point_registry=point_registry,
                    line_registry=line_registry,
                    point_size=global_size_value,
                    tolerance=point_tolerance,
                )
                hole_loops.append(int(hole_loop))
                hole_curve_tags.extend(hole_curve_tags_one)

            surface_tag = occ.addPlaneSurface([outer_loop, *hole_loops])
            surface_tags_by_zone[face.zone_key].append(int(surface_tag))

            for curve_tag in outer_curve_tags + hole_curve_tags:
                curve_usage.setdefault(int(curve_tag), set()).add(face.zone_key)

        occ.synchronize()
        _apply_mesh_options(
            gmsh,
            algorithm=algorithm,
            global_size=global_size_value,
            min_size=min_size,
            max_size=max_size,
        )

        for zone_key, surface_tags in sorted(surface_tags_by_zone.items()):
            if not surface_tags:
                continue
            physical_tag = gmsh.model.addPhysicalGroup(2, surface_tags)
            gmsh.model.setPhysicalName(2, int(physical_tag), f"zone::{zone_key}")
            physical_groups.append(
                ZoneConformalPhysicalGroup(
                    dimension=2,
                    tag=int(physical_tag),
                    name=f"zone::{zone_key}",
                    group_kind="zone_surface",
                    entity_tags=tuple(int(tag) for tag in sorted(surface_tags)),
                    zone_keys=(str(zone_key),),
                )
            )

        curve_tags_by_name: dict[str, list[int]] = {}
        for curve_tag, zone_keys in curve_usage.items():
            name, _, _ = _build_curve_group_name(zone_keys)
            curve_tags_by_name.setdefault(name, []).append(int(curve_tag))

        for name, curve_tags in sorted(curve_tags_by_name.items()):
            physical_tag = gmsh.model.addPhysicalGroup(1, sorted(curve_tags))
            gmsh.model.setPhysicalName(1, int(physical_tag), name)
            _group_name, group_kind, zone_names = _build_curve_group_name(
                set(name.split("::")[1:])
            )
            physical_groups.append(
                ZoneConformalPhysicalGroup(
                    dimension=1,
                    tag=int(physical_tag),
                    name=str(name),
                    group_kind=group_kind,
                    entity_tags=tuple(int(tag) for tag in sorted(curve_tags)),
                    zone_keys=tuple(zone_names),
                )
            )

        interface_curve_tags = [
            int(curve_tag)
            for name, curve_tags in curve_tags_by_name.items()
            if str(name).startswith("interface::")
            for curve_tag in curve_tags
        ]
        mesh_size_fields_summary = _apply_interface_refinement_field(
            gmsh,
            interface_curve_tags=interface_curve_tags,
            global_size=global_size_value,
            refine_interfaces=refine_interfaces_value,
            interface_size=interface_size_value,
            interface_distance=interface_distance_value,
            interface_sampling=int(interface_sampling),
        )

        gmsh.model.mesh.generate(2)
        # Stay compatible with the repository fallback reader when meshio is absent.
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.Binary", 0)
        gmsh.write(str(output_path_obj))
    finally:
        gmsh.finalize()

    mesh = GmshPlanarMesh2D.from_file(output_path_obj)
    physical_group_summaries = [group.to_summary() for group in physical_groups]
    surface_group_summaries = [
        group_summary
        for group_summary in physical_group_summaries
        if int(group_summary["dimension"]) == 2
    ]
    curve_group_summaries = [
        group_summary
        for group_summary in physical_group_summaries
        if int(group_summary["dimension"]) == 1
    ]
    cleaning_diagnostics = (
        {}
        if partition.cleaning_diagnostics is None
        else {str(key): value for key, value in partition.cleaning_diagnostics.items()}
    )
    tolerances = (
        dict(cleaning_diagnostics.get("tolerances", {})) if cleaning_diagnostics else {}
    )
    domain_area_value = float(partition.domain_area)
    covered_area_value = float(partition.covered_area)
    coverage_gap = abs(domain_area_value - covered_area_value)
    overlap_tolerance = (
        float(tolerances.get("overlap_tolerance", 0.0))
        if "overlap_tolerance" in tolerances
        else 0.0
    )
    coverage_tolerance = max(overlap_tolerance, 1.0e-9)
    interface_group_count = int(
        sum(1 for name in curve_tags_by_name if name.startswith("interface::"))
    )
    boundary_group_count = int(
        sum(1 for name in curve_tags_by_name if name.startswith("boundary::"))
    )

    cleaning_summary = {
        "mode": str(cleaning_diagnostics.get("cleaning_mode", "unknown")),
        "source_feature_count": int(
            cleaning_diagnostics.get("source_feature_count", 0)
        ),
        "features_after_domain_clip_count": int(
            cleaning_diagnostics.get("features_after_domain_clip_count", 0)
        ),
        "invalid_geometries_repaired_count": int(
            cleaning_diagnostics.get("invalid_geometries_repaired_count", 0)
        ),
        "polygons_removed_by_area_threshold_count": int(
            cleaning_diagnostics.get("polygons_removed_by_area_threshold_count", 0)
        ),
        "simplify_tolerance": (
            None
            if "simplify_tolerance" not in tolerances
            else float(tolerances.get("simplify_tolerance", 0.0))
        ),
        "heal_tolerance": (
            None
            if "heal_tolerance" not in tolerances
            else float(tolerances.get("heal_tolerance", 0.0))
        ),
        "min_polygon_area": (
            None
            if "min_polygon_area" not in tolerances
            else float(tolerances.get("min_polygon_area", 0.0))
        ),
        "overlap_tolerance": (
            None
            if "overlap_tolerance" not in tolerances
            else float(tolerances.get("overlap_tolerance", 0.0))
        ),
    }
    physical_groups_summary = {
        "surface_group_count": int(len(surface_group_summaries)),
        "curve_group_count": int(len(curve_group_summaries)),
        "interface_group_count": int(interface_group_count),
        "boundary_group_count": int(boundary_group_count),
    }
    qa_checks = {
        "coverage_gap": round(float(coverage_gap), 12),
        "coverage_tolerance": round(float(coverage_tolerance), 12),
        "coverage_within_tolerance": bool(coverage_gap <= coverage_tolerance),
        "has_interface_groups": bool(interface_group_count > 0),
        "has_zone_surface_groups": bool(
            len(surface_group_summaries) >= len(partition.zone_keys)
        ),
    }
    summary = {
        "summary_schema_version": "zone_conformal_sidecar_v1",
        "output_mesh": str(output_path_obj),
        "mesh_kind": str(mesh.kind),
        "cell_type": str(mesh.cell_type),
        "n_nodes": int(mesh.n_nodes),
        "n_cells": int(mesh.n_cells),
        "n_partition_faces": int(partition.n_faces),
        "zone_keys": list(partition.zone_keys),
        "face_counts_by_zone": partition.face_counts_by_zone,
        "face_areas_by_zone": {
            key: round(float(value), 12)
            for key, value in partition.face_areas_by_zone.items()
        },
        "domain_area": round(float(domain_area_value), 12),
        "covered_area": round(float(covered_area_value), 12),
        "interface_group_count": int(interface_group_count),
        "boundary_group_count": int(boundary_group_count),
        "global_size": float(global_size_value),
        "min_size": None if min_size is None else float(min_size),
        "max_size": None if max_size is None else float(max_size),
        "algorithm": str(algorithm),
        "cleaning_diagnostics": cleaning_diagnostics,
        "cleaning_summary": cleaning_summary,
        "physical_groups_summary": physical_groups_summary,
        "qa_checks": qa_checks,
        "mesh_size_fields": {
            "interface_refinement": mesh_size_fields_summary,
        },
        "surface_physical_groups": surface_group_summaries,
        "curve_physical_groups": curve_group_summaries,
    }
    return ZoneConformalMeshResult(
        mesh=mesh,
        partition=partition,
        output_path=output_path_obj,
        physical_groups=tuple(physical_groups),
        summary=summary,
    )


def generate_zone_conformal_mesh_from_geology_config(
    config: Mapping[str, Any],
    *,
    output_path: str | Path,
    config_path: str | Path | None = None,
    zone_key_column: str = "zone_key",
    priority_column: str | None = None,
    domain_geometry=None,
    global_size: float = 100.0,
    min_size: float | None = None,
    max_size: float | None = None,
    simplify_tolerance: float = 0.0,
    heal_tolerance: float = 0.0,
    min_polygon_area: float = 0.0,
    algorithm: str = "delaunay",
    refine_interfaces: bool = False,
    interface_size: float | None = None,
    interface_distance: float | None = None,
    interface_sampling: int = 64,
    model_name: str = "zone_conformal_mesh",
) -> ZoneConformalMeshResult:
    """Load one vector geology source and generate a conformal planar mesh."""
    geology_payload = load_vector_geology_dataframe(
        config,
        config_path=config_path,
        zone_key_column=zone_key_column,
    )
    return generate_zone_conformal_mesh_from_dataframe(
        geology_payload["gdf"],
        output_path=output_path,
        zone_key_column=zone_key_column,
        priority_column=priority_column,
        domain_geometry=domain_geometry,
        global_size=global_size,
        min_size=min_size,
        max_size=max_size,
        simplify_tolerance=simplify_tolerance,
        heal_tolerance=heal_tolerance,
        min_polygon_area=min_polygon_area,
        algorithm=algorithm,
        refine_interfaces=refine_interfaces,
        interface_size=interface_size,
        interface_distance=interface_distance,
        interface_sampling=interface_sampling,
        model_name=model_name,
    )
