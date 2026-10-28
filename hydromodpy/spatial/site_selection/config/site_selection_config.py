"""Configuration models for the site-selection workflow.

The models in this module describe the selection strategy and its criteria.
They deliberately do not implement hydrologic algorithms. Hydrologic rasters and
catchment delineation are delegated to existing ``hydromodpy.spatial`` modules.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.spatial.site_selection.config.criteria_config import CriteriaConfig
from hydromodpy.spatial.site_selection.config.dem_config import (
    DemAreaLightConfig,
    DemConfig,
    HydrologyConfig,
)
from hydromodpy.spatial.site_selection.config.outlets_config import (
    OutletsConfig,
    SpatialSelectionConfig,
)
from hydromodpy.spatial.site_selection.config.strategy_config import StrategyConfig, TerritoryConfig
from hydromodpy.spatial.site_selection.config.value_types import (
    MapContextLayerRole,
    WorkflowInputMode,
)


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
        description=(
            "Optional campaign or administrative region identifier. It is written in the "
            "region_id column of the selected-sites table and layers, and shown as Region "
            "in the review report. Empty leaves the column blank."
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


class OutputConfig(HydroModelBase):
    """Output artifact switches."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "write_regional_lab_csv": (
            "the selected sites enter the workspace site catalog instead. Run "
            "hmp site select <file> --into-catalog, or hmp site import --selection "
            "<manifest>, and remove the key."
        ),
    }

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
    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "random_seed": (
            "no step of the selection draws a random number, so the seed changed "
            "nothing. Remove the key."
        ),
    }

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
            if self.outlets.candidate_mode != "station_outlets":
                raise ValueError(
                    "observation_led requires outlets.candidate_mode='station_outlets'."
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
            if self.criteria.observations.flow_station.mode not in allowed_report_modes:
                raise ValueError("area_only requires flow_station.mode='report_only'.")
            if self.criteria.observations.piezometer_mode not in allowed_report_modes:
                raise ValueError("area_only requires piezometer_mode='report_only'.")
            if self.criteria.geology.mode != "report_only":
                raise ValueError("area_only requires geology.mode='report_only'.")
            if self.criteria.area.mode not in {"hard_reject", "score", "stratify"}:
                raise ValueError("area_only requires area to be an active criterion.")

        return self

    @property
    def effective_profile(self) -> str:
        """Return the explicit selection profile."""

        if self.strategy.profile:
            return self.strategy.profile
        return "custom"


class SiteSelectionFile(HydroModelBase):
    """The site selection file read by ``hmp site select``."""

    site_selection: Annotated[SiteSelectionConfig, Profile.USER] = Field(
        ..., description="The selection: territory, DEM, criteria and outputs."
    )


__all__ = [
    "MapContextConfig",
    "MapContextLayerConfig",
    "OutputConfig",
    "SiteSelectionInputConfig",
    "SiteSelectionConfig",
    "SiteSelectionFile",
]
