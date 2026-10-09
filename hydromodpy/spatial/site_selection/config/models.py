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
from hydromodpy.core.config_kit.visible_when import VisibleWhen

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

_CANDIDATE_MODE_VALUE_DOCS = {
    "network_sampling": "Generates candidate outlets by sampling the DEM-derived stream network.",
    "station_outlets": (
        "Uses imported observation station locations, such as flow stations, as candidate outlets."
    ),
}


def _criterion_mode_value_docs(subject: str, *, score_hint: str) -> dict[str, str]:
    """Build value_docs for a fully-implemented CriterionMode field.

    ``subject`` names the evidence checked (for example 'basin area'). Used for
    modes whose evaluator implements all five branches with real effect.
    """

    return {
        "hard_reject": f"Rejects candidates that fail the configured {subject} check.",
        "warning": (
            f"Flags candidates that fail the configured {subject} check, without rejecting them."
        ),
        "score": f"Scores candidates by {score_hint}.",
        "stratify": f"Makes {subject} available for grouping candidates into strata.",
        "report_only": (
            f"Records {subject} evidence without any automatic accept or reject decision."
        ),
    }


_OBSERVATION_ROLE_VALUE_DOCS = {
    "primary": "Accepted and recorded in the manifest; no code reads it, so a run is unchanged.",
    "bonus": "Accepted and recorded in the manifest; no code reads it, so a run is unchanged.",
    "score": "Accepted and recorded in the manifest; no code reads it, so a run is unchanged.",
    "stratify": "Accepted and recorded in the manifest; no code reads it, so a run is unchanged.",
    "report_only": ("Recorded but never read; one of the two values profile='area_only' accepts."),
    "ignore": "Recorded but never read; the other value profile='area_only' accepts.",
}


class StrategyConfig(HydroModelBase):
    """High-level strategy controlling candidate generation and criterion order."""

    principle: Annotated[SelectionPrinciple, Profile.USER] = Field(
        default="criteria_crossing",
        description="Selection principle: observation-led or direct criteria crossing.",
        json_schema_extra={
            "value_docs": {
                "observation_led": (
                    "Builds candidates from imported observation outlets, such as flow stations."
                ),
                "criteria_crossing": (
                    "Crosses the declared spatial and physical criteria directly, with "
                    "no observation-led outlets."
                ),
            }
        },
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
        json_schema_extra={"value_docs": _OBSERVATION_ROLE_VALUE_DOCS},
    )
    geology_role: Annotated[ObservationRole, Profile.USER] = Field(
        default="report_only",
        description="How geology influences a criteria_crossing campaign.",
        json_schema_extra={"value_docs": _OBSERVATION_ROLE_VALUE_DOCS},
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
        description=(
            "Candidate mode written to the manifest and the report in place of "
            "outlets.candidate_mode. Candidate generation itself reads outlets.candidate_mode."
        ),
        json_schema_extra={"value_docs": _CANDIDATE_MODE_VALUE_DOCS},
    )

    @model_validator(mode="after")
    def _validate_strategy(self) -> StrategyConfig:
        if self.principle == "observation_led":
            if not self.primary_observation_type:
                raise ValueError(
                    "observation_led requires primary_observation_type "
                    "(for example 'flow_station')."
                )
            if self.profile != "gauged_downstream_station":
                raise ValueError("observation_led requires profile='gauged_downstream_station'.")

        if self.profile == "gauged_downstream_station":
            if self.principle != "observation_led":
                raise ValueError(
                    "profile='gauged_downstream_station' requires principle='observation_led'."
                )
            if self.primary_observation_type != "flow_station":
                raise ValueError(
                    "profile='gauged_downstream_station' requires "
                    "primary_observation_type='flow_station'."
                )
            if self.candidate_mode not in {None, "station_outlets"}:
                raise ValueError(
                    "profile='gauged_downstream_station' requires candidate_mode='station_outlets'."
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
        ],
        Profile.USER,
    ] = Field(
        default="bbox",
        description=(
            "How the search territory is given: by administrative regions, by departments, "
            "by a polygon file or by a bounding box. Each mode reads its own key."
        ),
        json_schema_extra={
            "value_docs": {
                "admin_regions": (
                    "Bounds the territory to the bounding box of the named administrative regions."
                ),
                "admin_departments": (
                    "Bounds the territory to the bounding box of the named departments."
                ),
                "polygon_file": (
                    "Bounds the territory to the bounding box of a user-supplied polygon file."
                ),
                "bbox": "Bounds the territory to an explicit xmin, ymin, xmax, ymax box.",
            }
        },
    )
    country: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Country code used by administrative territory modes.",
    )
    regions: Annotated[list[str], Profile.USER, VisibleWhen("mode", "admin_regions")] = Field(
        default_factory=list,
        description=(
            "Names of the administrative regions that bound the territory. With "
            "country = 'FR' the names are checked against the French regions."
        ),
        examples=[["Bretagne"]],
    )
    departments: Annotated[list[str], Profile.USER, VisibleWhen("mode", "admin_departments")] = (
        Field(
            default_factory=list,
            description="Codes of the administrative departments that bound the territory.",
            examples=[["35", "56"]],
        )
    )
    polygon_file: Annotated[Path | None, Profile.USER, VisibleWhen("mode", "polygon_file")] = Field(
        default=None,
        description="Vector file of a polygon whose bounding box is the territory.",
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
            "Where the selection takes its DEM when dem.path is empty and the file holds "
            "no [data.dem] section. A dem.path or a [data.dem] section always wins."
        ),
        json_schema_extra={
            "value_docs": {
                "custom": "Takes no DEM of its own: dem.path or [data.dem] must give one.",
                "data": "Takes no DEM of its own: the [data.dem] section of the file gives it.",
                "ign_geoplateforme_dem": (
                    "Requests the IGN Geoplateforme DEM over the territory when neither "
                    "dem.path nor [data.dem] gives one."
                ),
            }
        },
    )
    path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Local DEM raster used to delineate the catchments. When set, it wins over "
            "[data.dem] and over source."
        ),
    )
    resolution_m: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Resolution of the DEM, in metres. It is written to the selection manifest "
            "only: no step resamples the DEM to it."
        ),
    )
    cache_policy: Annotated[str, Profile.USER] = Field(
        default="use_cache_else_download",
        description=(
            "Cache policy label written to the selection manifest and report. No step "
            "reads it: force_refresh is what bypasses the cache."
        ),
    )
    margin_km: Annotated[float, Profile.USER] = Field(
        default=0.0,
        ge=0,
        description="DEM request margin around the territory in kilometres.",
    )
    request_extent: Annotated[Literal["territory", "outlets"], Profile.USER] = Field(
        default="territory",
        description=(
            "Area the DEM is requested over through [data.dem]. "
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
        json_schema_extra={
            "value_docs": {
                "none": "Skips loading any DEM background for the review map.",
                "delineation": (
                    "Reuses the DEM already used to delineate basin contours as background."
                ),
                "territory": (
                    "Loads a separate regional DEM over the full territory for the background."
                ),
            }
        },
    )
    force_refresh: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Ignore existing cached data when supported by the provider.",
    )


