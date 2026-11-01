"""The ``[site_selection.outlets]`` and ``[site_selection.spatial_selection]`` tables."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.site_selection.config.value_types import (
    CANDIDATE_MODE_VALUE_DOCS,
    CandidateMode,
    OutletSnapStrategy,
    ReferenceNetworkSource,
    RouteOverlapMode,
    SpatialQuotaMode,
)

__all__ = [
    "OutletsConfig",
    "SpatialSelectionConfig",
]


class OutletsConfig(HydroModelBase):
    """Candidate outlet generation settings."""

    candidate_mode: Annotated[CandidateMode, Profile.USER] = Field(
        default="network_sampling",
        description=(
            "How candidate outlets are generated: sampled on the DEM stream network, or "
            "taken at the observation stations."
        ),
        json_schema_extra={"value_docs": CANDIDATE_MODE_VALUE_DOCS},
    )
    min_distance_between_outlets_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Smallest distance, in km, between two generated candidate outlets. Unset, "
            "outlets may sit as close as the network allows."
        ),
    )
    allow_nested_basins: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Allow nested candidate basins before final selection.",
    )
    max_generated_candidates: Annotated[int | None, Profile.USER] = Field(
        default=200,
        gt=0,
        description=(
            "Most candidate outlets generated from the DEM stream network and delineated. "
            "Unset, there is no cap. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    max_rejected_candidate_audit_records: Annotated[int | None, Profile.USER] = Field(
        default=5000,
        gt=0,
        description=(
            "Most rejected candidate cells written to the candidate-generation audit "
            "file (JSON lines). Unset, every rejected cell is written. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    max_generated_network_cells: Annotated[int | None, Profile.USER] = Field(
        default=50000,
        gt=0,
        description=(
            "Most DEM stream cells written to the generated network vector layer. The "
            "cells with the highest accumulation are kept first. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    snap_to_generated_stream: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Snap outlets to the DEM-derived stream network when applicable.",
    )
    snap_strategy: Annotated[OutletSnapStrategy, Profile.USER] = Field(
        default="dem_accumulation",
        description=(
            "Outlet snapping strategy. 'dem_accumulation' snaps directly on the "
            "DEM-derived accumulation raster. 'bdtopage_then_dem' first projects "
            "the station to BD Topage, then snaps locally on the DEM raster."
        ),
    )
    snap_dist_m: Annotated[int, Profile.USER] = Field(
        default=150,
        gt=0,
        description="Maximum snapping distance in metres for outlet-based delineation.",
    )
    reference_network_source: Annotated[ReferenceNetworkSource, Profile.USER] = Field(
        default="bdtopage",
        description="Reference hydrographic network used by bdtopage_then_dem.",
        json_schema_extra={
            "value_docs": {
                "bdtopage": (
                    "Downloads the reference stream network from the BD Topage WFS service."
                ),
                "custom": (
                    "Uses the local vector file at reference_network_path as the reference network."
                ),
            }
        },
    )
    reference_network_path: Annotated[
        Path | None, Profile.USER, VisibleWhen("reference_network_source", "custom")
    ] = Field(
        default=None,
        description=(
            "Local vector file of the reference stream network. Read by "
            "snap_strategy = 'bdtopage_then_dem'."
        ),
    )
    reference_network_max_distance_m: Annotated[float, Profile.USER] = Field(
        default=100.0,
        gt=0,
        description="Maximum accepted distance from candidate outlet to the reference network.",
    )
    reference_network_fetch_margin_m: Annotated[float, Profile.USER] = Field(
        default=500.0,
        ge=0,
        description="Extra margin around outlets when downloading a BD Topage reference network.",
    )
    reference_network_page_size: Annotated[int, Profile.DEV] = Field(
        default=2000,
        gt=0,
        description="BD Topage WFS page size used for the reference network download.",
    )
    reference_network_force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Redownload BD Topage even if the run output already contains a network file.",
    )

    @model_validator(mode="after")
    def _validate_reference_network(self) -> OutletsConfig:
        if (
            self.snap_strategy == "bdtopage_then_dem"
            and self.reference_network_source == "custom"
            and self.reference_network_path is None
        ):
            raise ValueError(
                "snap_strategy='bdtopage_then_dem' with "
                "reference_network_source='custom' requires reference_network_path."
            )
        return self


class SpatialSelectionConfig(HydroModelBase):
    """Spatial thinning and overlap policy."""

    max_selected_sites: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "Most catchments kept after ranking and spatial thinning. Unset, every "
            "accepted catchment is kept. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    allow_nested_basins: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Allow selected basins to be nested.",
    )
    min_outlet_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Smallest distance, in km, between two selected outlets. Unset, no spacing is enforced."
        ),
    )
    max_pairwise_basin_overlap_fraction: Annotated[float | None, Profile.USER] = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Largest share of a basin that may overlap an already selected basin, from 0 "
            "to 1. The share is taken against the area overlap_reference names. Unset, "
            "overlap is not checked."
        ),
        json_schema_extra={"unit": "-"},
    )
    overlap_reference: Annotated[
        Literal["smaller_basin", "candidate", "selected"], Profile.USER
    ] = Field(
        default="smaller_basin",
        description=(
            "Which basin area divides the overlap area to give the overlap share "
            "compared with max_pairwise_basin_overlap_fraction."
        ),
        json_schema_extra={
            "value_docs": {
                "smaller_basin": (
                    "Divides the intersection area by the area of the smaller of the two basins."
                ),
                "candidate": "Divides the intersection area by the candidate basin's own area.",
                "selected": (
                    "Divides the intersection area by the already-selected basin's own area."
                ),
            }
        },
    )
    overlap_mode: Annotated[RouteOverlapMode, Profile.USER] = Field(
        default="hard_reject",
        description=(
            "What happens to a candidate whose overlap share exceeds "
            "max_pairwise_basin_overlap_fraction."
        ),
        json_schema_extra={
            "value_docs": {
                "hard_reject": (
                    "Rejects a candidate whose basin overlap exceeds the configured threshold."
                ),
                "warning": (
                    "Flags excess basin overlap as a warning without rejecting the candidate."
                ),
                "score": (
                    "Behaves like warning here: flags excess overlap without computing a score."
                ),
                "report_only": (
                    "Behaves like warning here: flags excess overlap rather than only recording it."
                ),
            }
        },
    )
    spatial_quota_mode: Annotated[SpatialQuotaMode, Profile.USER] = Field(
        default="none",
        description="Optional coarse spatial quota applied after ranking.",
        json_schema_extra={
            "value_docs": {
                "none": "Applies no spatial quota; ranking alone decides which sites are kept.",
                "grid": ("Rejects extra candidates once a grid cell already holds its site quota."),
            }
        },
    )
    spatial_quota_cell_size_km: Annotated[
        float | None, Profile.USER, VisibleWhen("spatial_quota_mode", "grid")
    ] = Field(
        default=None,
        gt=0,
        description="Side of the square cells of the quota grid, in km.",
    )
    spatial_quota_max_sites_per_cell: Annotated[
        int, Profile.USER, VisibleWhen("spatial_quota_mode", "grid")
    ] = Field(
        default=1,
        ge=1,
        description=(
            "Most selected sites one quota grid cell may hold. Candidates past it are "
            "rejected in ranking order. A count."
        ),
        json_schema_extra={"unit": "-"},
    )

    @model_validator(mode="after")
    def _validate_spatial_quota(self) -> SpatialSelectionConfig:
        if self.spatial_quota_mode == "grid" and self.spatial_quota_cell_size_km is None:
            raise ValueError("spatial_quota_mode='grid' requires spatial_quota_cell_size_km.")
        return self
