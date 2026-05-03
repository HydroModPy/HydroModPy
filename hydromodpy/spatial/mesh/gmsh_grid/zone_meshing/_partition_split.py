"""Helpers that re-partition cleaned polygon faces with line constraints."""

from __future__ import annotations

from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._geometry_contracts import (
    ZoneGeometry,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.geometry_utils import (
    iter_line_parts,
    iter_polygon_parts,
    make_valid_geometry,
    make_valid_linework,
)


def split_partition_with_constraint_lines(
    partition,
    *,
    constraint_lines: list[LineString],
    tolerance: float,
    ZonePartitionFace_cls,
    ZoneConformalPartition_cls,
):
    """Re-partition faces when constraint lines must appear in the mesh."""
    if not constraint_lines:
        return partition

    valid_lines: list[LineString] = []
    for line in constraint_lines:
        if line is None or line.is_empty:
            continue
        repaired = make_valid_linework(line)
        valid_lines.extend(
            piece for piece in iter_line_parts(repaired) if float(piece.length) > 0.0
        )
    if not valid_lines:
        return partition

    zone_geometries: dict[str, ZoneGeometry] = {}
    for face in partition.faces:
        zone_key = str(face.zone_key)
        current = zone_geometries.get(zone_key)
        zone_geometries[zone_key] = (
            face.polygon if current is None else make_valid_geometry(current.union(face.polygon))
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
                zone_key for zone_key, geometry in zone_geometries.items() if geometry.covers(point)
            ]
            if not owners:
                continue
            if len(owners) == 1:
                owner = owners[0]
            else:
                owner = max(
                    owners,
                    key=lambda zone_key: float(part.intersection(zone_geometries[zone_key]).area),
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


__all__ = ["split_partition_with_constraint_lines"]
