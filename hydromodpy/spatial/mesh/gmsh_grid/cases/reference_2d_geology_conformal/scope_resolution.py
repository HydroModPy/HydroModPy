"""Minimal support-domain helpers for the conformal reference case."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalDomainConfig,
    ZoneConformalGeometryPayload,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.domain import (
    load_zone_meshing_domain_payload,
)


def _valid_geometry_mask(geometries) -> object:
    """Return one stable non-empty/non-missing mask across GeoPandas versions."""
    return (~geometries.is_empty) & (~geometries.isna())


def _load_domain_payload(
    *,
    domain_cfg: ZoneConformalDomainConfig,
    config_path: Path,
    domain_geographic: object | None,
    target_crs: object,
) -> ZoneConformalGeometryPayload:
    return load_zone_meshing_domain_payload(
        domain_cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=target_crs,
    )


__all__ = [
    "_load_domain_payload",
    "_valid_geometry_mask",
]
