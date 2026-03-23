"""Shared contracts for the reference 2D zone-conformal case."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import geopandas as gpd

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingSettings,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.conformal import (
    ZoneLinearConstraint,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.domain import (
    ZoneMeshingDomainConfig,
    ZoneMeshingDomainPayload,
)


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


ZoneConformalGeometryPayload = ZoneMeshingDomainPayload


@dataclass(frozen=True)
class ZoneConformalGeologySourceConfig:
    """Validated geology source definition used by the conformal case."""

    path: str
    kind: str
    code_field: str | None = None
    reference_raster_path: str | None = None
    all_touched: bool = False

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "ZoneConformalGeologySourceConfig":
        return cls(
            path=str(payload["path"]),
            kind=str(payload["kind"]),
            code_field=(
                None
                if payload.get("code_field") is None
                else str(payload["code_field"])
            ),
            reference_raster_path=(
                None
                if payload.get("reference_raster_path") is None
                else str(payload["reference_raster_path"])
            ),
            all_touched=bool(payload.get("all_touched", False)),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "kind": self.kind,
            "all_touched": self.all_touched,
        }
        if self.code_field is not None:
            payload["code_field"] = self.code_field
        if self.reference_raster_path is not None:
            payload["reference_raster_path"] = self.reference_raster_path
        return payload


@dataclass(frozen=True)
class ZoneConformalGeologyLandSeaConfig:
    """Validated optional land/sea override carried with geology config."""

    enabled: bool
    path: str | None = None
    sea_value: float = 0.0
    override_code: str = "1"

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "ZoneConformalGeologyLandSeaConfig":
        return cls(
            enabled=bool(payload.get("enabled", False)),
            path=None if payload.get("path") is None else str(payload["path"]),
            sea_value=float(payload.get("sea_value", 0.0)),
            override_code=str(payload.get("override_code", "1")),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "sea_value": self.sea_value,
            "override_code": self.override_code,
        }
        if self.path is not None:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class ZoneConformalGeologyConfig:
    """Validated geology config carried through conformal planning."""

    id: str
    source: ZoneConformalGeologySourceConfig
    clip_polygon_path: str | None
    landsea: ZoneConformalGeologyLandSeaConfig
    cell_samples_per_axis: int

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "ZoneConformalGeologyConfig":
        return cls(
            id=str(payload["id"]),
            source=ZoneConformalGeologySourceConfig.from_mapping(
                payload["source"],
            ),
            clip_polygon_path=(
                None
                if payload.get("clip_polygon_path") is None
                else str(payload["clip_polygon_path"])
            ),
            landsea=ZoneConformalGeologyLandSeaConfig.from_mapping(
                payload.get("landsea", {}),
            ),
            cell_samples_per_axis=int(payload.get("cell_samples_per_axis", 8)),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "source": self.source.to_mapping(),
            "landsea": self.landsea.to_mapping(),
            "cell_samples_per_axis": self.cell_samples_per_axis,
        }
        if self.clip_polygon_path is not None:
            payload["clip_polygon_path"] = self.clip_polygon_path
        return payload


ZoneConformalDomainConfig = ZoneMeshingDomainConfig


ZoneConformalZoneMeshingConfig = ZoneMeshingSettings


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
    geology: ZoneConformalGeologyConfig | None
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
    source_domain_gdf: gpd.GeoDataFrame
    zone_gdf: gpd.GeoDataFrame
    domain_payload: ZoneConformalGeometryPayload
    interface_scope_payload: ZoneConformalGeometryPayload
    refinement_scope_payload: ZoneConformalGeometryPayload
    interface_scope_is_custom: bool
    refinement_scope_is_custom: bool
    zone_meshing_cfg: ZoneConformalZoneMeshingConfig
    rivers_cfg: ZoneConformalRiversConfig | None
    watershed_boundary_cfg: ZoneConformalWatershedBoundaryConfig | None
    watershed_boundary_absorbed_by_scope: bool
    resolved_river_trace: object | None
    linear_constraints: tuple[ZoneLinearConstraint, ...]


__all__ = [
    "ZoneConformalCaseConfig",
    "ZoneConformalConstraintUsage",
    "ZoneConformalDomainConfig",
    "ZoneConformalGeologyConfig",
    "ZoneConformalGeologyLandSeaConfig",
    "ZoneConformalGeologySourceConfig",
    "ZoneConformalGeometryPayload",
    "ZoneConformalMeshingInputs",
    "ZoneConformalRiversConfig",
    "ZoneConformalSourcePayload",
    "ZoneConformalWatershedBoundaryConfig",
    "ZoneConformalWatershedBoundarySmoothingConfig",
    "ZoneConformalZoneMeshingConfig",
]
