"""Configuration models for the site-selection workflow.

The models in this module describe the selection strategy and its criteria.
They deliberately do not implement hydrologic algorithms. Hydrologic rasters and
catchment delineation are delegated to existing ``hydromodpy.spatial`` modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.administrative_france import validate_french_regions
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

SelectionPrinciple = Literal["observation_led", "criteria_crossing"]
StrategyProfile = Literal[
    "dem_only",
    "area_only",
    "multicriteria",
    "gauged_downstream_station",
]
CriterionMode = Literal["hard_reject", "warning", "score", "stratify", "report_only"]
ObservationRole = Literal["primary", "bonus", "score", "stratify", "report_only", "ignore"]
CandidateMode = Literal[
    "network_sampling",
    "dem_area_light",
    "station_outlets",
    "imported_points",
]
OutletSnapStrategy = Literal["dem_accumulation", "bdtopage_then_dem"]
ReferenceNetworkSource = Literal["bdtopage", "custom"]
RouteOverlapMode = Literal["hard_reject", "warning", "score", "report_only"]
SpatialQuotaMode = Literal["none", "grid"]
WorkflowInputMode = Literal[
    "auto",
    "plan_only",
    "hydrometry",
    "delineated_catchments",
    "generated_candidates",
    "dem_area_light",
]
MapContextLayerRole = Literal["territory", "hydrography", "geology", "other"]
InfluenceType = Literal[
    "major_dam_upstream",
    "major_withdrawal_upstream",
    "major_regulated_reach",
]
StationInfluenceUnknownPolicy = Literal["neutral", "warning"]


def _normalize_report_mode(value: object) -> object:
    if isinstance(value, str) and value.strip().lower() == "report":
        return "report_only"
    return value


class StrategyConfig(HydroModelBase):
    """High-level strategy controlling candidate generation and criterion order."""

    principle: Annotated[SelectionPrinciple, Profile.USER] = Field(
        default="criteria_crossing",
        description="Selection principle: observation-led or direct criteria crossing.",
    )
    profile: Annotated[StrategyProfile | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional selection profile. Short-term supported profiles are "
            "'area_only' and 'gauged_downstream_station'."
        ),
    )
    primary_axes: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Physical or spatial axes that drive a criteria_crossing selection.",
    )
    observation_role: Annotated[ObservationRole, Profile.USER] = Field(
        default="report_only",
        description="How observations influence a criteria_crossing campaign.",
    )
    geology_role: Annotated[ObservationRole, Profile.USER] = Field(
        default="report_only",
        description="How geology influences a criteria_crossing campaign.",
    )
    primary_observation_type: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Observation family required by an observation_led strategy.",
    )
    observation_source: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Provider or normalized source used for primary observations.",
    )
    candidate_mode: Annotated[CandidateMode | None, Profile.USER] = Field(
        default=None,
        description="Optional strategy-level candidate generation mode.",
    )

    @model_validator(mode="after")
    def _validate_strategy(self) -> StrategyConfig:
        if self.principle == "observation_led":
            if not self.primary_observation_type:
                raise ValueError(
                    "observation_led requires primary_observation_type "
                    "(for example 'flow_station')."
                )
            if self.profile not in {None, "gauged_downstream_station"}:
                raise ValueError(
                    "observation_led accepts only profile='gauged_downstream_station'."
                )

        if self.profile == "gauged_downstream_station":
            if self.principle != "observation_led":
                raise ValueError(
                    "profile='gauged_downstream_station' requires "
                    "principle='observation_led'."
                )
            if self.primary_observation_type != "flow_station":
                raise ValueError(
                    "profile='gauged_downstream_station' requires "
                    "primary_observation_type='flow_station'."
                )
            if self.candidate_mode not in {None, "station_outlets"}:
                raise ValueError(
                    "profile='gauged_downstream_station' requires "
                    "candidate_mode='station_outlets'."
                )

        if self.profile == "area_only":
            if self.principle != "criteria_crossing":
                raise ValueError("profile='area_only' requires principle='criteria_crossing'.")
            axes = {axis.strip().lower() for axis in self.primary_axes}
            if axes != {"area"}:
                raise ValueError("profile='area_only' requires primary_axes = ['area'].")
            if self.observation_role not in {"report_only", "ignore"}:
                raise ValueError("area_only requires observation_role='report_only' or 'ignore'.")
            if self.geology_role not in {"report_only", "ignore"}:
                raise ValueError("area_only requires geology_role='report_only' or 'ignore'.")

        return self


class TerritoryConfig(HydroModelBase):
    """Spatial domain where candidate basins are searched."""

    mode: Annotated[
        Literal[
            "admin_regions",
            "admin_departments",
            "polygon_file",
            "bbox",
            "site_catalog_extent",
            "geoparquet_filter",
        ],
        Profile.USER,
    ] = Field(default="bbox", description="Territory resolver mode.")
    country: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Country code used by administrative territory modes.",
    )
    regions: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Administrative regions used when mode='admin_regions'.",
    )
    departments: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Administrative departments used when mode='admin_departments'.",
    )
    polygon_file: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="User polygon file used when mode='polygon_file'.",
    )
    bbox: Annotated[tuple[float, float, float, float] | None, Profile.USER] = Field(
        default=None,
        description="Territory bounds as xmin, ymin, xmax, ymax.",
    )
    clip_to_territory: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Clip candidate basins or outlets to the requested territory.",
    )

    @model_validator(mode="after")
    def _validate_territory(self) -> TerritoryConfig:
        if self.mode == "admin_regions" and not self.regions:
            raise ValueError("mode='admin_regions' requires at least one region.")
        if self.mode == "admin_regions" and str(self.country or "").upper() == "FR":
            object.__setattr__(self, "regions", validate_french_regions(self.regions))
        if self.mode == "admin_departments" and not self.departments:
            raise ValueError("mode='admin_departments' requires at least one department.")
        if self.mode == "polygon_file" and self.polygon_file is None:
            raise ValueError("mode='polygon_file' requires polygon_file.")
        if self.mode == "bbox" and self.bbox is None:
            raise ValueError("mode='bbox' requires bbox.")
        return self


class DemConfig(HydroModelBase):
    """DEM source requested by site selection."""

    source: Annotated[Literal["custom", "data", "ign_geoplateforme_dem"], Profile.USER] = Field(
        default="custom",
        description=(
            "DEM source identifier: custom path, data section, or ign_geoplateforme_dem."
        ),
    )
    path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="Local DEM path when source='custom'.",
    )
    resolution_m: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="DEM resolution in metres.",
    )
    cache_policy: Annotated[str, Profile.USER] = Field(
        default="use_cache_else_download",
        description="Data cache policy.",
    )
    margin_km: Annotated[float, Profile.USER] = Field(
        default=0.0,
        ge=0,
        description="DEM request margin around the territory in kilometres.",
    )
    request_extent: Annotated[Literal["territory", "outlets"], Profile.USER] = Field(
        default="territory",
        description=(
            "Spatial extent used when a DEM is loaded through [data.dem]. "
            "'territory' requests the configured selection territory; 'outlets' "
            "requests the bounding box of imported outlets expanded by margin_km."
        ),
    )
    map_background_extent: Annotated[
        Literal["none", "delineation", "territory"],
        Profile.USER,
    ] = Field(
        default="delineation",
        description=(
            "DEM extent used only for review-map background. 'delineation' reuses "
            "the DEM used to calculate basin contours; 'territory' loads a "
            "regional DEM through [data.dem] without using it for delineation."
        ),
    )
    force_refresh: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Ignore existing cached data when supported by the provider.",
    )


class HydrologyConfig(HydroModelBase):
    """DEM-derived hydrologic products requested by the selection workflow."""

    method: Annotated[Literal["dem_only"], Profile.USER] = Field(
        default="dem_only",
        description="Hydrologic product generation method.",
    )
    flow_algorithm: Annotated[Literal["d8"], Profile.USER] = Field(
        default="d8",
        description="Flow routing algorithm used by existing spatial products.",
    )
    hydrologic_conditioning: Annotated[
        Literal["existing_default", "fill", "breach"],
        Profile.USER,
    ] = Field(
        default="existing_default",
        description="DEM conditioning strategy forwarded to existing flow products.",
    )
    network_threshold_area_km2: Annotated[float, Profile.USER] = Field(
        default=1.0,
        gt=0,
        description="Contributing-area threshold used to extract the stream network.",
    )
    compute_strahler: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Request Strahler diagnostics if existing spatial primitives support them.",
    )

    @property
    def dem_correction_type(self) -> Literal["fill", "breach"]:
        """Return the existing flow-products correction keyword."""

        if self.hydrologic_conditioning == "breach":
            return "breach"
        return "fill"


class DemAreaLightConfig(HydroModelBase):
    """Minimal DEM-only basin selection settings."""

    target_area_km2: Annotated[float, Profile.USER] = Field(
        default=100.0,
        gt=0,
        description="Preferred upstream basin area for DEM-only candidate outlets.",
    )
    min_area_km2: Annotated[float, Profile.USER] = Field(
        default=75.0,
        gt=0,
        description="Minimum accepted upstream basin area.",
    )
    max_area_km2: Annotated[float, Profile.USER] = Field(
        default=125.0,
        gt=0,
        description="Maximum accepted upstream basin area.",
    )
    n_basins: Annotated[int, Profile.USER] = Field(
        default=50,
        gt=0,
        description="Target number of basins selected by the greedy light workflow.",
    )
    max_candidates_before_delineation: Annotated[int | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Optional cap on DEM-area outlet candidates delineated before final "
            "selection. Lower values make examples faster but can leave fewer "
            "accepted basins after spatial filtering."
        ),
    )

    @model_validator(mode="after")
    def _validate_area_window(self) -> DemAreaLightConfig:
        if self.min_area_km2 > self.max_area_km2:
            raise ValueError("min_area_km2 must be <= max_area_km2.")
        if not (self.min_area_km2 <= self.target_area_km2 <= self.max_area_km2):
            raise ValueError("target_area_km2 must be inside [min_area_km2, max_area_km2].")
        return self


class OutletsConfig(HydroModelBase):
    """Candidate outlet generation settings."""

    candidate_mode: Annotated[CandidateMode, Profile.USER] = Field(
        default="network_sampling",
        description="How candidate outlets are generated.",
    )
    min_distance_between_outlets_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Minimum distance between generated outlets.",
    )
    allow_nested_basins: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Allow nested candidate basins before final selection.",
    )
    max_generated_candidates: Annotated[int | None, Profile.USER] = Field(
        default=200,
        gt=0,
        description="Maximum number of DEM/network-generated candidates to delineate.",
    )
    max_rejected_candidate_audit_records: Annotated[int | None, Profile.USER] = Field(
        default=5000,
        gt=0,
        description=(
            "Maximum number of rejected DEM/network candidate cells written to the "
            "candidate-generation audit JSONL."
        ),
    )
    max_generated_network_cells: Annotated[int | None, Profile.USER] = Field(
        default=50000,
        gt=0,
        description=(
            "Maximum number of DEM-derived stream cells exported to the generated "
            "network vector layer. Highest-accumulation cells are kept first."
        ),
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
    )
    reference_network_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="Local vector network used when reference_network_source='custom'.",
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
        description="Maximum number of catchments kept after ranking and spatial thinning.",
    )
    allow_nested_basins: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Allow selected basins to be nested.",
    )
    min_outlet_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Minimum spacing between selected outlets.",
    )
    max_pairwise_basin_overlap_fraction: Annotated[float | None, Profile.USER] = Field(
        default=None,
        ge=0,
        le=1,
        description="Maximum allowed overlap fraction between selected basins.",
    )
    overlap_reference: Annotated[Literal["smaller_basin", "candidate", "selected"], Profile.USER] = (
        Field(default="smaller_basin", description="Denominator used for overlap fraction.")
    )
    overlap_mode: Annotated[RouteOverlapMode, Profile.USER] = Field(
        default="hard_reject",
        description="How overlap violations affect selection.",
    )
    same_mainstem_policy: Annotated[
        Literal["allow_with_warning", "reject_downstream", "keep_best"] | None,
        Profile.USER,
    ] = Field(
        default=None,
        description="Optional policy for candidates on the same mainstem.",
    )
    spatial_quota_mode: Annotated[SpatialQuotaMode, Profile.USER] = Field(
        default="none",
        description="Optional coarse spatial quota applied after ranking.",
    )
    spatial_quota_cell_size_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Grid cell size used when spatial_quota_mode='grid'.",
    )
    spatial_quota_max_sites_per_cell: Annotated[int, Profile.USER] = Field(
        default=1,
        ge=1,
        description="Maximum selected sites allowed in one spatial quota cell.",
    )

    @model_validator(mode="after")
    def _validate_spatial_quota(self) -> SpatialSelectionConfig:
        if self.spatial_quota_mode == "grid" and self.spatial_quota_cell_size_km is None:
            raise ValueError(
                "spatial_quota_mode='grid' requires spatial_quota_cell_size_km."
            )
        return self


class SiteSelectionInputConfig(HydroModelBase):
    """Execution input selector used by the ``site_selection`` workflow."""

    mode: Annotated[WorkflowInputMode, Profile.USER] = Field(
        default="auto",
        description=(
            "Workflow input mode. auto uses catchments_csv when present, "
            "otherwise [hydrometry] when present, otherwise only writes a plan."
        ),
    )
    catchments_csv: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Pre-delineated catchments CSV used when mode='delineated_catchments'."
        ),
    )
    region_id: Annotated[str, Profile.USER] = Field(
        default="",
        description="Optional region identifier written to regional-lab CSV outputs.",
    )
    workspace_root: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="Optional workspace root forwarded to data-manager based loading.",
    )
    data_root: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="Optional data root forwarded to data-manager based loading.",
    )
    write_plan_manifest: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write site_selection_plan.json when the workflow is run in plan mode.",
    )
    delineate_from_outlets: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "When using catchments_csv, compute watershed contours from outlet "
            "coordinates and DEM flow products instead of trusting watershed_shp."
        ),
    )

    @model_validator(mode="after")
    def _validate_input(self) -> SiteSelectionInputConfig:
        if self.mode == "delineated_catchments" and self.catchments_csv is None:
            raise ValueError("mode='delineated_catchments' requires catchments_csv.")
        return self


class AreaRangeConfig(HydroModelBase):
    """Readable basin-area interval used by selection criteria."""

    range_id: Annotated[str, Profile.USER] = Field(
        default="",
        description="Stable identifier for the area range.",
    )
    label: Annotated[str, Profile.USER] = Field(
        default="",
        description="Human-readable area range label.",
    )
    min_area_km2: Annotated[float, Profile.USER] = Field(
        ...,
        gt=0,
        description="Minimum basin area for this range.",
    )
    max_area_km2: Annotated[float, Profile.USER] = Field(
        ...,
        gt=0,
        description="Maximum basin area for this range.",
    )

    @model_validator(mode="after")
    def _validate_range(self) -> AreaRangeConfig:
        if self.min_area_km2 > self.max_area_km2:
            raise ValueError("min_area_km2 must be <= max_area_km2.")
        return self


class AreaCriteriaConfig(HydroModelBase):
    """Area criterion configuration."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description="How basin area contributes to selection.",
    )
    target_area_km2: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Named target area used for reporting or strict area profiles.",
    )
    preferred_area_km2: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Preferred area used by score-based campaigns.",
    )
    score_half_width_fraction: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Relative half-width of the area score around preferred_area_km2.",
    )
    hard_min_area_km2: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Hard lower area bound when configured.",
    )
    hard_max_area_km2: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Hard upper area bound when configured.",
    )
    ranges: Annotated[list[AreaRangeConfig], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Explicit area ranges used for hard rejection, warnings or "
            "stratification. Prefer this over target/preferred area fields "
            "when the campaign is defined by minimum and maximum basin sizes."
        ),
    )

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        return _normalize_report_mode(value)

    @model_validator(mode="after")
    def _validate_area(self) -> AreaCriteriaConfig:
        if (
            self.hard_min_area_km2 is not None
            and self.hard_max_area_km2 is not None
            and self.hard_min_area_km2 > self.hard_max_area_km2
        ):
            raise ValueError("hard_min_area_km2 must be <= hard_max_area_km2.")
        if self.mode == "score" and self.preferred_area_km2 is None:
            raise ValueError("area mode='score' requires preferred_area_km2.")
        if self.mode == "score" and self.score_half_width_fraction is None:
            raise ValueError("area mode='score' requires score_half_width_fraction.")
        if (
            self.mode == "hard_reject"
            and not self.ranges
            and self.hard_min_area_km2 is None
            and self.hard_max_area_km2 is None
        ):
            raise ValueError(
                "area mode='hard_reject' requires at least one area range "
                "or a hard min/max area."
            )
        return self