class HydrologyConfig(HydroModelBase):
    """DEM-derived hydrologic products requested by the selection workflow."""

    method: Annotated[Literal["dem_only"], Profile.USER] = Field(
        default="dem_only",
        description=(
            "How the flow products (directions, accumulation, streams) are made. "
            "'dem_only' derives them from the DEM alone and is the only value today."
        ),
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
        json_schema_extra={
            "value_docs": {
                "existing_default": (
                    "Forwards 'fill' to the flow products; it is the site-selection default."
                ),
                "fill": "Raises each depression to its spill elevation before routing flow.",
                "breach": (
                    "Carves a channel through each depression, preserving natural flow paths."
                ),
            }
        },
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
        description="Smallest upstream area, in km2, a DEM-only candidate basin may have.",
    )
    max_area_km2: Annotated[float, Profile.USER] = Field(
        default=125.0,
        gt=0,
        description="Largest upstream area, in km2, a DEM-only candidate basin may have.",
    )
    n_basins: Annotated[int, Profile.USER] = Field(
        default=50,
        gt=0,
        description=(
            "Number of basins the DEM-only selection keeps. It replaces "
            "spatial_selection.max_selected_sites in that selection. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    max_candidates_before_delineation: Annotated[int | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Most candidate outlets delineated before the final selection. A lower value "
            "runs faster but can leave fewer accepted basins after spatial filtering. "
            "Unset, it is 20 times n_basins. A count."
        ),
        json_schema_extra={"unit": "-"},
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
        description=(
            "How candidate outlets are generated: sampled on the DEM stream network, or "
            "taken at the observation stations."
        ),
        json_schema_extra={"value_docs": _CANDIDATE_MODE_VALUE_DOCS},
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


class SiteSelectionInputConfig(HydroModelBase):
    """Execution input selector used by the ``site_selection`` workflow."""

    mode: Annotated[WorkflowInputMode, Profile.USER] = Field(
        default="plan_only",
        description=(
            "Where the candidate catchments come from: no data (a plan only), flow "
            "stations, a CSV of delineated catchments, outlets sampled on the DEM "
            "network, or DEM-only outlets around a target area."
        ),
        json_schema_extra={
            "value_docs": {
                "plan_only": (
                    "Writes the selection-plan manifest and report, loading no data and "
                    "delineating nothing."
                ),
                "hydrometry": (
                    "Loads flow stations through HydroModPy data managers, then delineates "
                    "their catchments."
                ),
                "delineated_catchments": (
                    "Reuses pre-delineated catchments and outlets supplied as catchments_csv."
                ),
                "generated_candidates": (
                    "Samples high-accumulation DEM/network cells to generate candidate outlets."
                ),
                "dem_area_light": (
                    "Generates DEM-only candidate outlets around a target upstream drainage area."
                ),
            }
        },
    )
    catchments_csv: Annotated[
        Path | None, Profile.USER, VisibleWhen("mode", "delineated_catchments")
    ] = Field(
        default=None,
        description="CSV file of catchments already delineated, one row per catchment.",
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
        description="Label of the area range shown in the report and the CSV outputs.",
    )
    min_area_km2: Annotated[float, Profile.USER] = Field(
        ...,
        gt=0,
        description="Smallest basin area of this range, in km2.",
        examples=[10.0],
    )
    max_area_km2: Annotated[float, Profile.USER] = Field(
        ...,
        gt=0,
        description="Largest basin area of this range, in km2.",
        examples=[50.0],
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
        json_schema_extra={
            "value_docs": _criterion_mode_value_docs(
                "basin area",
                score_hint="closeness of their area to preferred_area_km2",
            )
        },
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
        description=(
            "Half-width of the area score, as a share of preferred_area_km2. The score "
            "is 1 at the preferred area and falls to 0 at that distance from it. "
            "Required by mode = 'score'."
        ),
        json_schema_extra={"unit": "-"},
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
    """Criteria applied to flow stations in observation-led selections."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "What the flow-station checks do to a candidate: reject it, warn, score it, "
            "group it, or only report. Left at 'report_only', "
            "observations.flow_station_mode decides instead."
        ),
        json_schema_extra={
            "value_docs": _criterion_mode_value_docs(
                "flow-station",
                score_hint="record length and station-to-outlet distance",
            )
        },
    )
    min_record_years: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Shortest discharge record, in years, a station must hold. A record given as "
            "a count of daily values is divided by 365.25. Unset, record length is not checked."
        ),
        json_schema_extra={"unit": "year"},
    )
    max_station_to_outlet_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Largest distance, in km, between the station and the candidate outlet. "
            "Unset, observations.flow_station_max_distance_km applies."
        ),
    )
    require_station_inside_or_at_outlet: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Fail the check when the station is flagged outside the basin and away from its outlet."
        ),
    )


class StationInfluenceCriteriaConfig(HydroModelBase):
    """Criteria applied to station influence metadata."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "What a station flagged as influenced (a dam, a withdrawal) does to its "
            "candidate: reject it, warn, score it, group it, or only report."
        ),
        json_schema_extra={
            "value_docs": _criterion_mode_value_docs(
                "station-influence",
                score_hint="influence status: 1.0 if none, 0.5 if unknown, 0.0 if influenced",
            )
        },
    )
    source: Annotated[str, Profile.USER] = Field(
        default="hubeau_station_metadata",
        description=(
            "Name of the metadata source written into the station-influence evidence. "
            "It is a label and selects no provider."
        ),
    )
    warn_if_general_influence: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Raise an issue when the station metadata reports a general hydrologic "
            "influence. Under mode = 'hard_reject' the issue rejects the candidate."
        ),
    )
    warn_if_local_influence: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Raise an issue when the station metadata reports a local hydrologic "
            "influence. Under mode = 'hard_reject' the issue rejects the candidate."
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
        description="What a station with missing or unknown influence metadata raises.",
        json_schema_extra={
            "value_docs": {
                "neutral": (
                    "Does not raise a warning when station influence metadata is missing "
                    "or unknown."
                ),
                "warning": (
                    "Raises a warning when station influence metadata is missing or unknown."
                ),
            }
        },
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


