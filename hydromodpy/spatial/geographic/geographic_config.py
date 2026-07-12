from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, ValidationInfo, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.tracking import InputFile
from hydromodpy.core.units import UREG, LengthMeters
from hydromodpy.spatial.geographic.synthetic.config import SyntheticGeographicConfig


def _normalize_buff_area(value):
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        if token == "":
            raise ValueError("geographic.buff_area cannot be empty.")
        if token.endswith("%"):
            pct = float(token[:-1].strip())
            if pct <= 0.0:
                raise ValueError("geographic.buff_area percent must be > 0.")
            return pct
        quantity = UREG(token)
        if not hasattr(quantity, "magnitude"):
            dist_m = float(quantity)
        else:
            dist_m = float(quantity.to("m").magnitude)
        if dist_m <= 0.0:
            raise ValueError("geographic.buff_area distance must be > 0.")
        return f"{dist_m}"
    pct = float(value)
    if pct <= 0.0:
        raise ValueError("geographic.buff_area percent must be > 0.")
    return pct


class _CatchDefBase(HydroModelBase):
    """Common base for catchment definition variants."""

    dem_init_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="dem", category="data"),
    ] = Field(
        default=None,
        description=(
            "Path to the DEM raster used as input. "
            "For 'dem' and 'txt' modes: defines the model domain directly. "
            "For 'from_outlet_coord' and 'from_polyg_shp' modes: regional DEM used for flow analysis. "
            "May be left absent when [data.dem.sources] declares the DEM."
        ),
    )


class DemCatchDef(_CatchDefBase):
    """Model domain defined directly from a DEM raster."""

    catch_def: Annotated[Literal["dem"], Profile.USER] = Field(
        default="dem",
        description="Catchment defined by the DEM raster extent.",
    )


class TxtCatchDef(_CatchDefBase):
    """Model domain defined from an XYZ text grid plus a cell size."""

    catch_def: Annotated[Literal["txt"], Profile.USER] = Field(
        default="txt",
        description="Catchment defined from an XYZ text grid (cell_size required).",
    )
    cell_size: Annotated[LengthMeters, Profile.USER] = Field(
        gt=0,
        description=(
            "Grid cell size in metres used to rasterise the XYZ point cloud. "
            "Accepts inline units (e.g. '25 m', '0.025 km')."
        ),
    )


class OutletCatchDef(_CatchDefBase):
    """Watershed delineated from an outlet coordinate."""

    catch_def: Annotated[Literal["from_outlet_coord"], Profile.USER] = Field(
        default="from_outlet_coord",
        description="Watershed delineated from outlet coordinates on a regional DEM.",
    )
    x_outlet: Annotated[float, Profile.USER] = Field(
        description="X coordinate of the watershed outlet in the projected CRS.",
    )
    y_outlet: Annotated[float, Profile.USER] = Field(
        description="Y coordinate of the watershed outlet in the projected CRS.",
    )
    snap_dist: Annotated[LengthMeters, Profile.USER] = Field(
        gt=0.0,
        description=(
            "Maximum snapping distance (metres) to move the outlet to the nearest stream cell. "
            "Accepts inline units (e.g. 50, '50 m', '0.05 km')."
        ),
    )
    buff_area: Annotated[str | float, Profile.USER] = Field(
        description=(
            "Buffer around the watershed polygon. Numeric values are interpreted as a "
            "percentage of sqrt(area [km^2]). String values are interpreted as explicit "
            "distances (for example '500 m', '2 km')."
        ),
    )

    @field_validator("buff_area", mode="before")
    @classmethod
    def _normalize_buff_area_field(cls, value):
        return _normalize_buff_area(value)


class PolygonCatchDef(_CatchDefBase):
    """Watershed delineated from a polygon shapefile."""

    catch_def: Annotated[Literal["from_polyg_shp"], Profile.USER] = Field(
        default="from_polyg_shp",
        description="Watershed delineated from a polygon shapefile plus a regional DEM.",
    )
    polyg_shp_path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="watershed_polygon", category="geometry"),
    ] = Field(
        description="Path to the watershed polygon shapefile.",
    )
    buff_area: Annotated[str | float, Profile.USER] = Field(
        description=(
            "Buffer around the watershed polygon. Numeric values are interpreted as a "
            "percentage of sqrt(area [km^2]). String values are interpreted as explicit "
            "distances (for example '500 m', '2 km')."
        ),
    )

    @field_validator("buff_area", mode="before")
    @classmethod
    def _normalize_buff_area_field(cls, value):
        return _normalize_buff_area(value)


