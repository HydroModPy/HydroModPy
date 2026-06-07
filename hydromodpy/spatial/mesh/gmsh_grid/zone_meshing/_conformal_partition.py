"""Partition stage of zone-conformal meshing."""

from __future__ import annotations

from collections.abc import Sequence

from hydromodpy.spatial.mesh.gmsh_grid.trace import trace_mesh_stage
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    as_metric_tolerance,
    split_partition_with_constraint_lines,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._input_normalization import (
    normalize_linear_constraints,
    normalize_regional_size_fields,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._partition_builder import (
    build_partition_from_dataframe_impl,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.contracts import (
    ZoneConformalPartition,
    ZoneLinearConstraint,
    ZonePartitionFace,
    ZoneRegionalSizeField,
)
from hydromodpy.spatial.protocols import get_geology_data_source


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
    geology_source = get_geology_data_source()
    return build_partition_from_dataframe_impl(
        gdf,
        zone_key_column=zone_key_column,
        priority_column=priority_column,
        domain_geometry=domain_geometry,
        simplify_tolerance=simplify_tolerance,
        heal_tolerance=heal_tolerance,
        min_polygon_area=min_polygon_area,
        normalize_zone_key_fn=geology_source.normalize_zone_key,
        partition_face_cls=ZonePartitionFace,
        partition_cls=ZoneConformalPartition,
    )


def build_and_split_partition(
    gdf,
    *,
    zone_key_column: str,
    priority_column: str | None,
    domain_geometry,
    simplify_tolerance: float,
    heal_tolerance: float,
    min_polygon_area: float,
    linear_constraints: Sequence[ZoneLinearConstraint] | None,
    river_trace: object | None,
    regional_size_fields: Sequence[ZoneRegionalSizeField] | None,
) -> tuple[
    ZoneConformalPartition,
    list[ZoneLinearConstraint],
    list[ZoneRegionalSizeField],
    float,
]:
    """Build, normalize, and split a partition with constraint lines.

    Returns the final partition, prepared constraints, prepared regional size
    fields, and the metric tolerance derived from ``heal_tolerance``.
    """
    trace_mesh_stage("zone_meshing.partition.build.start")
    partition = build_zone_conformal_partition_from_dataframe(
        gdf,
        zone_key_column=zone_key_column,
        priority_column=priority_column,
        domain_geometry=domain_geometry,
        simplify_tolerance=simplify_tolerance,
        heal_tolerance=heal_tolerance,
        min_polygon_area=min_polygon_area,
    )
    trace_mesh_stage(
        "zone_meshing.partition.build.done",
        n_faces=partition.n_faces,
        n_zone_keys=len(partition.zone_keys),
    )
    normalized_constraints = normalize_linear_constraints(
        linear_constraints=linear_constraints,
        river_trace=river_trace,
    )
    trace_mesh_stage(
        "zone_meshing.constraints.normalized",
        n_constraints=len(normalized_constraints),
    )
    point_tolerance = as_metric_tolerance(float(heal_tolerance))
    constraint_lines = [line for constraint in normalized_constraints for line in constraint.lines]
    trace_mesh_stage(
        "zone_meshing.partition.split.start",
        n_constraint_lines=len(constraint_lines),
        point_tolerance=point_tolerance,
    )
    partition = split_partition_with_constraint_lines(
        partition,
        constraint_lines=constraint_lines,
        tolerance=point_tolerance,
        ZonePartitionFace_cls=ZonePartitionFace,
        ZoneConformalPartition_cls=ZoneConformalPartition,
    )
    trace_mesh_stage("zone_meshing.partition.split.done", n_faces=partition.n_faces)
    prepared_regional_size_fields = normalize_regional_size_fields(
        regional_size_fields=regional_size_fields,
        domain_geometry=partition.domain_geometry,
    )
    return (
        partition,
        list(normalized_constraints),
        list(prepared_regional_size_fields),
        point_tolerance,
    )