class PiezometerLayerConfig(HydroModelBase):
    """Vector layer used to compute piezometer evidence."""

    name: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Name of the piezometer layer, written into the evidence of each match.",
        examples=["ades_piezometers"],
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description="Vector file of the piezometer points matched against each basin.",
        examples=["piezometers.gpkg"],
    )
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribute column that names each piezometer. Unset, the row number is used.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Attribute column that labels each piezometer in the evidence. Unset, the "
            "identifier is used."
        ),
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
            "Mode of the flow-station checks, read only while flow_station.mode stays "
            "'report_only'. flow_station.mode wins when it is set to another value."
        ),
        json_schema_extra={
            "value_docs": _criterion_mode_value_docs(
                "flow-station",
                score_hint="record length and station-to-outlet distance",
            )
        },
    )
    flow_station_max_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Largest distance, in km, between the flow station and the candidate outlet. "
            "flow_station.max_station_to_outlet_distance_km wins when it is set."
        ),
    )
    piezometer_mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "What the piezometer checks do to a candidate: reject it, warn, score it, "
            "group it, or only report."
        ),
        json_schema_extra={
            "value_docs": _criterion_mode_value_docs(
                "piezometer",
                score_hint="distance to the nearest piezometer, or piezometer count",
            )
        },
    )
    piezometer_max_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Largest distance, in km, from the basin to its nearest piezometer. Under "
            "mode = 'score' the score falls from 1 at the basin to 0 at this distance."
        ),
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