class FlowStationCriteriaConfig(HydroModelBase):
    """Criteria applied to flow stations in observation-led selections."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(default="report_only")
    min_record_years: Annotated[float | None, Profile.USER] = Field(default=None, gt=0)
    max_station_to_outlet_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
    )
    require_station_inside_or_at_outlet: Annotated[bool, Profile.USER] = Field(default=False)

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        return _normalize_report_mode(value)


class StationInfluenceCriteriaConfig(HydroModelBase):
    """Criteria applied to station influence metadata."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(default="report_only")
    source: Annotated[str, Profile.USER] = Field(default="hubeau_station_metadata")
    warn_if_general_influence: Annotated[bool, Profile.USER] = Field(default=True)
    warn_if_local_influence: Annotated[bool, Profile.USER] = Field(default=True)
    warn_if_comment_keyword: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Report comment keyword matches as warnings. Comment keywords are "
            "not treated as hard-reject evidence."
        ),
    )
    unknown_policy: Annotated[StationInfluenceUnknownPolicy, Profile.USER] = Field(
        default="neutral",
    )
    comment_keywords: Annotated[list[str], Profile.USER] = Field(
        default_factory=lambda: [
            "barrage",
            "retenue",
            "derivation",
            "canal",
            "ecluse",
            "ouvrage",
            "regulation",
            "turbinage",
            "hydroelectrique",
            "usine",
        ],
        description="Keywords searched in station influence comments.",
    )

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        return _normalize_report_mode(value)


