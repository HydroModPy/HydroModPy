"""Mesh configuration schemas.

``mesh`` holds the ``[mesh]`` section read by the mesh step. The other modules
are the contract of the mesh-catchment launcher: how a delineated catchment is
meshed, how optional batch loops are configured, and how launcher-level output
paths are resolved.

Sub-modules:
- ``mesh``: the ``[mesh]`` section (engine, sizes, line families).
- ``rivers``: river-trace constraints.
- ``watershed``: watershed-boundary constraints (smoothing, coarsening, geology).
- ``hydraulic``: hydraulic-property tables keyed by geology zones.
- ``batch``: batch loop over outlet coordinates.
- ``main``: top-level mono-catchment launcher contract.
"""

from __future__ import annotations

from hydromodpy.spatial.mesh.config.batch import (
    MeshCatchmentBatchOutputs,
    MeshCatchmentBatchSection,
    parse_mesh_catchment_batch_config_data,
)
from hydromodpy.spatial.mesh.config.hydraulic import (
    MeshCatchmentHydraulicConductivity,
    MeshCatchmentHydraulicPropertiesConfig,
    MeshCatchmentHydraulicPropertyMapping,
    MeshCatchmentStorageCoefficient,
)
from hydromodpy.spatial.mesh.config.main import (
    MeshCatchmentConfig,
    ZoneMeshingDomainSchema,
    parse_mesh_catchment_config_data,
)
from hydromodpy.spatial.mesh.config.mesh import (
    MeshConfig,
    MeshFamiliesConfig,
    MeshRegularConfig,
    MeshTriangleConfig,
    MeshVoronoiConfig,
)
from hydromodpy.spatial.mesh.config.rivers import MeshCatchmentRiversConfig
from hydromodpy.spatial.mesh.config.watershed import (
    MeshCatchmentWatershedBoundaryConfig,
    MeshCatchmentWatershedBoundarySmoothingConfig,
    MeshCatchmentWatershedGeologyConformityConfig,
    MeshCatchmentWatershedOutsideCoarseningConfig,
)

__all__ = [
    "MeshCatchmentBatchOutputs",
    "MeshCatchmentBatchSection",
    "MeshCatchmentConfig",
    "MeshCatchmentHydraulicConductivity",
    "MeshCatchmentHydraulicPropertiesConfig",
    "MeshCatchmentHydraulicPropertyMapping",
    "MeshCatchmentRiversConfig",
    "MeshCatchmentStorageCoefficient",
    "MeshCatchmentWatershedBoundaryConfig",
    "MeshCatchmentWatershedBoundarySmoothingConfig",
    "MeshCatchmentWatershedGeologyConformityConfig",
    "MeshCatchmentWatershedOutsideCoarseningConfig",
    "MeshConfig",
    "MeshFamiliesConfig",
    "MeshRegularConfig",
    "MeshTriangleConfig",
    "MeshVoronoiConfig",
    "ZoneMeshingDomainSchema",
    "parse_mesh_catchment_batch_config_data",
    "parse_mesh_catchment_config_data",
]
