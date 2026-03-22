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
class ZoneConformalDomainConfig:
    """Validated support/scope config reused across domain-like sections."""

    kind: str
    bbox: tuple[float, float, float, float] | None = None
    coordinates: tuple[tuple[float, float], ...] | None = None
    path: str | None = None
    id_field: str | None = None
    selected_id: str | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "ZoneConformalDomainConfig":
        bbox_raw = payload.get("bbox")
        coordinates_raw = payload.get("coordinates")
        return cls(
            kind=str(payload["kind"]),
            bbox=(
                None
                if bbox_raw is None
                else tuple(float(value) for value in bbox_raw)
            ),
            coordinates=(
                None
                if coordinates_raw is None
                else tuple(
                    (float(pair[0]), float(pair[1])) for pair in coordinates_raw
                )
            ),
            path=None if payload.get("path") is None else str(payload["path"]),
            id_field=(
                None if payload.get("id_field") is None else str(payload["id_field"])
            ),
            selected_id=(
                None
                if payload.get("selected_id") is None
                else str(payload["selected_id"])
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.bbox is not None:
            payload["bbox"] = [float(value) for value in self.bbox]
        if self.coordinates is not None:
            payload["coordinates"] = [
                [float(x), float(y)] for x, y in self.coordinates
            ]
        if self.path is not None:
            payload["path"] = self.path
        if self.id_field is not None:
            payload["id_field"] = self.id_field
        if self.selected_id is not None:
            payload["selected_id"] = self.selected_id
        return payload


@dataclass(frozen=True)
class ZoneConformalZoneMeshingConfig:
    """Validated meshing options consumed by the low-level Gmsh driver."""

    algorithm: str
    global_size: float
    min_size: float | None
    max_size: float | None
    simplify_tolerance: float
    heal_tolerance: float
    min_polygon_area: float
    refine_interfaces: bool
    interface_size: float | None
    interface_distance: float | None
    interface_sampling: int


@dataclass(frozen=True)
class ZoneConformalRiversConfig:
    """Validated river-constraint options for one run."""

    source: str
    path: str | None
    clip_to_domain: bool
    min_segment_length: float
    snap_tolerance: float


@dataclass(frozen=True)
class ZoneConformalWatershedBoundarySmoothingConfig:
    """Validated smoothing options for the watershed-boundary constraint."""

    enabled: bool
    simplify_tolerance: float
    heal_tolerance: float
    min_polygon_area: float


@dataclass(frozen=True)
class ZoneConformalWatershedBoundaryConfig:
    """Validated watershed-boundary options for one run."""

    enabled: bool
    source: str
    clip_to_domain: bool
    min_segment_length: float
    participates_in_refinement: bool
    smoothing: ZoneConformalWatershedBoundarySmoothingConfig


@dataclass(frozen=True)
class ZoneConformalCaseConfig:
    """Normalized top-level case configuration consumed by planning."""

    constraints_mode: str
    geology: Mapping[str, Any] | None
    rivers: ZoneConformalRiversConfig | None
    watershed_boundary: ZoneConformalWatershedBoundaryConfig | None
    domain: ZoneConformalDomainConfig
    interface_scope: ZoneConformalDomainConfig | None
    refinement_scope: ZoneConformalDomainConfig | None
    zone_meshing: ZoneConformalZoneMeshingConfig
    output_mesh: object | None
    output_summary_json: object | None
    output_figure: object | None
    output_figure_regional: object | None


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
    zone_meshing_cfg: ZoneConformalZoneMeshingConfig
    rivers_cfg: ZoneConformalRiversConfig | None
    watershed_boundary_cfg: ZoneConformalWatershedBoundaryConfig | None
    resolved_river_trace: object | None
    linear_constraints: tuple[ZoneLinearConstraint, ...]


__all__ = [
    "ZoneConformalCaseConfig",
    "ZoneConformalConstraintUsage",
    "ZoneConformalDomainConfig",
    "ZoneConformalGeometryPayload",
    "ZoneConformalMeshingInputs",
    "ZoneConformalRiversConfig",
    "ZoneConformalSourcePayload",
    "ZoneConformalWatershedBoundaryConfig",
    "ZoneConformalWatershedBoundarySmoothingConfig",
    "ZoneConformalZoneMeshingConfig",
]