class PiezometerLayerConfig(HydroModelBase):
    """Vector layer used to compute piezometer evidence."""

    name: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Human-readable piezometer layer name.",
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description="Vector file containing piezometer features.",
    )
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source-feature identifier field.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source-feature label field.",
    )
    record_years_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional field containing available record length in years.",
    )
    quality_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional field containing a quality/status label.",
    )


class ObservationsCriteriaConfig(HydroModelBase):
    """Criteria applied to observation families."""

    flow_station_mode: Annotated[CriterionMode, Profile.USER] = Field(default="report_only")
    flow_station_max_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
    )
    piezometer_mode: Annotated[CriterionMode, Profile.USER] = Field(default="report_only")
    piezometer_max_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
    )
    flow_station: Annotated[FlowStationCriteriaConfig, Profile.USER] = Field(
        default_factory=FlowStationCriteriaConfig,
    )
    station_influence: Annotated[StationInfluenceCriteriaConfig, Profile.USER] = Field(
        default_factory=StationInfluenceCriteriaConfig,
    )
    piezometer_layers: Annotated[list[PiezometerLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional vector layers used to compute piezometer evidence.",
    )

    @field_validator("flow_station_mode", "piezometer_mode", mode="before")
    @classmethod
    def _normalize_modes(cls, value: object) -> object:
        return _normalize_report_mode(value)


class InfluenceLayerConfig(HydroModelBase):
    """Vector layer used to compute anthropic-influence evidence."""

    name: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Human-readable influence layer name.",
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description="Vector file containing influence features.",
    )
    influence_type: Annotated[InfluenceType, Profile.USER] = Field(
        ...,
        description="Normalized influence flag filled when features match a basin.",
    )
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source-feature identifier field.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source-feature label field.",
    )
    severity_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional field used to classify major features.",
    )
    major_values: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Values considered major in severity_field. When empty, every "
            "matched feature is considered major."
        ),
    )


