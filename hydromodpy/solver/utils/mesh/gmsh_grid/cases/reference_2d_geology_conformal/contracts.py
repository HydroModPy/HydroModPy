"""Shared contracts for the reference 2D zone-conformal case."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import geopandas as gpd

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingSettings,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.contracts import (
    ZoneLinearConstraint,
    ZoneRegionalSizeField,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.domain import (
    ZoneMeshingDomainConfig,
    ZoneMeshingDomainPayload,
)


@dataclass(frozen=True)
class ZoneConformalConstraintFamilies:
    """Resolved constraint families enabled for one conformal meshing run."""

    geology_interface: bool
    river: bool


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
    ) -> ZoneConformalGeologySourceConfig:
        return cls(
            path=str(payload["path"]),
            kind=str(payload["kind"]),
            code_field=(None if payload.get("code_field") is None else str(payload["code_field"])),
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
    ) -> ZoneConformalGeologyLandSeaConfig:
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
    ) -> ZoneConformalGeologyConfig:
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
    """Optional smoothing controls for the watershed-boundary constraint."""

    enabled: bool
    distance: float | None
    river_buffer_distance: float | None
    outer_bias_distance: float | None


@dataclass(frozen=True)
class ZoneConformalWatershedOutsideCoarseningConfig:
    """Optional coarse-background controls applied outside the watershed."""

    enabled: bool
    size_factor: float
    transition_distance: float | None
    grid_resolution: float | None


@dataclass(frozen=True)
class ZoneConformalWatershedGeologyConformityConfig:
    """Control where geology remains conformal relative to the watershed."""

    mode: str
    buffer_distance: float | None


@dataclass(frozen=True)
class ZoneConformalWatershedBoundaryConfig:
    """Optional watershed-boundary linear-constraint controls."""

    enabled: bool
    boundary_refinement_distance: float | None
    smoothing: ZoneConformalWatershedBoundarySmoothingConfig
    outside_coarsening: ZoneConformalWatershedOutsideCoarseningConfig
    geology_conformity: ZoneConformalWatershedGeologyConformityConfig


@dataclass(frozen=True)
class ZoneConformalCaseConfig:
    """Normalized top-level case configuration consumed by planning."""

    constraint_families: ZoneConformalConstraintFamilies
    constraints_mode_label: str
    geology: ZoneConformalGeologyConfig | None
    rivers: ZoneConformalRiversConfig | None
    watershed_boundary: ZoneConformalWatershedBoundaryConfig
    domain: ZoneConformalDomainConfig
    zone_meshing: ZoneConformalZoneMeshingConfig
    output_mesh: object | None
    output_summary_json: object | None
    output_figure: object | None
    output_figure_regional: object | None
    figure_dpi: int
    figure_regional_dpi: int


@dataclass(frozen=True)
class ZoneConformalMeshingDiagnostics:
    """Secondary artifacts kept for reporting and plotting only."""

    source_plot_gdf: gpd.GeoDataFrame
    rivers_cfg: ZoneConformalRiversConfig | None
    river_trace: object | None
    watershed_boundary_plot_gdf: gpd.GeoDataFrame | None = None
    watershed_boundary_summary: Mapping[str, Any] | None = None
    outside_coarsening_summary: Mapping[str, Any] | None = None
    geology_conformity_summary: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ZoneConformalMeshingInputs:
    """Common meshing contract assembled before calling the Gmsh core."""

    constraint_families: ZoneConformalConstraintFamilies
    constraints_mode_label: str
    source_payload: ZoneConformalSourcePayload
    zone_gdf: gpd.GeoDataFrame
    effective_domain_payload: ZoneConformalGeometryPayload
    zone_meshing_cfg: ZoneConformalZoneMeshingConfig
    linear_constraints: tuple[ZoneLinearConstraint, ...]
    regional_size_fields: tuple[ZoneRegionalSizeField, ...]
    diagnostics: ZoneConformalMeshingDiagnostics


__all__ = [
    "ZoneConformalCaseConfig",
    "ZoneConformalConstraintFamilies",
    "ZoneConformalDomainConfig",
    "ZoneConformalGeologyConfig",
    "ZoneConformalGeologyLandSeaConfig",
    "ZoneConformalGeologySourceConfig",
    "ZoneConformalGeometryPayload",
    "ZoneConformalMeshingDiagnostics",
    "ZoneConformalMeshingInputs",
    "ZoneConformalRiversConfig",
    "ZoneConformalSourcePayload",
    "ZoneConformalWatershedBoundaryConfig",
    "ZoneConformalWatershedGeologyConformityConfig",
    "ZoneConformalWatershedOutsideCoarseningConfig",
    "ZoneConformalWatershedBoundarySmoothingConfig",
    "ZoneConformalZoneMeshingConfig",
    "ZoneRegionalSizeField",
]
