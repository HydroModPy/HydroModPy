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

from hydromodpy.spatial.mesh.gmsh_grid._deps import require_gmsh as _require_gmsh
from hydromodpy.spatial.mesh.gmsh_grid.trace import trace_mesh_stage
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._build_context import (
    compute_effective_max_size,
    initialize_build_state,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._conformal_gmsh_stages import (
    apply_options_and_synchronize,
    apply_refinement_stage,
    build_occ_surfaces_and_constraints,
    configure_gmsh_session,
    generate_and_capture_mesh,
    register_physical_groups,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._conformal_partition import (
    build_and_split_partition,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._input_normalization import (
    normalize_interface_refinement_inputs,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._partition_builder import (
    _select_partition_face_owner as _select_partition_face_owner_impl,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._summary_sidecar import (
    build_zone_conformal_summary,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementPolicy,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.contracts import (
    ZoneConformalMeshResult,
    ZoneLinearConstraint,
    ZoneRegionalSizeField,
)
from hydromodpy.spatial.protocols import get_geology_data_source

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

    (
        partition,
        normalized_constraints,
        prepared_regional_size_fields,
        point_tolerance,
    ) = build_and_split_partition(
        gdf,
        zone_key_column=zone_key_column,
        priority_column=priority_column,
        domain_geometry=domain_geometry,
        simplify_tolerance=simplify_tolerance,
        heal_tolerance=heal_tolerance,
        min_polygon_area=min_polygon_area,
        linear_constraints=linear_constraints,
        river_trace=river_trace,
        regional_size_fields=regional_size_fields,
    )
    prepared_constraints = normalized_constraints

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
    try:
        occ = configure_gmsh_session(
            gmsh=gmsh,
            model_name=model_name,
            algorithm=algorithm,
            global_size_value=global_size_value,
            min_size=min_size,
            effective_max_size=effective_max_size,
        )
        existing_curve_tags = build_occ_surfaces_and_constraints(
            gmsh=gmsh,
            occ=occ,
            partition=partition,
            prepared_constraints=prepared_constraints,
            build_state=build_state,
            point_tolerance=point_tolerance,
            global_size_value=global_size_value,
        )
        apply_options_and_synchronize(
            gmsh=gmsh,
            occ=occ,
            algorithm=algorithm,
            global_size_value=global_size_value,
            min_size=min_size,
            effective_max_size=effective_max_size,
        )
        curve_tag_to_segment = register_physical_groups(
            gmsh=gmsh,
            partition=partition,
            prepared_constraints=prepared_constraints,
            build_state=build_state,
            point_tolerance=point_tolerance,
            existing_curve_tags=existing_curve_tags,
        )
        mesh_size_fields_summary, refined_curve_tags = apply_refinement_stage(
            gmsh=gmsh,
            build_state=build_state,
            curve_tag_to_segment=curve_tag_to_segment,
            prepared_constraints=prepared_constraints,
            constraint_by_name=constraint_by_name,
            prepared_regional_size_fields=prepared_regional_size_fields,
            output_path_obj=output_path_obj,
            partition=partition,
            refinement_policy=refinement_policy,
            refinement_scope_geometry=refinement_scope_geometry,
            refine_interfaces_value=refine_interfaces_value,
            interface_size_value=interface_size_value,
            interface_distance_value=interface_distance_value,
            interface_sampling=interface_sampling,
            point_tolerance=point_tolerance,
            global_size_value=global_size_value,
        )
        mesh = generate_and_capture_mesh(gmsh=gmsh, output_path_obj=output_path_obj)
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