class InfluenceLayerConfig(HydroModelBase):
    """Vector layer used to compute anthropic-influence evidence."""

    name: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Name of the influence layer, written into the evidence of each match.",
        examples=["dams"],
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description=(
            "Vector file of the influence features (dams, withdrawals, regulated reaches) "
            "matched against each basin."
        ),
        examples=["dams.gpkg"],
    )
    influence_type: Annotated[InfluenceType, Profile.USER] = Field(
        ...,
        description="Normalized influence flag filled when features match a basin.",
        examples=["major_dam_upstream"],
        json_schema_extra={
            "value_docs": {
                "major_dam_upstream": (
                    "Marks matching basins as having a major dam upstream of the outlet."
                ),
                "major_withdrawal_upstream": (
                    "Marks matching basins as having a major water withdrawal upstream."
                ),
                "major_regulated_reach": (
                    "Marks matching basins as having a major regulated reach upstream."
                ),
            }
        },
    )
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribute column that names each feature. Unset, the row number is used.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Attribute column that labels each feature in the evidence. Unset, the "
            "identifier is used."
        ),
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
        description=(
            "What a basin carrying an influence flag selected by the reject_* keys does "
            "to its candidate: reject it, warn, or only report."
        ),
        json_schema_extra={
            "value_docs": {
                "hard_reject": (
                    "Rejects a candidate when a configured influence rejection flag is present."
                ),
                "warning": (
                    "Flags a configured influence flag as a warning without rejecting "
                    "the candidate."
                ),
                "score": ("Behaves like warning here: flags influence without computing a score."),
                "stratify": (
                    "Behaves like warning here: flags influence without grouping by class."
                ),
                "report_only": (
                    "Records influence evidence without any automatic accept or reject decision."
                ),
            }
        },
    )
    reject_major_dam_upstream: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Count a major dam upstream of the outlet as a failure of the influence check. "
            "What a failure does follows mode."
        ),
    )
    reject_major_withdrawal_upstream: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Count a major water withdrawal upstream of the outlet as a failure of the "
            "influence check. What a failure does follows mode."
        ),
    )
    reject_major_regulated_reach: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Count a major regulated reach upstream of the outlet as a failure of the "
            "influence check. What a failure does follows mode."
        ),
    )
    influence_search_radius_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Radius, in km, of the disk around the outlet searched for influence features "
            "when a candidate has no basin polygon. Unset, such a candidate gets no evidence."
        ),
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
        description="Name of the geology layer, written into the evidence of each match.",
        examples=["brgm_1m"],
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description="Vector polygon file containing geology units.",
        examples=["geology.gpkg"],
    )
    class_field: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Feature field containing the geology class.",
        examples=["lithology"],
    )
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribute column that names each polygon. Unset, the row number is used.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribute column that labels each polygon in the evidence.",
    )


