"""Shared contracts for the reference 2D zone-conformal case."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import geopandas as gpd

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing import ZoneLinearConstraint


@dataclass(frozen=True)
class ZoneConformalConstraintUsage:
    """Resolved constraint switches for one conformal meshing run."""

    constraints_mode: str
    uses_geology_constraints: bool
    uses_river_constraints: bool


@dataclass(frozen=True)
class ZoneConformalSourcePayload:
    """Normalized source metadata carried through meshing and reporting."""

    field_id: str
    source_kind: str
    source_path: str
    n_source_features_before_domain_clip: int


@dataclass(frozen=True)
class ZoneConformalGeometryPayload:
    """Resolved support or scope geometry passed between planning stages."""

    geometry: object
    gdf: gpd.GeoDataFrame
    summary: dict[str, Any]

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "ZoneConformalGeometryPayload":
        return cls(
            geometry=payload["geometry"],
            gdf=payload["gdf"],
            summary=dict(payload.get("summary", {})),
        )


@dataclass(frozen=True)
class ZoneConformalMeshingInputs:
    """Common meshing contract assembled before calling the Gmsh core."""

    usage: ZoneConformalConstraintUsage
    source_payload: ZoneConformalSourcePayload
    zone_gdf: gpd.GeoDataFrame
    domain_payload: ZoneConformalGeometryPayload
    interface_scope_payload: ZoneConformalGeometryPayload
    refinement_scope_payload: ZoneConformalGeometryPayload
    interface_scope_is_custom: bool
    refinement_scope_is_custom: bool
    zone_meshing_cfg: Mapping[str, Any]
    rivers_cfg: Mapping[str, Any] | None
    watershed_boundary_cfg: Mapping[str, Any] | None
    resolved_river_trace: object | None
    linear_constraints: tuple[ZoneLinearConstraint, ...]


__all__ = [
    "ZoneConformalConstraintUsage",
    "ZoneConformalGeometryPayload",
    "ZoneConformalMeshingInputs",
    "ZoneConformalSourcePayload",
]
