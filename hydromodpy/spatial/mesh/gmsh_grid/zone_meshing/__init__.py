"""Expose the public API for zone-conformal meshing on top of Gmsh.

This package is intentionally organized in layers:

- ``config.py`` validates user-facing meshing parameters
- ``domain.py`` resolves support-domain geometries
- ``conformal.py`` orchestrates partitioning + Gmsh generation
- internal helpers stay in ``_geometry_cleaning.py``, ``_gmsh_driver.py`` and
  ``_refinement_policy.py``

Import from here when you need the stable public entry points without pulling
the whole internal layout into higher-level code.
"""

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingSettings,
    parse_zone_meshing_settings,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.conformal import (
    build_zone_conformal_partition_from_dataframe,
    generate_zone_conformal_mesh_from_dataframe,
    generate_zone_conformal_mesh_from_geology_config,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.contracts import (
    ZoneConformalMeshResult,
    ZoneConformalPartition,
    ZoneConformalPhysicalGroup,
    ZoneLinearConstraint,
    ZonePartitionFace,
    ZoneRegionalSizeField,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.domain import (
    ZoneMeshingDomainConfig,
    ZoneMeshingDomainPayload,
    load_zone_meshing_domain_payload,
    parse_zone_meshing_domain_config,
)

__all__ = [
    "ZoneConformalPhysicalGroup",
    "ZoneConformalMeshResult",
    "ZoneConformalPartition",
    "ZoneLinearConstraint",
    "ZoneRegionalSizeField",
    "ZoneMeshingDomainConfig",
    "ZoneMeshingDomainPayload",
    "ZoneMeshingSettings",
    "ZonePartitionFace",
    "build_zone_conformal_partition_from_dataframe",
    "generate_zone_conformal_mesh_from_dataframe",
    "generate_zone_conformal_mesh_from_geology_config",
    "load_zone_meshing_domain_payload",
    "parse_zone_meshing_domain_config",
    "parse_zone_meshing_settings",
]
