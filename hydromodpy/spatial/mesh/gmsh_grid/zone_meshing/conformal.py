"""Generate 2D planar meshes that follow polygonal zone boundaries exactly.

This module exposes the high-level entry points.
The heavy lifting is delegated to:

* ``_geometry_cleaning`` - Shapely geometry validation, cleaning, partitioning
* ``_gmsh_driver`` - Gmsh Python API helpers (rings, polylines, refinement)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from hydromodpy.spatial._protocols import get_geology_data_source
from hydromodpy.spatial.mesh.gmsh_grid._deps import require_gmsh as _require_gmsh
from hydromodpy.spatial.mesh.gmsh_grid.trace import trace_mesh_stage
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._build_context import (
    compute_effective_max_size,
    initialize_build_state,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._curve_groups import (
    build_curve_tag_to_segment,
    draft_curve_groups,
    embed_constraint_curves,
    register_curve_physical_groups,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    as_metric_tolerance,
    iter_line_parts,
    segment_intersects_refinement_scope,
    segment_matches_linework,
    split_partition_with_constraint_lines,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._gmsh_driver import (
    add_polyline_segments,
    add_ring_loop,
    apply_family_refinement_fields,
    apply_interface_refinement_field,
    apply_mesh_options,
    build_curve_group_name,
    build_runtime_planar_mesh_from_gmsh,
    configure_gmsh_terminal_output,
    create_regional_structured_size_field,
    set_background_mesh_from_fields,
    write_repository_compatible_mesh,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._input_normalization import (
    normalize_interface_refinement_inputs,
    normalize_linear_constraints,
    normalize_regional_size_fields,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._linework_matching import (
    SurfaceEmbeddingLocator,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._partition_builder import (
    _select_partition_face_owner as _select_partition_face_owner_impl,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._partition_builder import (
    build_partition_from_dataframe_impl,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_policy import (
    apply_local_refinement_policy,
    build_refinement_candidates,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._summary_sidecar import (
    build_zone_conformal_summary,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementPolicy,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.contracts import (
    ZoneConformalMeshResult,
    ZoneConformalPartition,
    ZoneConformalPhysicalGroup,
    ZoneLinearConstraint,
    ZonePartitionFace,
    ZoneRegionalSizeField,
)

# ---------------------------------------------------------------------------
# Partition builder
# ---------------------------------------------------------------------------


def _select_partition_face_owner(
    *,
    part: BaseGeometry,
    point: BaseGeometry,
    resolved_geometries: Mapping[str, BaseGeometry],
    grouped_priorities: Mapping[str, float],
    overlap_tolerance: float,
    probe_radius: float,
) -> str | None:
    """Compatibility wrapper around the internal partition-owner selector.

    The implementation now lives in ``_partition_builder.py``, but this thin
    wrapper keeps the historical import path stable for tests and local debug
    scripts that still import the helper from ``conformal.py``.
    """
    return _select_partition_face_owner_impl(
        part=part,
        point=point,
        resolved_geometries=resolved_geometries,
        grouped_priorities=grouped_priorities,
        overlap_tolerance=overlap_tolerance,
        probe_radius=probe_radius,
    )


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


# ---------------------------------------------------------------------------
# Mesh generation
# ---------------------------------------------------------------------------
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
    refinement_policy: ZoneMeshingRefinementPolicy | None = None,
    linear_constraints: Sequence[ZoneLinearConstraint] | None = None,
    regional_size_fields: Sequence[ZoneRegionalSizeField] | None = None,
    river_trace: object | None = None,
    refinement_scope_geometry=None,
    model_name: str = "zone_conformal_mesh",
) -> ZoneConformalMeshResult:
    """Generate one conformal planar mesh from polygon zones.

    This is the main orchestration entry point of the module. The function
    deliberately proceeds in coarse stages:

    1. validate sizing inputs;
    2. build and optionally split the polygon partition;
    3. create OCC entities and physical groups in Gmsh;
    4. prepare interface and regional size fields;
    5. generate and export the mesh together with a stable summary payload.
    """
    trace_mesh_stage(
        "zone_meshing.generate.start",
        output_path=output_path,
        n_source_features=len(gdf),
        global_size=global_size,
        refine_interfaces=refine_interfaces,
    )
    global_size_value = float(global_size)
    if not np.isfinite(global_size_value) or global_size_value <= 0.0:
        raise ValueError("global_size must be finite and > 0")
    (
        refine_interfaces_value,
        interface_size_value,
        interface_distance_value,
    ) = normalize_interface_refinement_inputs(
        global_size=global_size_value,
        refine_interfaces=refine_interfaces,
        interface_size=interface_size,
        interface_distance=interface_distance,
        interface_sampling=interface_sampling,
    )

    # Build the cleaned polygon partition first, then split it further if
    # internal line constraints must become explicit mesh curves.
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
    prepared_constraints = normalized_constraints
    constraint_lines = [line for constraint in prepared_constraints for line in constraint.lines]
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

    trace_mesh_stage("zone_meshing.gmsh.require")
    gmsh = _require_gmsh()
    output_path_obj = Path(output_path).resolve()
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    effective_max_size = compute_effective_max_size(
        global_size_value=global_size_value,
        max_size=max_size,
        prepared_regional_size_fields=prepared_regional_size_fields,
    )
    build_state = initialize_build_state(
        zone_keys=partition.zone_keys,
        constraint_names=[str(constraint.name) for constraint in prepared_constraints],
    )
    constraint_by_name = {str(constraint.name): constraint for constraint in prepared_constraints}
    trace_mesh_stage("zone_meshing.gmsh.initialize")
    gmsh.initialize()
    try:
        configure_gmsh_terminal_output(gmsh)
        gmsh.model.add(str(model_name).strip() or "zone_conformal_mesh")
        occ = gmsh.model.occ

        # Create one OCC surface per partition face and record which curves are
        # shared by which zones. That later drives physical-group naming.
        trace_mesh_stage("zone_meshing.occ.surfaces.start", n_faces=partition.n_faces)
        for face in partition.faces:
            outer_loop, outer_curve_tags = add_ring_loop(
                occ,
                np.asarray(face.polygon.exterior.coords, dtype=float),
                point_registry=build_state.point_registry,
                line_registry=build_state.line_registry,
                point_size=global_size_value,
                tolerance=point_tolerance,
            )
            hole_loops: list[int] = []
            hole_curve_tags: list[int] = []
            for interior in face.polygon.interiors:
                hole_loop, hole_curve_tags_one = add_ring_loop(
                    occ,
                    np.asarray(interior.coords, dtype=float),
                    point_registry=build_state.point_registry,
                    line_registry=build_state.line_registry,
                    point_size=global_size_value,
                    tolerance=point_tolerance,
                )
                hole_loops.append(int(hole_loop))
                hole_curve_tags.extend(hole_curve_tags_one)

            surface_tag = occ.addPlaneSurface([outer_loop, *hole_loops])
            build_state.surface_tags_by_zone[face.zone_key].append(int(surface_tag))
            build_state.surface_polygon_by_tag[int(surface_tag)] = face.polygon

            for curve_tag in outer_curve_tags + hole_curve_tags:
                build_state.curve_usage.setdefault(int(curve_tag), set()).add(face.zone_key)
        trace_mesh_stage(
            "zone_meshing.occ.surfaces.done",
            n_points=len(build_state.point_registry),
            n_curves=len(build_state.line_registry),
            n_surfaces=len(build_state.surface_polygon_by_tag),
        )

        existing_curve_tags = set(int(tag) for tag in build_state.curve_usage)
        if prepared_constraints:
            # Re-node the constraint lines against the partition boundary so
            # Gmsh receives a consistent set of segments to embed/refine.
            trace_mesh_stage("zone_meshing.constraints.embed_prep.start")
            partition_linework = unary_union([face.polygon.boundary for face in partition.faces])
            for constraint in prepared_constraints:
                constraint_name = str(constraint.name)
                constraint_linework = unary_union(list(constraint.lines))
                build_state.constraint_linework_by_name[constraint_name] = constraint_linework
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
                        point_registry=build_state.point_registry,
                        line_registry=build_state.line_registry,
                        point_size=global_size_value,
                        tolerance=point_tolerance,
                    ):
                        if int(curve_tag) in existing_curve_tags:
                            continue
                        build_state.constraint_curve_tags_raw[constraint_name].append(
                            int(curve_tag)
                        )
                        build_state.curve_usage.setdefault(int(curve_tag), set())
            trace_mesh_stage("zone_meshing.constraints.embed_prep.done")

        trace_mesh_stage("zone_meshing.occ.synchronize.start")
        occ.synchronize()
        trace_mesh_stage("zone_meshing.occ.synchronize.done")
        trace_mesh_stage("zone_meshing.mesh_options.apply.start")
        apply_mesh_options(
            gmsh,
            algorithm=algorithm,
            global_size=global_size_value,
            min_size=min_size,
            max_size=effective_max_size,
        )
        trace_mesh_stage("zone_meshing.mesh_options.apply.done")

        # Surface groups identify geology zones; curve groups identify
        # interfaces, boundaries and named internal constraints.
        trace_mesh_stage("zone_meshing.physical_groups.surfaces.start")
        for zone_key, surface_tags in sorted(build_state.surface_tags_by_zone.items()):
            if not surface_tags:
                continue
            physical_tag = gmsh.model.addPhysicalGroup(2, surface_tags)
            gmsh.model.setPhysicalName(2, int(physical_tag), f"zone::{zone_key}")
            build_state.physical_groups.append(
                ZoneConformalPhysicalGroup(
                    dimension=2,
                    tag=int(physical_tag),
                    name=f"zone::{zone_key}",
                    group_kind="zone_surface",
                    entity_tags=tuple(int(tag) for tag in sorted(surface_tags)),
                    zone_keys=(str(zone_key),),
                )
            )
        trace_mesh_stage("zone_meshing.physical_groups.surfaces.done")

        curve_tag_to_segment = build_curve_tag_to_segment(line_registry=build_state.line_registry)
        domain_boundary = partition.domain_geometry.boundary

        curve_groups = draft_curve_groups(
            curve_usage=build_state.curve_usage,
            curve_tag_to_segment=curve_tag_to_segment,
            prepared_constraints=prepared_constraints,
            constraint_linework_by_name=build_state.constraint_linework_by_name,
            domain_boundary=domain_boundary,
            tolerance=point_tolerance,
            segment_matches_linework_fn=segment_matches_linework,
            build_curve_group_name_fn=build_curve_group_name,
        )

        trace_mesh_stage("zone_meshing.physical_groups.curves.start")
        (
            build_state.curve_tags_by_name,
            curve_physical_groups,
        ) = register_curve_physical_groups(
            gmsh=gmsh,
            curve_groups=curve_groups,
            physical_group_factory=ZoneConformalPhysicalGroup,
        )
        build_state.physical_groups.extend(curve_physical_groups)
        trace_mesh_stage("zone_meshing.physical_groups.curves.done")

        trace_mesh_stage("zone_meshing.constraints.embed.start")
        surface_locator = SurfaceEmbeddingLocator(
            surface_polygon_by_tag=build_state.surface_polygon_by_tag,
            tolerance=point_tolerance,
        )
        embed_constraint_curves(
            gmsh=gmsh,
            prepared_constraints=prepared_constraints,
            curve_tags_by_name=build_state.curve_tags_by_name,
            existing_curve_tags=existing_curve_tags,
            curve_tag_to_segment=curve_tag_to_segment,
            surface_polygon_by_tag=build_state.surface_polygon_by_tag,
            tolerance=point_tolerance,
            segment_matches_linework_fn=segment_matches_linework,
            success_by_name=build_state.constraint_embed_success_by_name,
            failures_by_name=build_state.constraint_embed_failures_by_name,
            surface_locator=surface_locator,
        )
        trace_mesh_stage("zone_meshing.constraints.embed.done")

        trace_mesh_stage("zone_meshing.refinement.start")
        refined_curve_tags: set[int]
        use_regional_background = bool(prepared_regional_size_fields)
        if (
            refine_interfaces_value
            and refinement_policy is not None
            and refinement_policy.enabled
            and interface_size_value is not None
            and interface_distance_value is not None
        ):
            policy_candidates = build_refinement_candidates(
                curve_tags_by_name=build_state.curve_tags_by_name,
                curve_tag_to_segment=curve_tag_to_segment,
                refinement_scope_geometry=refinement_scope_geometry,
                point_tolerance=point_tolerance,
                policy=refinement_policy,
                default_interface_size=float(interface_size_value),
                default_interface_distance=float(interface_distance_value),
                default_interface_sampling=int(interface_sampling),
            )
            policy_result = apply_local_refinement_policy(
                candidates=policy_candidates,
                policy=refinement_policy,
            )
            mesh_size_fields_summary = apply_family_refinement_fields(
                gmsh,
                family_curve_tags=policy_result.active_curve_tags_by_family,
                global_size=global_size_value,
                refine_interfaces=refine_interfaces_value,
                family_settings=refinement_policy.families,
                default_interface_size=float(interface_size_value),
                default_interface_distance=float(interface_distance_value),
                default_interface_sampling=int(interface_sampling),
                stop_at_distance_max=use_regional_background,
            )
            mesh_size_fields_summary["candidate_interface_curve_count"] = int(
                policy_result.candidate_count
            )
            mesh_size_fields_summary["scope_filtered_interface_curve_count"] = int(
                policy_result.active_curve_count
            )
            refined_curve_tags = {
                int(curve_tag)
                for curve_tags in policy_result.active_curve_tags_by_family.values()
                for curve_tag in curve_tags
            }
            build_state.refinement_policy_summary = policy_result.to_mapping()
        else:
            interface_curve_tags_all = [
                int(curve_tag)
                for name, curve_tags_list in build_state.curve_tags_by_name.items()
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
                stop_at_distance_max=use_regional_background,
            )
            mesh_size_fields_summary["candidate_interface_curve_count"] = int(
                len(sorted(set(int(tag) for tag in interface_curve_tags_all)))
            )
            mesh_size_fields_summary["scope_filtered_interface_curve_count"] = int(
                len(sorted(set(int(tag) for tag in interface_curve_tags)))
            )
            refined_curve_tags = set(int(tag) for tag in interface_curve_tags)
        mesh_size_fields_summary["refinement_scope_applied"] = bool(
            refinement_scope_geometry is not None
        )
        interface_background_field_tag = None
        background_payload = mesh_size_fields_summary.get("background_field")
        if isinstance(background_payload, dict):
            background_field_tag = background_payload.get("background_field_tag")
            if background_field_tag is not None:
                interface_background_field_tag = int(background_field_tag)

        combined_background_field_tags: list[int] = []
        if interface_background_field_tag is not None:
            combined_background_field_tags.append(int(interface_background_field_tag))
        if prepared_regional_size_fields:
            build_state.regional_background_summary = {
                "enabled": True,
                "fields": [],
            }
            for regional_field in prepared_regional_size_fields:
                field_tag, field_summary, temp_path = create_regional_structured_size_field(
                    gmsh,
                    region_geometry=regional_field.region_geometry,
                    domain_bounds=tuple(partition.domain_geometry.bounds),
                    inside_size=float(regional_field.inside_size),
                    outside_size=float(regional_field.outside_size),
                    transition_distance=float(regional_field.transition_distance or 0.0),
                    grid_resolution=float(regional_field.grid_resolution),
                    scratch_dir=output_path_obj.parent,
                    field_name=regional_field.name,
                )
                build_state.regional_field_temp_paths.append(temp_path)
                combined_background_field_tags.append(int(field_tag))
                build_state.regional_background_summary["fields"].append(field_summary)
            final_background_field_tag = set_background_mesh_from_fields(
                gmsh,
                field_tags=combined_background_field_tags,
            )
            build_state.regional_background_summary["final_background_field_tag"] = (
                None if final_background_field_tag is None else int(final_background_field_tag)
            )
        trace_mesh_stage(
            "zone_meshing.refinement.done",
            n_candidate_interface_curves=mesh_size_fields_summary[
                "candidate_interface_curve_count"
            ],
            n_scope_interface_curves=mesh_size_fields_summary[
                "scope_filtered_interface_curve_count"
            ],
        )

        trace_mesh_stage("zone_meshing.gmsh.generate.start")
        gmsh.model.mesh.generate(2)
        trace_mesh_stage("zone_meshing.gmsh.generate.done")
        trace_mesh_stage("zone_meshing.mesh.write.start", output_path=output_path_obj)
        write_repository_compatible_mesh(gmsh, output_path_obj)
        trace_mesh_stage("zone_meshing.mesh.write.done", output_path=output_path_obj)
        trace_mesh_stage(
            "zone_meshing.mesh.capture_runtime.start",
            output_path=output_path_obj,
        )
        mesh = build_runtime_planar_mesh_from_gmsh(
            gmsh,
            source_path=output_path_obj,
        )
        trace_mesh_stage(
            "zone_meshing.mesh.capture_runtime.done",
            n_cells=mesh.n_cells,
        )
    finally:
        trace_mesh_stage("zone_meshing.gmsh.finalize")
        gmsh.finalize()
        for temp_path in build_state.regional_field_temp_paths:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                continue
    summary = build_zone_conformal_summary(
        output_path_obj=output_path_obj,
        mesh=mesh,
        partition=partition,
        physical_groups=build_state.physical_groups,
        curve_tags_by_name=build_state.curve_tags_by_name,
        normalized_constraints=normalized_constraints,
        constraint_embed_success_by_name=build_state.constraint_embed_success_by_name,
        constraint_embed_failures_by_name=build_state.constraint_embed_failures_by_name,
        river_trace=river_trace,
        refine_interfaces_value=refine_interfaces_value,
        refined_curve_tags=refined_curve_tags,
        mesh_size_fields_summary=mesh_size_fields_summary,
        regional_background_summary=build_state.regional_background_summary,
        global_size_value=global_size_value,
        min_size=min_size,
        max_size=max_size,
        effective_max_size=effective_max_size,
        algorithm=algorithm,
        refinement_policy_summary=build_state.refinement_policy_summary,
    )
    trace_mesh_stage("zone_meshing.generate.done", n_cells=mesh.n_cells)
    return ZoneConformalMeshResult(
        mesh=mesh,
        partition=partition,
        output_path=output_path_obj,
        physical_groups=tuple(build_state.physical_groups),
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
    refinement_policy: ZoneMeshingRefinementPolicy | None = None,
    linear_constraints: Sequence[ZoneLinearConstraint] | None = None,
    regional_size_fields: Sequence[ZoneRegionalSizeField] | None = None,
    river_trace: object | None = None,
    refinement_scope_geometry=None,
    model_name: str = "zone_conformal_mesh",
) -> ZoneConformalMeshResult:
    """Load one vector geology source and generate a conformal planar mesh."""
    geology_payload = get_geology_data_source().load_vector_dataframe(
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
        refinement_policy=refinement_policy,
        linear_constraints=linear_constraints,
        regional_size_fields=regional_size_fields,
        river_trace=river_trace,
        refinement_scope_geometry=refinement_scope_geometry,
        model_name=model_name,
    )