class GeologyCriteriaConfig(HydroModelBase):
    """Geology criterion configuration."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "What the geology class of a basin does to its candidate: score it, group "
            "it, or only report. Geology cannot reject or warn today."
        ),
        json_schema_extra={
            "value_docs": {
                "hard_reject": (
                    "Behaves like report_only here: geology cannot yet reject a candidate."
                ),
                "warning": ("Behaves like report_only here: geology cannot yet raise a warning."),
                "score": "Gives a full score when a geology class is found, none otherwise.",
                "stratify": (
                    "Makes the geology class available for grouping candidates into strata."
                ),
                "report_only": (
                    "Records geology evidence without any automatic accept or reject decision."
                ),
            }
        },
    )
    prefer_diversity: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Records a wish for geologically diverse sites in the evidence. No step "
            "reads it yet, so the selection is the same either way."
        ),
    )
    layers: Annotated[list[GeologyLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional polygon layers used to compute geology evidence.",
    )


class CriteriaConfig(HydroModelBase):
    """Versioned criteria set and criterion-mode lists."""

    ruleset: Annotated[str, Profile.USER] = Field(
        default="site_selection_v1",
        description="Name of the criteria set, written to the selection manifest and report.",
    )
    hard_reject: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Criteria named as hard rejections in the manifest and report. The list is "
            "recorded; each criterion's own mode makes the decision. A name may sit in "
            "one list only."
        ),
    )
    warning: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Criteria named as warnings in the manifest and report. The list is recorded; "
            "each criterion's own mode makes the decision."
        ),
    )
    soft_score: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Criteria named as scores in the manifest and report. The list is recorded; "
            "each criterion's own mode makes the decision."
        ),
    )
    report_only: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Criteria named as reported only in the manifest and report. The list is "
            "recorded; each criterion's own mode makes the decision."
        ),
    )
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

    write_rejected: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write rejected_sites.csv, the table of rejected sites.",
    )
    write_selected: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write selected_sites.csv, the table of selected sites.",
    )
    write_geojson: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write the outlets and basins of the selected and rejected sites as GeoJSON.",
    )
    write_geoparquet: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Write the outlets and basins of the selected and rejected sites as GeoParquet.",
    )
    write_geopackage: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Write the outlets and basins of the selected and rejected sites as one GeoPackage.",
    )
    write_csv: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Write the site tables as CSV. When false, write_selected and write_rejected "
            "write nothing."
        ),
    )
    write_regional_lab_csv: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Write regional_lab_sites.csv: the selected sites in the columns the "
            "regional-lab catalog loader reads."
        ),
    )
    write_report_html: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Write the HTML review report with its maps and tables.",
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
        examples=["rivers"],
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description="GeoJSON file used as static map context.",
        examples=["rivers.geojson"],
    )
    role: Annotated[MapContextLayerRole, Profile.USER] = Field(
        default="other",
        description="Visual role controlling the default map style.",
        json_schema_extra={
            "value_docs": {
                "territory": "Drawn as a dashed grey outline, styled as the territory boundary.",
                "hydrography": "Drawn as thin blue lines, styled as the stream network.",
                "geology": "Drawn as pale yellow polygons, styled as geology units.",
                "other": "Drawn as neutral grey polygons and lines with no special role.",
            }
        },
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
        examples=["small_basins"],
    )
    output_root: Annotated[Path, Profile.USER] = Field(
        ...,
        description="Output directory for all site-selection artifacts.",
        examples=["site_selection"],
    )
    random_seed: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description=(
            "Seed for a random draw. No step of the selection draws a random number "
            "today, so a run is the same with or without it."
        ),
        json_schema_extra={"unit": "-"},
    )
    terrain_engine: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Flow-routing engine that conditions the DEM and delineates candidate "
            "catchments. Unset uses the engine this build defaults to. A string and "
            "not an enumeration, mirroring geographic.terrain_engine: the values that "
            "resolve depend on what is installed beside HydroModPy."
        ),
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

    @field_validator("terrain_engine")
    @classmethod
    def _check_terrain_engine_resolves(cls, value: str | None) -> str | None:
        """Refuse an engine this installation cannot serve, while reading the document.

        Mirror of ``GeographicConfig._check_terrain_engine_resolves``. ``None`` is
        not checked: it means "whatever this build defaults to".
        """
        if value is None:
            return value
        from hydromodpy.spatial.terrain import registry as terrain_registry

        if terrain_registry.is_registered(value):
            return value
        served = ", ".join(terrain_registry.list_engine_ids()) or "none"
        raise ValueError(
            f"site_selection.terrain_engine names {value!r}, and this installation serves "
            f"{served}. A third-party engine joins that list through the "
            f"{terrain_registry.ENTRY_POINT_GROUP!r} entry-point group, without a patch to "
            "HydroModPy."
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

        if self.input.mode == "dem_area_light":
            if self.strategy.profile != "area_only":
                raise ValueError(
                    "site_selection.input.mode='dem_area_light' requires "
                    "strategy.profile='area_only'."
                )
            if self.dem_area_light is None:
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