class InfluenceCriteriaConfig(HydroModelBase):
    """Known-influence checks for observation-led campaigns."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(default="report_only")
    reject_major_dam_upstream: Annotated[bool, Profile.USER] = Field(default=False)
    reject_major_withdrawal_upstream: Annotated[bool, Profile.USER] = Field(default=False)
    reject_major_regulated_reach: Annotated[bool, Profile.USER] = Field(default=False)
    influence_search_radius_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
    )
    layers: Annotated[list[InfluenceLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional vector layers used to compute influence flags automatically.",
    )

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        return _normalize_report_mode(value)


class GeologyLayerConfig(HydroModelBase):
    """Polygon layer used to compute basin geology classes."""

    name: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Human-readable geology layer name.",
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description="Vector polygon file containing geology units.",
    )
    class_field: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Feature field containing the geology class.",
    )
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source-feature identifier field.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source-feature label field.",
    )


class GeologyCriteriaConfig(HydroModelBase):
    """Geology criterion configuration."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(default="report_only")
    prefer_diversity: Annotated[bool, Profile.USER] = Field(default=False)
    layers: Annotated[list[GeologyLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional polygon layers used to compute geology evidence.",
    )

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        return _normalize_report_mode(value)


class CriteriaConfig(HydroModelBase):
    """Versioned criteria set and criterion-mode lists."""

    ruleset: Annotated[str, Profile.USER] = Field(default="site_selection_v1")
    hard_reject: Annotated[list[str], Profile.USER] = Field(default_factory=list)
    warning: Annotated[list[str], Profile.USER] = Field(default_factory=list)
    soft_score: Annotated[list[str], Profile.USER] = Field(default_factory=list)
    report_only: Annotated[list[str], Profile.USER] = Field(default_factory=list)
    area: Annotated[AreaCriteriaConfig, Profile.USER] = Field(default_factory=AreaCriteriaConfig)
    observations: Annotated[ObservationsCriteriaConfig, Profile.USER] = Field(
        default_factory=ObservationsCriteriaConfig,
    )
    influence: Annotated[InfluenceCriteriaConfig, Profile.USER] = Field(
        default_factory=InfluenceCriteriaConfig,
    )
    geology: Annotated[GeologyCriteriaConfig, Profile.USER] = Field(
        default_factory=GeologyCriteriaConfig,
    )

    @model_validator(mode="after")
    def _validate_disjoint_mode_lists(self) -> CriteriaConfig:
        seen: dict[str, str] = {}
        for family, values in (
            ("hard_reject", self.hard_reject),
            ("warning", self.warning),
            ("soft_score", self.soft_score),
            ("report_only", self.report_only),
        ):
            for value in values:
                key = value.strip()
                previous = seen.get(key)
                if previous is not None:
                    raise ValueError(
                        f"criterion {key!r} is listed in both {previous} and {family}."
                    )
                seen[key] = family
        return self


class OutputConfig(HydroModelBase):
    """Output artifact switches."""

    write_candidates: Annotated[bool, Profile.USER] = Field(default=False)
    write_rejected: Annotated[bool, Profile.USER] = Field(default=True)
    write_selected: Annotated[bool, Profile.USER] = Field(default=True)
    write_geojson: Annotated[bool, Profile.USER] = Field(default=True)
    write_geoparquet: Annotated[bool, Profile.USER] = Field(default=False)
    write_geopackage: Annotated[bool, Profile.USER] = Field(default=False)
    write_csv: Annotated[bool, Profile.USER] = Field(default=True)
    write_regional_lab_csv: Annotated[bool, Profile.USER] = Field(default=True)
    write_report_md: Annotated[bool, Profile.USER] = Field(default=False)
    write_report_html: Annotated[bool, Profile.USER] = Field(default=False)


class MapContextLayerConfig(HydroModelBase):
    """Optional layer shown only on site-selection review maps."""

    name: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Human-readable layer name used in the map/report manifest.",
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description="GeoJSON file used as static map context.",
    )
    role: Annotated[MapContextLayerRole, Profile.USER] = Field(
        default="other",
        description="Visual role controlling the default map style.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional feature-property field used for future labels.",
    )


