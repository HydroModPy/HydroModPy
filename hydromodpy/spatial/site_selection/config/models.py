"""Configuration models for the site-selection workflow.

The models in this module describe the selection strategy and its criteria.
They deliberately do not implement hydrologic algorithms. Hydrologic rasters and
catchment delineation are delegated to existing ``hydromodpy.spatial`` modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PrivateAttr, model_validator

from hydromodpy.core.administrative_france import validate_french_regions
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

SelectionPrinciple = Literal["observation_led", "criteria_crossing"]
StrategyProfile = Literal[
    "area_only",
    "gauged_downstream_station",
]
CriterionMode = Literal["hard_reject", "warning", "score", "stratify", "report_only"]
ObservationRole = Literal["primary", "bonus", "score", "stratify", "report_only", "ignore"]
CandidateMode = Literal[
    "network_sampling",
    "station_outlets",
]
OutletSnapStrategy = Literal["dem_accumulation", "bdtopage_then_dem"]
ReferenceNetworkSource = Literal["bdtopage", "custom"]
RouteOverlapMode = Literal["hard_reject", "warning", "score", "report_only"]
SpatialQuotaMode = Literal["none", "grid"]
WorkflowInputMode = Literal[
    "dry_run",
    "hydrometry",
    "delineated_catchments",
    "dem_network_sampling",
    "dem_area_target",
]
MapContextLayerRole = Literal["territory", "hydrography", "geology", "other"]
InfluenceType = Literal[
    "major_dam_upstream",
    "major_withdrawal_upstream",
    "major_regulated_reach",
]
StationInfluenceUnknownPolicy = Literal["neutral", "warning"]


class StrategyConfig(HydroModelBase):
    """High-level strategy controlling candidate generation and criterion order."""

    principle: Annotated[SelectionPrinciple | None, Profile.USER] = Field(
        default=None,
        description=(
            "Effective selection principle, usually inferred from profile. "
            "'observation_led' loads the declared primary observation family "
            "first, creates candidate outlets from those records, delineates "
            "their basins, then applies criteria. 'criteria_crossing' starts "
            "from imported or DEM-derived candidate basins first; observations "
            "are evaluated only as criteria/evidence on that inventory."
        ),
    )
    profile: Annotated[StrategyProfile | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional workflow preset. 'area_only' selects basins primarily by "
            "area; 'gauged_downstream_station' selects catchments attached to "
            "flow stations. Hydrometry input infers "
            "'gauged_downstream_station' when the profile is omitted. Presets "
            "infer principle, primary observation type, primary axes and "
            "candidate mode when those fields are omitted."
        ),
    )
    primary_axes: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Physical or spatial axes that drive a criteria_crossing selection. "
            "Inferred as ['area'] when profile='area_only'."
        ),
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
        description=(
            "Effective observation family that defines candidate records for "
            "an observation_led strategy. Inferred as 'flow_station' when "
            "profile='gauged_downstream_station'."
        ),
    )
    candidate_mode: Annotated[CandidateMode | None, Profile.USER] = Field(
        default=None,
        description=(
            "Effective strategy-level outlet generation mode. Inferred as "
            "'station_outlets' for observation-led workflows that use already "
            "loaded observation/outlet point records; otherwise leave unset to "
            "use [site_selection.outlets].candidate_mode."
        ),
    )

    @model_validator(mode="after")
    def _validate_strategy(self) -> StrategyConfig:
        if self.profile == "gauged_downstream_station":
            if self.principle not in {None, "observation_led"}:
                raise ValueError(
                    "profile='gauged_downstream_station' requires principle='observation_led'."
                )
            if self.primary_observation_type not in {None, "flow_station"}:
                raise ValueError(
                    "profile='gauged_downstream_station' requires "
                    "primary_observation_type='flow_station'."
                )
            if self.candidate_mode not in {None, "station_outlets"}:
                raise ValueError(
                    "profile='gauged_downstream_station' requires candidate_mode='station_outlets'."
                )
            object.__setattr__(self, "principle", "observation_led")
            object.__setattr__(self, "primary_observation_type", "flow_station")
            object.__setattr__(self, "candidate_mode", "station_outlets")

        if self.profile == "area_only":
            if self.principle not in {None, "criteria_crossing"}:
                raise ValueError("profile='area_only' requires principle='criteria_crossing'.")
            axes = {axis.strip().lower() for axis in self.primary_axes}
            if self.primary_axes and axes != {"area"}:
                raise ValueError("profile='area_only' requires primary_axes = ['area'].")
            object.__setattr__(self, "principle", "criteria_crossing")
            object.__setattr__(self, "primary_axes", ["area"])
            if self.observation_role not in {"report_only", "ignore"}:
                raise ValueError("area_only requires observation_role='report_only' or 'ignore'.")
            if self.geology_role not in {"report_only", "ignore"}:
                raise ValueError("area_only requires geology_role='report_only' or 'ignore'.")

        if self.profile is None:
            return self

        return self


class TerritoryConfig(HydroModelBase):
    """Spatial domain where candidate basins are searched."""

    mode: Annotated[
        Literal[
            "admin_regions",
            "admin_departments",
            "polygon_file",
            "bbox",
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

    source: Annotated[
        Literal["custom", "data_manager", "ign_geoplateforme_dem"] | None,
        Profile.USER,
    ] = Field(
        default=None,
        description=(
            "Optional DEM resolver override. When omitted, site_selection uses "
            "site_selection.dem.path if provided, otherwise the HydroModPy data "
            "manager configured in [data.dem]. Explicit values are: 'custom' "
            "for site_selection.dem.path only, 'data_manager' for [data.dem], "
            "and 'ign_geoplateforme_dem' for the IGN Geoplateforme provider "
            "shortcut."
        ),
    )
    path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Local DEM file or directory when source='custom'. A directory with "
            "several TIF/TIFF/ASC tiles is mosaicked into a cached GeoTIFF."
        ),
    )
    resolution_m: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Effective DEM resolution in metres. For data-manager DEM sources, "
            "prefer data.dem.sources[].resolution_m; site-selection derives this "
            "value for manifests and reports. Keep this field only for custom "
            "DEM paths or provider shortcuts without [data.dem]."
        ),
    )
    cache_policy: Annotated[str, Profile.USER] = Field(
        default="use_cache_else_download",
        description="Data cache policy.",
    )
    delineation_buffer_km: Annotated[float, Profile.USER] = Field(
        default=0.0,
        ge=0,
        description=(
            "Buffer added to the DEM used for flow directions and basin "
            "delineation, in kilometres. With "
            "delineation_dem_extent_source='candidate_outlets_bbox', this expands "
            "the bounding box of candidate outlets; with "
            "delineation_dem_extent_source='selection_territory', it expands the "
            "configured selection territory."
        ),
    )
    delineation_dem_extent_source: Annotated[
        Literal["selection_territory", "candidate_outlets_bbox"],
        Profile.USER,
    ] = Field(
        default="selection_territory",
        description=(
            "Source used to build the extent of the DEM loaded for hydrologic "
            "calculations: flow direction, accumulation, outlet snapping, and "
            "catchment delineation. 'selection_territory' loads the DEM over "
            "the configured territory and is the safer option when upstream "
            "basins may extend far from outlets. 'candidate_outlets_bbox' "
            "loads only the bounding box of candidate or station outlets, "
            "expanded by delineation_buffer_km; this is faster for previews, "
            "but the buffer must be large enough to contain the upstream area "
            "needed for delineation."
        ),
    )
    review_map_dem_background: Annotated[
        Literal["none", "delineation_dem", "territory_dem"],
        Profile.USER,
    ] = Field(
        default="delineation_dem",
        description=(
            "DEM used as the HTML review-map background. 'delineation_dem' "
            "reuses the DEM used to calculate basin contours; 'territory_dem' "
            "loads a territory-scale DEM through [data.dem] without using it "
            "for delineation; 'none' disables the DEM map background."
        ),
    )
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Ignore existing cached data when supported by the provider.",
    )


class HydrologyConfig(HydroModelBase):
    """DEM-derived hydrologic products requested by the selection workflow."""

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
    compute_strahler: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Request Strahler diagnostics if existing spatial primitives support them.",
    )

    @property
    def dem_correction_type(self) -> Literal["fill", "breach"]:
        """Return the existing flow-products correction keyword."""

        if self.hydrologic_conditioning == "breach":
            return "breach"
        return "fill"


class DemAreaTargetConfig(HydroModelBase):
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
        description="Target number of basins selected by the DEM target-area workflow.",
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
    def _validate_area_window(self) -> DemAreaTargetConfig:
        if self.min_area_km2 > self.max_area_km2:
            raise ValueError("min_area_km2 must be <= max_area_km2.")
        if not (self.min_area_km2 <= self.target_area_km2 <= self.max_area_km2):
            raise ValueError("target_area_km2 must be inside [min_area_km2, max_area_km2].")
        return self


class OutletsConfig(HydroModelBase):
    """Candidate outlet construction settings."""

    candidate_mode: Annotated[CandidateMode, Profile.USER] = Field(
        default="network_sampling",
        description=(
            "Concrete outlet construction mode. 'station_outlets' uses already "
            "loaded observation/outlet point records; 'network_sampling' "
            "samples DEM-derived stream-network cells."
        ),
    )
    min_distance_between_outlets_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Minimum spacing used to thin candidate outlets before basin "
            "delineation. In station-led workflows, stations closer than this "
            "compete and only one outlet is kept."
        ),
    )
    allow_nested_basins: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Allow nested candidate basins before final selection.",
    )
    max_network_candidates: Annotated[int | None, Profile.USER] = Field(
        default=200,
        gt=0,
        description="Maximum number of DEM network candidates to delineate.",
    )
    max_rejected_network_candidate_audit_records: Annotated[int | None, Profile.USER] = Field(
        default=5000,
        gt=0,
        description=(
            "Maximum number of rejected DEM/network candidate cells written to the "
            "candidate audit JSONL."
        ),
    )
    max_dem_network_cells: Annotated[int | None, Profile.USER] = Field(
        default=50000,
        gt=0,
        description=(
            "Maximum number of DEM-derived stream cells exported to the DEM "
            "network vector layer. Highest-accumulation cells are kept first."
        ),
    )
    snap_to_dem_network: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Snap outlets to the DEM-derived stream network when applicable.",
    )
    snap_strategy: Annotated[OutletSnapStrategy, Profile.USER] = Field(
        default="dem_accumulation",
        description=(
            "Outlet snapping strategy. 'dem_accumulation' snaps directly on the "
            "DEM-derived accumulation raster. 'bdtopage_then_dem' first snaps "
            "the original station/candidate outlet to the reference network, "
            "then runs the local DEM snap."
        ),
    )
    dem_snap_max_distance_m: Annotated[int, Profile.USER] = Field(
        default=150,
        gt=0,
        description=(
            "Maximum distance, in metres, allowed for the final local snap on "
            "the DEM-derived accumulation raster. This snap is the point used "
            "for basin delineation and is separate from any preliminary "
            "reference-network snap."
        ),
    )
    reference_network_source: Annotated[ReferenceNetworkSource, Profile.USER] = Field(
        default="bdtopage",
        description=(
            "Reference hydrographic network used before the DEM snap when "
            "snap_strategy='bdtopage_then_dem'."
        ),
    )
    reference_network_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="Local vector network used when reference_network_source='custom'.",
    )
    reference_network_snap_max_distance_m: Annotated[float, Profile.USER] = Field(
        default=100.0,
        gt=0,
        description=(
            "Maximum distance, in metres, allowed between the original station "
            "or candidate outlet and the nearest reference-network line before "
            "snapping to that line. With snap_strategy='bdtopage_then_dem', "
            "candidates farther than this from BD Topage fail before the final "
            "DEM snap."
        ),
    )
    reference_network_fetch_margin_m: Annotated[float, Profile.DEV] = Field(
        default=500.0,
        ge=0,
        description=(
            "Extra margin, in metres, around candidate outlets when downloading "
            "the reference network. It only affects the download/search window, "
            "not the accepted snap distance."
        ),
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
        description=(
            "Allow the final selection to keep catchments that contain one "
            "another. When false, nested upstream/downstream basins compete "
            "during spatial thinning; when true, they can both be selected."
        ),
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
        description=(
            "Maximum allowed area overlap between two selected basins, expressed "
            "as a fraction of overlap_reference. Use 0.20 to allow up to 20% "
            "overlap; null disables this pairwise overlap check."
        ),
    )
    overlap_reference: Annotated[Literal["smaller_basin", "candidate", "selected"], Profile.USER] = (
        Field(
            default="smaller_basin",
            description=(
                "Area used as denominator for pairwise overlap fraction. "
                "'smaller_basin' measures the shared area relative to the "
                "smaller basin; 'candidate' or 'selected' use one side of the "
                "selection comparison."
            ),
        )
    )
    overlap_mode: Annotated[RouteOverlapMode, Profile.USER] = Field(
        default="hard_reject",
        description=(
            "How pairwise basin-overlap violations affect selection. "
            "'hard_reject' blocks the lower-ranked overlapping basin; 'warning' "
            "keeps it selected and records the overlap as a warning."
        ),
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
            raise ValueError("spatial_quota_mode='grid' requires spatial_quota_cell_size_km.")
        return self


class SiteSelectionInputConfig(HydroModelBase):
    """Execution input selector used by the ``site_selection`` workflow."""

    @model_validator(mode="before")
    @classmethod
    def _migrate_plan_only_mode(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if payload.get("mode") == "plan_only":
            payload["mode"] = "dry_run"
        return payload

    mode: Annotated[WorkflowInputMode, Profile.USER] = Field(
        default="dry_run",
        description=(
            "Execution path used by site_selection. 'dry_run' validates and "
            "documents the selection campaign without loading candidates, "
            "delineating basins or selecting/rejecting sites. 'hydrometry' loads "
            "observation stations from [hydrometry] and uses their outlets as "
            "candidates. 'delineated_catchments' reads an existing catchments_csv. "
            "'dem_area_target' runs the simplified DEM target-area search. "
            "'dem_network_sampling' runs lower-level DEM stream-network sampling. "
            "Legacy 'plan_only' input is accepted as an alias for 'dry_run'."
        ),
    )
    catchments_csv: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=("Pre-delineated catchments CSV used when mode='delineated_catchments'."),
    )
    region_id: Annotated[str, Profile.USER] = Field(
        default="",
        description=(
            "Optional output grouping label copied to regional-lab CSV and manifest "
            "outputs. When omitted, it is derived from a single administrative "
            "region or department in [site_selection.territory]. Set it only to "
            "override the exported label for multi-territory, bbox, polygon or "
            "custom campaigns. It does not constrain the search extent."
        ),
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
        description="Write site_selection_plan.json when the workflow is run in dry_run mode.",
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
                "area mode='hard_reject' requires at least one area range or a hard min/max area."
            )
        return self


class FlowStationCriteriaConfig(HydroModelBase):
    """Criteria applied to gauging-station record and location evidence."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "How gauging-station suitability affects the final decision. This "
            "criterion checks the available discharge record, the distance "
            "between the station and the final outlet, and optionally whether "
            "the station is inside the basin or at the outlet."
        ),
    )
    min_record_years: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Minimum required discharge-record length in years.",
    )
    max_station_to_outlet_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Maximum allowed distance between the gauging station and the final "
            "basin outlet."
        ),
    )
    require_station_inside_or_at_outlet: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Require the gauging station to be inside the delineated basin or "
            "at the final outlet."
        ),
    )