CatchDef: TypeAlias = Annotated[
    DemCatchDef | TxtCatchDef | OutletCatchDef | PolygonCatchDef,
    Field(discriminator="catch_def", description="Catchment definition discriminator."),
]
"""Discriminated union of catchment definition variants."""


class RiverNetworkConfig(HydroModelBase):
    """Optional DEM-based river network extraction settings.

    Enable this block when geographic preprocessing must derive streams from
    flow accumulation. Thresholds can be expressed as contributing area
    (``area_km2``) or contributing cell count (``cells``), with optional
    pruning and Strahler/link rasters for downstream diagnostics.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Enable DEM-based river-network extraction from flow accumulation "
            "during geographic preprocessing."
        ),
    )
    threshold_mode: Annotated[Literal["area_km2", "cells"], Profile.USER] = Field(
        default="area_km2",
        description=(
            "Stream-initiation threshold selector. "
            "'area_km2' uses contributing area in km^2. "
            "'cells' uses contributing-cell count directly."
        ),
    )
    threshold_area_km2: Annotated[
        float | None,
        Profile.USER,
        VisibleWhen("threshold_mode", "area_km2"),
    ] = Field(
        default=None,
        description=(
            "Contributing area threshold (km^2), required when threshold_mode='area_km2'."
        ),
    )
    threshold_cells: Annotated[
        float | None,
        Profile.USER,
        VisibleWhen("threshold_mode", "cells"),
    ] = Field(
        default=None,
        description=("Contributing-cell threshold, required when threshold_mode='cells'."),
    )
    prune_short_streams: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="If true, remove short stream segments after extraction.",
    )
    min_stream_length_m: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Minimum stream length (metres) used by short-segment pruning. "
            "Accepts inline units (e.g. 0, 250, '250 m', '0.5 km')."
        ),
    )
    compute_strahler_order: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute Strahler order raster from extracted streams.",
    )
    compute_stream_links: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute stream-link identifier raster from extracted streams.",
    )
    all_vertices: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Forwarded to Whitebox raster_streams_to_vector. False keeps a lighter vector geometry."
        ),
    )

    @model_validator(mode="after")
    def _validate_threshold_payload(self) -> RiverNetworkConfig:
        if not bool(self.enabled):
            return self

        mode = str(self.threshold_mode)
        if mode == "area_km2":
            if self.threshold_area_km2 is None:
                raise ValueError(
                    "geographic.river_network.threshold_mode='area_km2' requires "
                    "geographic.river_network.threshold_area_km2."
                )
            if float(self.threshold_area_km2) <= 0.0:
                raise ValueError("geographic.river_network.threshold_area_km2 must be > 0.")
            if self.threshold_cells is not None:
                raise ValueError(
                    "geographic.river_network.threshold_cells must be omitted when "
                    "threshold_mode='area_km2'."
                )
            return self

        if self.threshold_cells is None:
            raise ValueError(
                "geographic.river_network.threshold_mode='cells' requires "
                "geographic.river_network.threshold_cells."
            )
        if float(self.threshold_cells) <= 0.0:
            raise ValueError("geographic.river_network.threshold_cells must be > 0.")
        if self.threshold_area_km2 is not None:
            raise ValueError(
                "geographic.river_network.threshold_area_km2 must be omitted when "
                "threshold_mode='cells'."
            )
        return self


class LakeEnforcementConfig(HydroModelBase):
    """Hydro-enforce lakes into the ROUTING DEM before D8 flow routing.

    A topographic breach/fill is lake-blind: on a dammed reservoir it carves a
    thalweg that misses the flat water body, so streams dead-end short of the lake
    and the outlet-delineated catchment excludes the reservoir. When enabled, the
    lake footprints are carved (a gentle ramp toward the outlet plus an outlet
    notch) into a SEPARATE routing DEM used only for delineation; the model grid
    top stays on the raw DEM, so the lake-aquifer geometry is untouched. It reuses
    the lake footprint polygons already supplied for LAK cells -- no river source.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Carve the lake footprints into the routing DEM before D8 so streams "
            "converge into the lakes and drain to the outlet through them."
        ),
    )
    lake_geometry_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="lake_enforcement_geometry", category="geometry"),
    ] = Field(
        default=None,
        description=(
            "Lake footprint polygons (gpkg/shp) to carve. A bare filename resolves "
            "against <workspace>/data/lake_geometry/. Required when enabled."
        ),
    )
    slope: Annotated[float, Profile.USER] = Field(
        default=0.003,
        gt=0.0,
        description=(
            "Ramp gradient (m per m of distance to the outlet). Small and positive "
            "so each lake slopes gently toward the outlet with no flat depression "
            "(a flat sink would make the breach crawl)."
        ),
    )
    buffer_m: Annotated[LengthMeters, Profile.USER] = Field(
        default=15.0,
        ge=0.0,
        description=(
            "Buffer (metres) applied to each lake footprint to bridge inter-lake "
            "sills and knit the shoreline into the carve."
        ),
    )
    capture_radius_m: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        description=(
            "If > 0, run a SECOND delineation pass: any stream that dead-ends within "
            "this distance of a lake (a near-miss over a flat forebay) is carved to "
            "the lake and re-delineated, so its channel reaches the shoreline. 0 "
            "disables the capture pass (lake carve only)."
        ),
    )
    capture_max_streams: Annotated[int, Profile.EXPERT] = Field(
        default=8,
        ge=1,
        description=(
            "Capture pass: cap on how many near-miss stream terminals are carved to "
            "lakes per pass (kept by decreasing flow accumulation)."
        ),
    )
    capture_min_acc_fraction: Annotated[float, Profile.EXPERT] = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Capture pass: keep only near-miss terminals whose flow accumulation is at "
            "least this fraction of the largest, so a tiny rivulet is not carved."
        ),
    )


