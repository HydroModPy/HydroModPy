"""Public facade for support-domain parsing and loading.

The concrete implementation is split across internal helpers:

* ``_domain_contracts.py`` for the public typed payloads
* ``_domain_schema.py`` for Pydantic validation
* ``_domain_geometry.py`` for geometry cleanup helpers
* ``_domain_loaders.py`` for the actual ``bbox`` / ``polygon`` / ``vector`` /
  ``geographic_*`` loading paths

This file intentionally keeps the stable import surface used by the rest of the
meshing stack.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._domain_contracts import (
    ZoneMeshingDomainConfig,
    ZoneMeshingDomainPayload,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._domain_loaders import (
    load_zone_meshing_domain_payload_impl,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._domain_schema import (
    ZoneMeshingDomainBBoxSchema,
    ZoneMeshingDomainGeographicBoxBufferSchema,
    ZoneMeshingDomainGeographicWatershedBoxSchema,
    ZoneMeshingDomainGeographicWatershedSchema,
    ZoneMeshingDomainPolygonSchema,
    ZoneMeshingDomainVectorSchema,
)


def parse_zone_meshing_domain_config(
    config_data: Mapping[str, Any],
) -> ZoneMeshingDomainConfig:
    """Return one typed support-domain contract from a raw mapping."""
    return ZoneMeshingDomainConfig.from_mapping(config_data)


def load_zone_meshing_domain_payload(
    config: ZoneMeshingDomainConfig,
    *,
    config_path: str | Path | None = None,
    domain_geographic: object | None = None,
    target_crs=None,
) -> ZoneMeshingDomainPayload:
    """Load one domain geometry and return one typed payload."""
    return load_zone_meshing_domain_payload_impl(
        config,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=target_crs,
    )


__all__ = [
    "parse_zone_meshing_domain_config",
    "ZoneMeshingDomainBBoxSchema",
    "ZoneMeshingDomainConfig",
    "ZoneMeshingDomainGeographicBoxBufferSchema",
    "ZoneMeshingDomainGeographicWatershedBoxSchema",
    "ZoneMeshingDomainGeographicWatershedSchema",
    "ZoneMeshingDomainPayload",
    "ZoneMeshingDomainPolygonSchema",
    "ZoneMeshingDomainVectorSchema",
    "load_zone_meshing_domain_payload",
]
