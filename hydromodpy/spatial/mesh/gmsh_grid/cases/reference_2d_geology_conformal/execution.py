"""Execution helpers for the reference 2D zone-conformal case."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.mesh.gmsh_grid import (
    generate_zone_conformal_mesh_from_dataframe,
)
from hydromodpy.spatial.mesh.gmsh_grid._trace import trace_mesh_stage
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalMeshingInputs,
)


def _run_zone_conformal_meshing(
    *,
    meshing_inputs: ZoneConformalMeshingInputs,
    mesh_path: Path,
):
    trace_mesh_stage(
        "zone_conformal.execution.generate.start",
        mesh_path=mesh_path,
        n_zone_features=len(meshing_inputs.zone_gdf),
        n_constraints=len(meshing_inputs.linear_constraints),
    )
    result = generate_zone_conformal_mesh_from_dataframe(
        meshing_inputs.zone_gdf,
        output_path=mesh_path,
        zone_key_column="zone_key",
        priority_column=(
            "_mesh_priority" if "_mesh_priority" in meshing_inputs.zone_gdf.columns else None
        ),
        domain_geometry=meshing_inputs.effective_domain_payload.geometry,
        algorithm=meshing_inputs.zone_meshing_cfg.algorithm,
        global_size=meshing_inputs.zone_meshing_cfg.global_size,
        min_size=meshing_inputs.zone_meshing_cfg.min_size,
        max_size=meshing_inputs.zone_meshing_cfg.max_size,
        simplify_tolerance=meshing_inputs.zone_meshing_cfg.simplify_tolerance,
        heal_tolerance=meshing_inputs.zone_meshing_cfg.heal_tolerance,
        min_polygon_area=meshing_inputs.zone_meshing_cfg.min_polygon_area,
        refine_interfaces=meshing_inputs.zone_meshing_cfg.refine_interfaces,
        interface_size=meshing_inputs.zone_meshing_cfg.interface_size,
        interface_distance=meshing_inputs.zone_meshing_cfg.interface_distance,
        interface_sampling=meshing_inputs.zone_meshing_cfg.interface_sampling,
        refinement_policy=meshing_inputs.zone_meshing_cfg.refinement_policy,
        linear_constraints=meshing_inputs.linear_constraints,
        regional_size_fields=meshing_inputs.regional_size_fields,
        refinement_scope_geometry=None,
        model_name=(f"reference_2d_zone_conformal_{meshing_inputs.constraints_mode_label}"),
    )
    trace_mesh_stage(
        "zone_conformal.execution.generate.done",
        output_mesh=result.output_path,
        n_cells=result.mesh.n_cells,
    )
    return result


__all__ = ["_run_zone_conformal_meshing"]