class DamCarveConfig(HydroModelBase):
    """Optional dam structure-carve of the MODEL-TOP DEM.

    A raw DEM samples the concrete dam crest as terrain, so the aquifer column
    under the dam is lifted to the crest (~87 m on the Cheze 5 m DEM) and a
    cutoff-wall HFB band lands above the real seepage. This carves ONLY the dam
    footprint of the model-top DEM down to the surrounding valley floor, so the
    cutoff wall can sit on the surveyed axis at the dam (not shifted downstream,
    and no need for a stream-burned DEM that would lower every channel). It is
    the mirror of enforce_lakes: enforce_lakes carves the routing DEM, this
    carves the top DEM, at the dam only.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Carve the dam footprint of the model-top DEM down to the local "
            "valley floor so the cutoff wall sits at the true dam on a raw DEM."
        ),
    )
    line_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="dam_carve_line", category="geometry"),
    ] = Field(
        default=None,
        description=(
            "Dam trace (gpkg/shp/csv) along which the top is carved. A bare "
            "filename resolves against <workspace>/data/cutoff_wall/. Usually the "
            "same surveyed voile axis as the cutoff_wall. Required when enabled."
        ),
    )
    buffer_m: Annotated[LengthMeters, Profile.USER] = Field(
        default=40.0,
        gt=0.0,
        description=(
            "Half-width (metres) of the carved corridor around the dam trace. "
            "Make it a bit wider than one DEM/cell size so the whole dam body is "
            "brought to the valley floor."
        ),
    )
    search_radius_m: Annotated[LengthMeters | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Radius (metres) of the neighborhood whose minimum elevation defines "
            "the valley floor the corridor is carved to. When omitted, derives "
            "3 * buffer_m."
        ),
    )


class GeographicConfig(HydroModelBase):
    """Geographic configuration for watershed delineation.

    This model stores parameters used to extract and prepare the physical domain
    (watershed geometry and rasters) based on various possible input definitions.

    Standard mode uses an external DEM with one of the catchment definitions:
    direct DEM, XYZ text grid, outlet coordinate, or polygon shapefile.
    Synthetic mode builds an analytical support and bypasses external DEM
    delineation.
    """

    source_mode: Annotated[Literal["standard", "synthetic"], Profile.USER] = Field(
        default="standard",
        description=(
            "Geographic runtime mode. "
            "'standard' keeps the historical DEM/outlet/polygon workflow. "
            "'synthetic' builds one analytical support from [geographic.synthetic]."
        ),
    )
    catchment: Annotated[
        CatchDef | None,
        Profile.USER,
        VisibleWhen("source_mode", "standard"),
    ] = Field(
        default=None,
        description=(
            "Catchment definition payload used when source_mode='standard'. "
            "Discriminated by 'catch_def' on the nested table: "
            "'dem' | 'txt' | 'from_outlet_coord' | 'from_polyg_shp'."
        ),
    )
    crs_project: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Target projected CRS for all outputs (e.g. 'EPSG:2154'). If not set, derived from the input DEM.",
    )
    dem_correc_type: Annotated[Literal["breach", "fill"], Profile.USER] = Field(
        default="breach",
        description="DEM depression correction method. 'breach' (recommended) preserves natural flow paths. 'fill' raises sinks to their pour point.",
    )
    domain_extent: Annotated[Literal["box", "watershed_buff", "watershed"], Profile.USER] = Field(
        default="box",
        description=(
            "Selects the DEM surface used for the domain. 'box' (default) keeps "
            "the full buffered rectangular support. 'watershed' / 'watershed_buff' "
            "select the catchment (optionally with a buffer ring) surface. Note: "
            "the MODFLOW 6 mesh still covers the buffered box (the buffer stays "
            "active for inter-basin exchange); out-of-watershed drainage is kept "
            "out of the catchment discharge by the DRN watershed-routing, not by "
            "an idomain mask. Experimental."
        ),
    )
    bottom_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="aquifer_bottom", category="geometry"),
    ] = Field(
        default=None,
        description="Path to a raster representing the aquifer bottom elevation. Must share the same grid as the model domain.",
    )
    reg_fold: Annotated[Path | None, Profile.DEV] = Field(
        default=None,
        description="Folder with pre-computed regional flow rasters. When set, rasters are loaded instead of recomputed.",
    )
    synthetic: Annotated[SyntheticGeographicConfig, Profile.USER] = Field(
        default_factory=SyntheticGeographicConfig,
        description=(
            "Synthetic geographic support used when source_mode='synthetic'. "
            "This analytical mode bypasses watershed delineation from external DEM files."
        ),
    )
    river_network: Annotated[RiverNetworkConfig, Profile.USER] = Field(
        default_factory=RiverNetworkConfig,
        description=(
            "Optional DEM-derived river-network extraction settings. "
            "When disabled, no stream network is generated in geographic preprocessing."
        ),
    )
    enforce_lakes: Annotated[LakeEnforcementConfig, Profile.USER] = Field(
        default_factory=LakeEnforcementConfig,
        description=(
            "Optional lake hydro-enforcement of the routing DEM: carve the lake "
            "footprints so streams route into the lakes and drain to the outlet, "
            "without touching the model grid top."
        ),
    )
    dam_carve: Annotated[DamCarveConfig, Profile.USER] = Field(
        default_factory=DamCarveConfig,
        description=(
            "Optional dam structure-carve of the model-top DEM: lower the dam "
            "footprint to the valley floor so a cutoff wall sits at the dam on a "
            "raw DEM (mirror of enforce_lakes, on the top instead of the routing DEM)."
        ),
    )
    reuse_existing_outputs: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "If true, reuse previously generated geographic artifacts when the "
            "cached fingerprint matches the current DEM, outlet/polygon and "
            "geographic settings. This is useful for profiling repeated "
            "simulation runs in the same workspace."
        ),
    )

    write_intermediates: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description=(
            "Keep intermediate rasters and shapefiles on disk after geographic "
            "preprocessing. When false (default), results_stable/ is removed "
            "after ingestion into the simulation Zarr store."
        ),
    )

    def uses_synthetic_geographic(self) -> bool:
        """Return True when the analytical synthetic geographic mode is selected."""
        return str(self.source_mode).strip().lower() == "synthetic"

    @property
    def catch_def(self) -> str | None:
        """Discriminator value of the active catchment variant, or None for synthetic."""
        return None if self.catchment is None else self.catchment.catch_def

    @property
    def dem_init_path(self) -> Path | None:
        """DEM input path from the active catchment variant, or None."""
        return None if self.catchment is None else self.catchment.dem_init_path

    @property
    def cell_size(self) -> float | None:
        """Cell size for 'txt' variant, or None otherwise."""
        return getattr(self.catchment, "cell_size", None) if self.catchment is not None else None

    @property
    def x_outlet(self) -> float | None:
        """Outlet x coordinate for 'from_outlet_coord' variant, or None otherwise."""
        return getattr(self.catchment, "x_outlet", None) if self.catchment is not None else None

    @property
    def y_outlet(self) -> float | None:
        """Outlet y coordinate for 'from_outlet_coord' variant, or None otherwise."""
        return getattr(self.catchment, "y_outlet", None) if self.catchment is not None else None

    @property
    def snap_dist(self) -> float | None:
        """Outlet snapping distance for 'from_outlet_coord' variant, or None otherwise."""
        return getattr(self.catchment, "snap_dist", None) if self.catchment is not None else None

    @property
    def buff_area(self) -> str | float | None:
        """Watershed buffer for outlet/polygon variants, or None otherwise."""
        return getattr(self.catchment, "buff_area", None) if self.catchment is not None else None

    @property
    def polyg_shp_path(self) -> Path | None:
        """Watershed polygon shapefile for 'from_polyg_shp' variant, or None otherwise."""
        return (
            getattr(self.catchment, "polyg_shp_path", None) if self.catchment is not None else None
        )

    @classmethod
    def from_outlet(
        cls,
        *,
        x: float,
        y: float,
        dem: str | Path,
        snap_dist: float | str = 150.0,
        buff_area: float | str = 10.0,
        crs_project: str | None = None,
        **overrides,
    ) -> GeographicConfig:
        """Watershed delineated from an outlet coordinate and a DEM raster."""
        return cls(
            source_mode="standard",
            catchment={
                "catch_def": "from_outlet_coord",
                "dem_init_path": Path(dem) if dem is not None else None,
                "x_outlet": float(x),
                "y_outlet": float(y),
                "snap_dist": snap_dist,
                "buff_area": buff_area,
            },
            crs_project=crs_project,
            **overrides,
        )

    @classmethod
    def from_dem(
        cls,
        dem: str | Path,
        *,
        crs_project: str | None = None,
        **overrides,
    ) -> GeographicConfig:
        """Model domain driven entirely by a DEM raster."""
        return cls(
            source_mode="standard",
            catchment={"catch_def": "dem", "dem_init_path": Path(dem)},
            crs_project=crs_project,
            **overrides,
        )

    @classmethod
    def from_polygon(
        cls,
        polygon: str | Path,
        *,
        dem: str | Path,
        buff_area: float | str = 10.0,
        crs_project: str | None = None,
        **overrides,
    ) -> GeographicConfig:
        """Watershed delineated from a polygon shapefile plus a DEM."""
        return cls(
            source_mode="standard",
            catchment={
                "catch_def": "from_polyg_shp",
                "dem_init_path": Path(dem),
                "polyg_shp_path": Path(polygon),
                "buff_area": buff_area,
            },
            crs_project=crs_project,
            **overrides,
        )

    @classmethod
    def synthetic_case(cls, **overrides) -> GeographicConfig:
        """Analytical synthetic geographic support (bypasses DEM delineation)."""
        return cls(source_mode="synthetic", **overrides)

    @model_validator(mode="after")
    def _check_source_mode_payload(self, info: ValidationInfo) -> GeographicConfig:
        """Enforce mode-level invariants between source_mode and catchment."""
        if self.uses_synthetic_geographic():
            return self
        if self.catchment is None:
            raise ValueError(
                "geographic.catch_def is required when geographic.source_mode='standard'."
            )
        context = info.context or {}
        allow_dem_bootstrap = bool(context.get("allow_dem_bootstrap"))
        if self.catchment.dem_init_path is None and not allow_dem_bootstrap:
            raise ValueError(
                f"catch_def='{self.catchment.catch_def}' requires 'dem_init_path' "
                "(path to the DEM raster or XYZ text file)."
            )
        return self


__all__ = [
    "CatchDef",
    "DemCatchDef",
    "GeographicConfig",
    "OutletCatchDef",
    "PolygonCatchDef",
    "RiverNetworkConfig",
    "TxtCatchDef",
]