class StationInfluenceCriteriaConfig(HydroModelBase):
    """Criteria applied to flow-station hydrologic influence metadata."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "How flow-station hydrologic influence metadata affects the final "
            "decision."
        ),
    )
    source: Annotated[str, Profile.USER] = Field(
        default="hubeau_station_metadata",
        description=(
            "Metadata source used to evaluate station influence, for example "
            "Hub'Eau station metadata fields."
        ),
    )
    warn_if_general_influence: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Flag Hub'Eau general site influence metadata, such as site-scale "
            "hydrologic alteration, when it is present."
        ),
    )
    warn_if_local_influence: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Flag Hub'Eau local station influence metadata, such as local "
            "hydraulic alteration near the station, when it is present."
        ),
    )
    warn_if_comment_keyword: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Report comment keyword matches as warnings. Comment keywords are "
            "not treated as hard-reject evidence."
        ),
    )
    unknown_policy: Annotated[StationInfluenceUnknownPolicy, Profile.USER] = Field(
        default="neutral",
        description=(
            "How missing or unknown station influence metadata is handled. "
            "'neutral' keeps it from blocking by itself; 'warning' records a "
            "review warning."
        ),
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
        description=(
            "Keywords searched in station comments to flag possible hydraulic "
            "influence for review."
        ),
    )


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

    flow_station_mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "Default mode for gauging-station suitability checks when the "
            "detailed flow_station block does not override it."
        ),
    )
    flow_station_max_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Default maximum distance between gauging stations and final basin "
            "outlets."
        ),
    )
    piezometer_mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description="Default mode for piezometer observation checks.",
    )
    piezometer_max_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Maximum distance used when matching piezometers to basins or outlets.",
    )
    flow_station: Annotated[FlowStationCriteriaConfig, Profile.USER] = Field(
        default_factory=FlowStationCriteriaConfig,
        description=(
            "Detailed gauging-station suitability settings. The TOML key stays "
            "'flow_station' because it is also the internal observation-family "
            "identifier."
        ),
    )
    station_influence: Annotated[StationInfluenceCriteriaConfig, Profile.USER] = Field(
        default_factory=StationInfluenceCriteriaConfig,
        description="Station metadata influence criterion settings.",
    )
    piezometer_layers: Annotated[list[PiezometerLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional vector layers used to compute piezometer evidence.",
    )


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

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description="How anthropic influence evidence affects the final decision.",
    )
    reject_major_dam_upstream: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Reject sites when evidence reports a major upstream dam.",
    )
    reject_major_withdrawal_upstream: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Reject sites when evidence reports a major upstream withdrawal.",
    )
    reject_major_regulated_reach: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Reject sites when evidence reports a major regulated reach.",
    )
    influence_search_radius_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Optional search radius in kilometres for influence layers.",
    )
    layers: Annotated[list[InfluenceLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional vector layers used to compute influence flags automatically.",
    )


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

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description="How geology evidence affects the final decision.",
    )
    prefer_diversity: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Prefer or highlight basins with more diverse geology classes.",
    )
    layers: Annotated[list[GeologyLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional polygon layers used to compute geology evidence.",
    )


class CriteriaConfig(HydroModelBase):
    """Selection criteria and audit-facing criterion-mode lists."""

    ruleset: Annotated[str, Profile.USER] = Field(
        default="",
        description=(
            "Optional stable name of the criterion set used for audit outputs. "
            "When omitted, site_selection derives it from selection_id."
        ),
    )
    hard_reject: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Blocking criteria: when one fails, the candidate is not retained. "
            "Keep 'delineation_failure' here to document that a basin that "
            "cannot be delineated is unusable."
        ),
    )
    warning: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Review warnings: the candidate can still be selected, but the "
            "issue is highlighted in the site-selection report for expert "
            "review before final acceptance."
        ),
    )
    ranking_preference: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Preference criteria used to rank otherwise acceptable candidates "
            "without rejecting them directly."
        ),
    )
    report_only: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Context-only evidence exported for human review or audit, without "
            "automatic decision impact."
        ),
    )
    area: Annotated[AreaCriteriaConfig, Profile.USER] = Field(
        default_factory=AreaCriteriaConfig,
        description="Area criterion settings.",
    )
    observations: Annotated[ObservationsCriteriaConfig, Profile.USER] = Field(
        default_factory=ObservationsCriteriaConfig,
        description="Observation criterion settings.",
    )
    influence: Annotated[InfluenceCriteriaConfig, Profile.USER] = Field(
        default_factory=InfluenceCriteriaConfig,
        description="Anthropic influence criterion settings.",
    )
    geology: Annotated[GeologyCriteriaConfig, Profile.USER] = Field(
        default_factory=GeologyCriteriaConfig,
        description="Geology criterion settings.",
    )

    @model_validator(mode="after")
    def _validate_disjoint_mode_lists(self) -> CriteriaConfig:
        seen: dict[str, str] = {}
        for family, values in (
            ("hard_reject", self.hard_reject),
            ("warning", self.warning),
            ("ranking_preference", self.ranking_preference),
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

    write_rejected: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write rejected site tables and spatial layers.",
    )
    write_selected: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write selected site tables and spatial layers.",
    )
    write_geojson: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write GeoJSON spatial outputs for outlets, basins and observations.",
    )
    write_geoparquet: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Write GeoParquet spatial outputs when supported.",
    )
    write_geopackage: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Write a GeoPackage with site-selection spatial layers.",
    )
    write_csv: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write selected, rejected and decision CSV tables.",
    )
    write_regional_lab_csv: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write regional_lab_sites.csv for downstream regional-lab workflows.",
    )
    keep_intermediate_rasters: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Keep intermediate GeoTIFF rasters such as flow products and "
            "per-candidate watershed masks after final outputs are written."
        ),
    )


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
    _report_html_build_at_end: bool = PrivateAttr(default=False)

    @property
    def report_html_build_at_end(self) -> bool:
        """Whether the generic [report.html] contract requests final HTML output."""

        return self._report_html_build_at_end

    def with_report_html_build_at_end(self, requested: bool) -> SiteSelectionConfig:
        """Return a copy carrying workflow-local HTML report intent."""

        clone = self.model_copy()
        object.__setattr__(clone, "_report_html_build_at_end", bool(requested))
        return clone

    selection_id: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description=(
            "Stable campaign identifier copied to manifests, decision exports, "
            "and downstream regional-lab/testbed hand-offs."
        ),
    )
    output_root: Annotated[Path, Profile.USER] = Field(
        ...,
        description=(
            "Directory where site-selection artifacts are written, resolved "
            "relative to the TOML file when a relative path is provided. Contains "
            "manifests, decision tables, spatial layers, reports, and optional "
            "intermediate files."
        ),
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
    dem: Annotated[DemConfig, Profile.USER] = Field(
        default_factory=DemConfig,
        description="DEM source requested by site selection.",
    )
    hydrology: Annotated[HydrologyConfig, Profile.USER] = Field(
        default_factory=HydrologyConfig,
        description="DEM-derived hydrologic products requested by the selection workflow.",
    )
    dem_area_target: Annotated[DemAreaTargetConfig | None, Profile.USER] = Field(
        default=None,
        description="Compact settings for DEM-only automatic small-basin selection.",
    )
    input: Annotated[SiteSelectionInputConfig, Profile.USER] = Field(
        default_factory=SiteSelectionInputConfig,
        description="Execution input selector used by the site-selection workflow.",
    )
    outlets: Annotated[OutletsConfig, Profile.USER] = Field(
        default_factory=OutletsConfig,
        description="Candidate outlet generation settings.",
    )
    spatial_selection: Annotated[SpatialSelectionConfig, Profile.USER] = Field(
        default_factory=SpatialSelectionConfig,
        description="Spatial thinning and overlap policy.",
    )
    criteria: Annotated[CriteriaConfig, Profile.USER] = Field(
        default_factory=CriteriaConfig,
        description="Selection criteria and criterion-mode lists.",
    )
    output: Annotated[OutputConfig, Profile.USER] = Field(
        default_factory=OutputConfig,
        description="Output artifact switches.",
    )
    map_context: Annotated[MapContextConfig, Profile.USER] = Field(
        default_factory=MapContextConfig,
        description="Optional static context layers for review figures.",
    )
    @property
    def resolved_region_id(self) -> str:
        """Return the output grouping label after territory-based inference."""

        return self.input.region_id or self._region_id_from_territory()

    def _region_id_from_territory(self) -> str:
        if self.territory.mode == "admin_regions" and len(self.territory.regions) == 1:
            return self.territory.regions[0]
        if (
            self.territory.mode == "admin_departments"
            and len(self.territory.departments) == 1
        ):
            return self.territory.departments[0]
        return ""

    @model_validator(mode="before")
    @classmethod
    def _migrate_review_map_dem_background(cls, data: object) -> object:
        """Move legacy [site_selection.review_map] into [site_selection.dem]."""

        if not isinstance(data, dict):
            return data
        payload = dict(data)
        review_map = payload.pop("review_map", None)
        if not isinstance(review_map, dict) or "dem_background" not in review_map:
            return payload

        dem_payload = dict(payload.get("dem") or {})
        legacy_value = review_map["dem_background"]
        current_value = dem_payload.get("review_map_dem_background")
        if current_value is not None and current_value != legacy_value:
            raise ValueError(
                "Use site_selection.dem.review_map_dem_background; it conflicts "
                "with legacy site_selection.review_map.dem_background."
            )
        dem_payload["review_map_dem_background"] = legacy_value
        payload["dem"] = dem_payload
        return payload

    @model_validator(mode="after")
    def _validate_selection_config(self) -> SiteSelectionConfig:
        criteria_ruleset = self.criteria.ruleset.strip()
        if criteria_ruleset != self.criteria.ruleset:
            object.__setattr__(
                self,
                "criteria",
                self.criteria.model_copy(update={"ruleset": criteria_ruleset}),
            )
        if not criteria_ruleset:
            object.__setattr__(
                self,
                "criteria",
                self.criteria.model_copy(update={"ruleset": self.selection_id}),
            )

        input_region_id = self.input.region_id.strip()
        if input_region_id != self.input.region_id:
            object.__setattr__(
                self,
                "input",
                self.input.model_copy(update={"region_id": input_region_id}),
            )
        if not input_region_id:
            inferred_region_id = self._region_id_from_territory()
            if inferred_region_id:
                object.__setattr__(
                    self,
                    "input",
                    self.input.model_copy(update={"region_id": inferred_region_id}),
                )

        if self.input.mode == "hydrometry":
            if self.strategy.profile not in {None, "gauged_downstream_station"}:
                raise ValueError(
                    "site_selection.input.mode='hydrometry' requires "
                    "strategy.profile='gauged_downstream_station' when a profile "
                    "is set."
                )
            if self.strategy.principle not in {None, "observation_led"}:
                raise ValueError(
                    "site_selection.input.mode='hydrometry' requires "
                    "strategy.principle='observation_led' when principle is set."
                )
            if self.strategy.primary_observation_type not in {None, "flow_station"}:
                raise ValueError(
                    "site_selection.input.mode='hydrometry' requires "
                    "primary_observation_type='flow_station' when set."
                )
            if self.strategy.candidate_mode not in {None, "station_outlets"}:
                raise ValueError(
                    "site_selection.input.mode='hydrometry' requires "
                    "candidate_mode='station_outlets' when set."
                )
            if self.strategy.profile is None:
                inferred_strategy = StrategyConfig.model_validate(
                    self.strategy.model_dump()
                    | {
                        "profile": "gauged_downstream_station",
                        "principle": "observation_led",
                        "primary_observation_type": "flow_station",
                        "candidate_mode": "station_outlets",
                    }
                )
                object.__setattr__(self, "strategy", inferred_strategy)
        elif self.strategy.profile is None:
            if self.strategy.principle == "observation_led":
                raise ValueError(
                    "observation_led requires profile='gauged_downstream_station' "
                    "or site_selection.input.mode='hydrometry'."
                )
            if self.strategy.principle is None:
                object.__setattr__(
                    self,
                    "strategy",
                    self.strategy.model_copy(update={"principle": "criteria_crossing"}),
                )

        if self.strategy.principle == "observation_led":
            outlet_mode_was_set = "candidate_mode" in self.outlets.model_fields_set
            if outlet_mode_was_set and self.outlets.candidate_mode != "station_outlets":
                raise ValueError(
                    "observation_led requires candidate_mode='station_outlets' "
                    "in strategy or outlets."
                )
            if not outlet_mode_was_set and self.outlets.candidate_mode != "station_outlets":
                object.__setattr__(
                    self,
                    "outlets",
                    self.outlets.model_copy(update={"candidate_mode": "station_outlets"}),
                )

        if self.input.mode == "dem_area_target":
            if self.strategy.profile != "area_only":
                raise ValueError(
                    "site_selection.input.mode='dem_area_target' requires "
                    "strategy.profile='area_only'."
                )
            if self.dem_area_target is None:
                object.__setattr__(self, "dem_area_target", DemAreaTargetConfig())

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
            if self.strategy.primary_observation_type != "flow_station":
                raise ValueError(
                    "profile='gauged_downstream_station' requires "
                    "primary_observation_type='flow_station'."
                )

        return self

    @property
    def effective_profile(self) -> str:
        """Return the explicit selection profile."""

        if self.strategy.profile:
            return self.strategy.profile
        return "custom"


__all__ = [
    "AreaCriteriaConfig",
    "AreaRangeConfig",
    "CandidateMode",
    "CriteriaConfig",
    "CriterionMode",
    "DemAreaTargetConfig",
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
