"""Expose the public API for zone-conformal meshing on top of Gmsh.

Import from this package when the goal is to generate meshes that honor a
polygonal zonation. It gathers the configuration helpers, geometry contracts,
and conformal meshing entry points without exposing the whole internal layout.
"""

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.config import (
    validate_zone_meshing_config_data,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.conformal import (
    ZoneConformalPhysicalGroup,
    ZoneConformalMeshResult,
    ZoneConformalPartition,
    ZonePartitionFace,
    build_zone_conformal_partition_from_dataframe,
    generate_zone_conformal_mesh_from_dataframe,
    generate_zone_conformal_mesh_from_geology_config,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.domain import (
    load_zone_meshing_domain_geometry,
    validate_zone_meshing_domain_config_data,
)

__all__ = [
    "ZoneConformalPhysicalGroup",
    "ZoneConformalMeshResult",
    "ZoneConformalPartition",
    "ZonePartitionFace",
    "build_zone_conformal_partition_from_dataframe",
    "generate_zone_conformal_mesh_from_dataframe",
    "generate_zone_conformal_mesh_from_geology_config",
    "load_zone_meshing_domain_geometry",
    "validate_zone_meshing_config_data",
    "validate_zone_meshing_domain_config_data",
]
