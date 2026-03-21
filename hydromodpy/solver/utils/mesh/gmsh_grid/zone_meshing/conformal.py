"""Generate 2D planar meshes that follow polygonal zone boundaries exactly.

This module exposes the public dataclasses and the high-level entry points.
The heavy lifting is delegated to:

* ``_geometry_cleaning`` — Shapely geometry validation, cleaning, partitioning
* ``_gmsh_driver`` — Gmsh Python API helpers (rings, polylines, refinement)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from shapely.geometry import LineString, Polygon, MultiPolygon
from shapely.ops import polygonize, unary_union

from hydromodpy.data_managers.variables.geology.io import load_vector_geology_dataframe
from hydromodpy.data_managers.variables.geology.processing import normalize_zone_key
from hydromodpy.solver.utils.mesh.gmsh_grid._deps import require_gmsh as _require_gmsh
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    as_metric_tolerance,
    clean_domain_geometry,
    clean_zone_rows,
    group_zone_geometries,
    iter_line_parts,
    iter_polygon_parts,
    make_valid_geometry,
    resolve_zone_overlaps,
    segment_intersects_refinement_scope,
    segment_matches_linework,
    split_partition_with_constraint_lines,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._gmsh_driver import (
    add_polyline_segments,
    add_ring_loop,
    apply_interface_refinement_field,
    apply_mesh_options,
    build_curve_group_name,
    configure_gmsh_terminal_output,
    iter_river_lines_from_trace,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


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


@dataclass(frozen=True)
class ZoneLinearConstraint:
    """One named internal line constraint that must appear in the generated mesh."""

    name: str
    kind: str
    lines: tuple[LineString, ...]
    participates_in_refinement: bool = True

    @property
    def line_count(self) -> int:
        return int(len(self.lines))


# ---------------------------------------------------------------------------
# Partition builder
# ---------------------------------------------------------------------------


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

    simplify_tol = as_metric_tolerance(simplify_tolerance)
    heal_tol = as_metric_tolerance(heal_tolerance)
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
        normalize_zone_key_fn=normalize_zone_key,
    )
    if not cleaned_rows:
        raise ValueError("Zone cleaning produced no usable polygon")

    grouped_geometries, grouped_priority = group_zone_geometries(cleaned_rows)
    resolved_geometries = resolve_zone_overlaps(
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
    domain = make_valid_geometry(domain)
    if domain.is_empty:
        raise ValueError("Resolved zones produced an empty meshing domain")

    linework = [domain.boundary]
    linework.extend(geometry.boundary for geometry in resolved_geometries.values())
    merged_boundaries = unary_union(linework)

    faces: list[ZonePartitionFace] = []
    for polygonized in polygonize(merged_boundaries):
        polygon = make_valid_geometry(polygonized)
        for part in iter_polygon_parts(polygon):
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


# ---------------------------------------------------------------------------
# Mesh generation
# ---------------------------------------------------------------------------


def _group_kind_for_constraint_kind(kind: str) -> str:
    token = str(kind).strip().lower()
    if token == "river_trace":
        return "river_curve"
    return f"{token}_curve"


def _constraint_sort_key(constraint: ZoneLinearConstraint) -> tuple[int, str]:
    token = str(constraint.kind).strip().lower()
    if token == "watershed_boundary":
        return (0, str(constraint.name))
    if token == "river_trace":
        return (1, str(constraint.name))
    return (10, str(constraint.name))


def _normalize_zone_linear_constraint(
    raw_constraint: ZoneLinearConstraint | Mapping[str, Any] | object,
) -> ZoneLinearConstraint:
    if isinstance(raw_constraint, ZoneLinearConstraint):
        return raw_constraint

    if isinstance(raw_constraint, Mapping):
        name = raw_constraint.get("name")
        kind = raw_constraint.get("kind")
        lines_attr = raw_constraint.get("lines")
        participates_in_refinement = raw_constraint.get(
            "participates_in_refinement", True
        )
    else:
        name = getattr(raw_constraint, "name", None)
        kind = getattr(raw_constraint, "kind", None)
        lines_attr = getattr(raw_constraint, "lines", None)
        participates_in_refinement = getattr(
            raw_constraint, "participates_in_refinement", True
        )

    name_text = str(name).strip()
    kind_text = str(kind).strip()
    if name_text == "":
        raise ValueError("linear constraints require one non-empty name.")
    if kind_text == "":
        raise ValueError(
            f"linear constraint '{name_text}' requires one non-empty kind."
        )
    if lines_attr is None:
        raise TypeError(
            f"linear constraint '{name_text}' must expose a 'lines' collection."
        )

    lines: list[LineString] = []
    for geometry in lines_attr:
        if geometry is None:
            continue
        for line in iter_line_parts(geometry):
            if float(line.length) > 0.0:
                lines.append(line)

    if not lines:
        raise ValueError(
            f"linear constraint '{name_text}' produced no usable line segment."
        )
    return ZoneLinearConstraint(
        name=name_text,
        kind=kind_text,
        lines=tuple(lines),
        participates_in_refinement=bool(participates_in_refinement),
    )


def _normalize_linear_constraints(
    *,
    linear_constraints: tuple[ZoneLinearConstraint | Mapping[str, Any] | object, ...]
    | None,
    river_trace: object | None,
) -> tuple[ZoneLinearConstraint, ...]:
    if linear_constraints is not None:
        out = [
            _normalize_zone_linear_constraint(raw_constraint)
            for raw_constraint in linear_constraints
        ]
        return tuple(sorted(out, key=_constraint_sort_key))

    river_lines = iter_river_lines_from_trace(river_trace)
    if not river_lines:
        return ()
    return (
        ZoneLinearConstraint(
            name="river::trace",
            kind="river_trace",
            lines=tuple(river_lines),
            participates_in_refinement=True,
        ),
    )


def _find_matching_constraint(
    *,
    segment: LineString | None,
    ordered_constraints: tuple[ZoneLinearConstraint, ...],
    constraint_linework_by_name: Mapping[str, Any],
    tolerance: float,
) -> ZoneLinearConstraint | None:
    if segment is None:
        return None
    for constraint in ordered_constraints:
        linework = constraint_linework_by_name.get(str(constraint.name))
        if linework is None:
            continue
        if segment_matches_linework(
            segment=segment,
            linework=linework,
            tolerance=tolerance,
        ):
            return constraint
    return None


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
    linear_constraints: tuple[
        ZoneLinearConstraint | Mapping[str, Any] | object, ...
    ]
    | None = None,
    river_trace: object | None = None,
    refinement_scope_geometry=None,
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
    normalized_constraints = _normalize_linear_constraints(
        linear_constraints=linear_constraints,
        river_trace=river_trace,
    )
    constraint_lines = [
        line
        for constraint in normalized_constraints
        for line in constraint.lines
    ]
    point_tolerance = as_metric_tolerance(heal_tolerance)
    partition = split_partition_with_constraint_lines(
        partition,
        constraint_lines=constraint_lines,
        tolerance=point_tolerance,
        ZonePartitionFace_cls=ZonePartitionFace,
        ZoneConformalPartition_cls=ZoneConformalPartition,
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
    surface_polygon_by_tag: dict[int, Polygon] = {}
    physical_groups: list[ZoneConformalPhysicalGroup] = []
    curve_tags_by_name: dict[str, list[int]] = {}
    constraint_linework_by_name: dict[str, Any] = {}
    constraint_by_name = {
        str(constraint.name): constraint for constraint in normalized_constraints
    }
    constraint_curve_tags_raw: dict[str, list[int]] = {
        str(constraint.name): [] for constraint in normalized_constraints
    }
    constraint_embed_success_by_name: dict[str, int] = {
        str(constraint.name): 0 for constraint in normalized_constraints
    }
    constraint_embed_failures_by_name: dict[str, int] = {
        str(constraint.name): 0 for constraint in normalized_constraints
    }

    gmsh.initialize()
    try:
        configure_gmsh_terminal_output(gmsh)
        gmsh.model.add(str(model_name).strip() or "zone_conformal_mesh")
        occ = gmsh.model.occ

        for face in partition.faces:
            outer_loop, outer_curve_tags = add_ring_loop(
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
                hole_loop, hole_curve_tags_one = add_ring_loop(
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
            surface_polygon_by_tag[int(surface_tag)] = face.polygon

            for curve_tag in outer_curve_tags + hole_curve_tags:
                curve_usage.setdefault(int(curve_tag), set()).add(face.zone_key)

        existing_curve_tags = set(int(tag) for tag in curve_usage)
        if normalized_constraints:
            partition_linework = unary_union(
                [face.polygon.boundary for face in partition.faces]
            )
            for constraint in normalized_constraints:
                constraint_name = str(constraint.name)
                constraint_linework = unary_union(list(constraint.lines))
                constraint_linework_by_name[constraint_name] = constraint_linework
                noded_linework = unary_union([partition_linework, *constraint.lines])
                noded_constraint_lines = [
                    line
                    for line in iter_line_parts(noded_linework)
                    if segment_matches_linework(
                        segment=line,
                        linework=constraint_linework,
                        tolerance=point_tolerance,
                    )
                ]
                for constraint_line in noded_constraint_lines:
                    if segment_matches_linework(
                        segment=constraint_line,
                        linework=partition_linework,
                        tolerance=point_tolerance,
                    ):
                        continue
                    for curve_tag in add_polyline_segments(
                        occ,
                        np.asarray(constraint_line.coords, dtype=float),
                        point_registry=point_registry,
                        line_registry=line_registry,
                        point_size=global_size_value,
                        tolerance=point_tolerance,
                    ):
                        if int(curve_tag) in existing_curve_tags:
                            continue
                        constraint_curve_tags_raw[constraint_name].append(int(curve_tag))
                        curve_usage.setdefault(int(curve_tag), set())

        occ.synchronize()
        apply_mesh_options(
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

        curve_groups: dict[str, dict[str, Any]] = {}
        curve_tag_to_segment: dict[int, LineString] = {}
        for canonical, line_tag in line_registry.items():
            curve_tag_to_segment[int(line_tag)] = LineString(
                [
                    (float(canonical[0][0]), float(canonical[0][1])),
                    (float(canonical[1][0]), float(canonical[1][1])),
                ]
            )
        domain_boundary = partition.domain_geometry.boundary

        for curve_tag, zone_keys in sorted(curve_usage.items()):
            segment = curve_tag_to_segment.get(int(curve_tag))
            matched_constraint = _find_matching_constraint(
                segment=segment,
                ordered_constraints=normalized_constraints,
                constraint_linework_by_name=constraint_linework_by_name,
                tolerance=point_tolerance,
            )
            if matched_constraint is not None:
                name = str(matched_constraint.name)
                group_kind = _group_kind_for_constraint_kind(matched_constraint.kind)
                zone_names: tuple[str, ...] = ()
            else:
                is_boundary = segment_matches_linework(
                    segment=segment,
                    linework=domain_boundary,
                    tolerance=point_tolerance,
                )
                name, group_kind, zone_names = build_curve_group_name(
                    set(str(zone_key) for zone_key in zone_keys),
                    is_boundary=is_boundary,
                )
            payload = curve_groups.setdefault(
                str(name),
                {
                    "group_kind": str(group_kind),
                    "zone_keys": tuple(str(zone_key) for zone_key in zone_names),
                    "curve_tags": [],
                },
            )
            payload["curve_tags"].append(int(curve_tag))

        for name, payload in sorted(curve_groups.items()):
            curve_tags = sorted(set(int(tag) for tag in payload["curve_tags"]))
            curve_tags_by_name[str(name)] = curve_tags
            physical_tag = gmsh.model.addPhysicalGroup(1, curve_tags)
            gmsh.model.setPhysicalName(1, int(physical_tag), name)
            physical_groups.append(
                ZoneConformalPhysicalGroup(
                    dimension=1,
                    tag=int(physical_tag),
                    name=str(name),
                    group_kind=str(payload["group_kind"]),
                    entity_tags=tuple(int(tag) for tag in sorted(curve_tags)),
                    zone_keys=tuple(str(zone_key) for zone_key in payload["zone_keys"]),
                )
            )

        for constraint in normalized_constraints:
            constraint_name = str(constraint.name)
            for curve_tag in curve_tags_by_name.get(constraint_name, []):
                if int(curve_tag) in existing_curve_tags:
                    constraint_embed_success_by_name[constraint_name] += 1
                    continue
                segment = curve_tag_to_segment.get(int(curve_tag))
                if segment is None:
                    constraint_embed_failures_by_name[constraint_name] += 1
                    continue
                embedded = False
                for surface_tag, surface_polygon in surface_polygon_by_tag.items():
                    if not segment_matches_linework(
                        segment=segment,
                        linework=surface_polygon,
                        tolerance=point_tolerance,
                    ):
                        continue
                    try:
                        gmsh.model.mesh.embed(1, [int(curve_tag)], 2, int(surface_tag))
                        embedded = True
                    except Exception:
                        continue
                if embedded:
                    constraint_embed_success_by_name[constraint_name] += 1
                else:
                    constraint_embed_failures_by_name[constraint_name] += 1

        interface_curve_tags_all = [
            int(curve_tag)
            for name, curve_tags_list in curve_tags_by_name.items()
            if not str(name).startswith("boundary::")
            and (
                str(name) not in constraint_by_name
                or bool(constraint_by_name[str(name)].participates_in_refinement)
            )
            for curve_tag in curve_tags_list
        ]
        interface_curve_tags = [
            int(curve_tag)
            for curve_tag in interface_curve_tags_all
            if segment_intersects_refinement_scope(
                segment=curve_tag_to_segment.get(int(curve_tag)),
                scope_geometry=refinement_scope_geometry,
                tolerance=point_tolerance,
            )
        ]
        mesh_size_fields_summary = apply_interface_refinement_field(
            gmsh,
            interface_curve_tags=interface_curve_tags,
            global_size=global_size_value,
            refine_interfaces=refine_interfaces_value,
            interface_size=interface_size_value,
            interface_distance=interface_distance_value,
            interface_sampling=int(interface_sampling),
        )
        mesh_size_fields_summary["candidate_interface_curve_count"] = int(
            len(sorted(set(int(tag) for tag in interface_curve_tags_all)))
        )
        mesh_size_fields_summary["scope_filtered_interface_curve_count"] = int(
            len(sorted(set(int(tag) for tag in interface_curve_tags)))
        )
        mesh_size_fields_summary["refinement_scope_applied"] = bool(
            refinement_scope_geometry is not None
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
    cleaning_diagnostics_raw = (
        {}
        if partition.cleaning_diagnostics is None
        else {str(key): value for key, value in partition.cleaning_diagnostics.items()}
    )
    tolerances = (
        dict(cleaning_diagnostics_raw.get("tolerances", {}))
        if cleaning_diagnostics_raw
        else {}
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
        "mode": str(cleaning_diagnostics_raw.get("cleaning_mode", "unknown")),
        "source_feature_count": int(
            cleaning_diagnostics_raw.get("source_feature_count", 0)
        ),
        "features_after_domain_clip_count": int(
            cleaning_diagnostics_raw.get("features_after_domain_clip_count", 0)
        ),
        "invalid_geometries_repaired_count": int(
            cleaning_diagnostics_raw.get("invalid_geometries_repaired_count", 0)
        ),
        "polygons_removed_by_area_threshold_count": int(
            cleaning_diagnostics_raw.get("polygons_removed_by_area_threshold_count", 0)
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
    linear_constraints_summary: dict[str, dict[str, Any]] = {}
    for constraint in normalized_constraints:
        constraint_name = str(constraint.name)
        curve_tags = [
            int(tag) for tag in curve_tags_by_name.get(constraint_name, ())
        ]
        curve_tag_set = set(curve_tags)
        linear_constraints_summary[constraint_name] = {
            "provided": True,
            "kind": str(constraint.kind),
            "line_count": int(constraint.line_count),
            "curve_count": int(len(curve_tags)),
            "embedded_surface_curve_pairs": int(
                constraint_embed_success_by_name.get(constraint_name, 0)
            ),
            "embed_failures": int(
                constraint_embed_failures_by_name.get(constraint_name, 0)
            ),
            "refined_with_interface_field": bool(
                bool(refine_interfaces_value)
                and bool(
                    curve_tag_set.intersection(
                        set(int(tag) for tag in interface_curve_tags)
                    )
                )
            ),
            "participates_in_refinement": bool(
                constraint.participates_in_refinement
            ),
        }
    river_trace_summary = dict(
        linear_constraints_summary.get(
            "river::trace",
            {
                "provided": bool(river_trace is not None),
                "line_count": 0,
                "curve_count": 0,
                "embedded_surface_curve_pairs": 0,
                "embed_failures": 0,
                "refined_with_interface_field": False,
            },
        )
    )
    river_trace_summary = {
        "provided": bool(river_trace_summary.get("provided", False)),
        "line_count": int(river_trace_summary.get("line_count", 0)),
        "curve_count": int(river_trace_summary.get("curve_count", 0)),
        "embedded_surface_curve_pairs": int(
            river_trace_summary.get("embedded_surface_curve_pairs", 0)
        ),
        "embed_failures": int(river_trace_summary.get("embed_failures", 0)),
        "refined_with_interface_field": bool(
            river_trace_summary.get("refined_with_interface_field", False)
        ),
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
        "cleaning_diagnostics": cleaning_diagnostics_raw,
        "cleaning_summary": cleaning_summary,
        "linear_constraints": linear_constraints_summary,
        "river_trace": river_trace_summary,
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
    linear_constraints: tuple[
        ZoneLinearConstraint | Mapping[str, Any] | object, ...
    ]
    | None = None,
    river_trace: object | None = None,
    refinement_scope_geometry=None,
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
        linear_constraints=linear_constraints,
        river_trace=river_trace,
        refinement_scope_geometry=refinement_scope_geometry,
        model_name=model_name,
    )