class MapContextConfig(HydroModelBase):
    """Optional static context layers for review figures."""

    layers: Annotated[list[MapContextLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Context vector layers drawn behind selection artifacts.",
    )


class SiteSelectionConfig(HydroModelBase):
    """Top-level site-selection workflow configuration."""

    _TOML_SECTION = "site_selection"

    selection_id: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Stable identifier for this selection campaign.",
    )
    output_root: Annotated[Path, Profile.USER] = Field(
        ...,
        description="Output directory for all site-selection artifacts.",
    )
    random_seed: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description="Optional seed used by stochastic candidate thinning.",
    )
    strategy: Annotated[StrategyConfig, Profile.USER] = Field(default_factory=StrategyConfig)
    territory: Annotated[TerritoryConfig, Profile.USER] = Field(
        ...,
        description="Territory where candidate basins are searched.",
    )
    dem: Annotated[DemConfig, Profile.USER] = Field(default_factory=DemConfig)
    hydrology: Annotated[HydrologyConfig, Profile.USER] = Field(default_factory=HydrologyConfig)
    dem_area_light: Annotated[DemAreaLightConfig | None, Profile.USER] = Field(
        default=None,
        description="Compact settings for DEM-only automatic small-basin selection.",
    )
    input: Annotated[SiteSelectionInputConfig, Profile.USER] = Field(
        default_factory=SiteSelectionInputConfig,
    )
    outlets: Annotated[OutletsConfig, Profile.USER] = Field(default_factory=OutletsConfig)
    spatial_selection: Annotated[SpatialSelectionConfig, Profile.USER] = Field(
        default_factory=SpatialSelectionConfig,
    )
    criteria: Annotated[CriteriaConfig, Profile.USER] = Field(default_factory=CriteriaConfig)
    output: Annotated[OutputConfig, Profile.USER] = Field(default_factory=OutputConfig)
    map_context: Annotated[MapContextConfig, Profile.USER] = Field(
        default_factory=MapContextConfig,
    )

    @model_validator(mode="after")
    def _validate_selection_config(self) -> SiteSelectionConfig:
        if self.strategy.principle == "observation_led":
            mode = self.strategy.candidate_mode or self.outlets.candidate_mode
            if mode != "station_outlets":
                raise ValueError(
                    "observation_led requires candidate_mode='station_outlets' "
                    "in strategy or outlets."
                )

        if self.input.mode == "dem_area_light" and self.dem_area_light is None:
            object.__setattr__(self, "dem_area_light", DemAreaLightConfig())

        if self.strategy.profile == "area_only":
            allowed_report_modes = {"report_only"}
            if self.criteria.observations.flow_station_mode not in allowed_report_modes:
                raise ValueError("area_only requires flow_station_mode='report_only'.")
            if self.criteria.observations.piezometer_mode not in allowed_report_modes:
                raise ValueError("area_only requires piezometer_mode='report_only'.")
            if self.criteria.geology.mode != "report_only":
                raise ValueError("area_only requires geology.mode='report_only'.")
            if self.criteria.area.mode not in {"hard_reject", "score", "stratify"}:
                raise ValueError("area_only requires area to be an active criterion.")

        if self.strategy.profile == "gauged_downstream_station":
            mode = self.strategy.candidate_mode or self.outlets.candidate_mode
            if mode != "station_outlets":
                raise ValueError(
                    "profile='gauged_downstream_station' requires "
                    "candidate_mode='station_outlets' in strategy or outlets."
                )
            if self.strategy.primary_observation_type != "flow_station":
                raise ValueError(
                    "profile='gauged_downstream_station' requires "
                    "primary_observation_type='flow_station'."
                )

        return self

    @property
    def effective_profile(self) -> str:
        """Return the explicit profile or the short-term profile inferred from the config."""

        if self.strategy.profile:
            return self.strategy.profile
        mode = self.strategy.candidate_mode or self.outlets.candidate_mode
        if (
            self.strategy.principle == "observation_led"
            and self.strategy.primary_observation_type == "flow_station"
            and mode == "station_outlets"
        ):
            return "gauged_downstream_station"
        if self.input.mode == "dem_area_light":
            return "area_only"
        return "custom"


__all__ = [
    "AreaCriteriaConfig",
    "AreaRangeConfig",
    "CandidateMode",
    "CriteriaConfig",
    "CriterionMode",
    "DemAreaLightConfig",
    "DemConfig",
    "FlowStationCriteriaConfig",
    "GeologyCriteriaConfig",
    "GeologyLayerConfig",
    "HydrologyConfig",
    "InfluenceCriteriaConfig",
    "InfluenceLayerConfig",
    "InfluenceType",
    "MapContextConfig",
    "MapContextLayerConfig",
    "MapContextLayerRole",
    "ObservationRole",
    "ObservationsCriteriaConfig",
    "OutletSnapStrategy",
    "OutletsConfig",
    "OutputConfig",
    "PiezometerLayerConfig",
    "ReferenceNetworkSource",
    "RouteOverlapMode",
    "SelectionPrinciple",
    "SiteSelectionInputConfig",
    "SiteSelectionConfig",
    "SpatialSelectionConfig",
    "SpatialQuotaMode",
    "StationInfluenceCriteriaConfig",
    "StationInfluenceUnknownPolicy",
    "StrategyConfig",
    "StrategyProfile",
    "TerritoryConfig",
    "WorkflowInputMode",
]
