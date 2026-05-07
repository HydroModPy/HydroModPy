from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, ValidationInfo, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.tracking import InputFile
from hydromodpy.core.units import parse_length_to_m
from hydromodpy.spatial.geographic.synthetic.config import SyntheticGeographicConfig


def _normalize_snap_dist(value):
    if value is None:
        return None
    snap_m = float(parse_length_to_m(value, default_unit="m", label="geographic.snap_dist"))
    if snap_m <= 0.0:
        raise ValueError("geographic.snap_dist must be > 0.")
    return snap_m


def _normalize_cell_size(value):
    if value is None:
        return None
    cell_size_m = float(parse_length_to_m(value, default_unit="m", label="geographic.cell_size"))
    if cell_size_m <= 0.0:
        raise ValueError("geographic.cell_size must be > 0.")
    return cell_size_m


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
        dist_m = float(parse_length_to_m(token, default_unit="m", label="geographic.buff_area"))
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
    cell_size: Annotated[float, Profile.USER] = Field(
        gt=0,
        description="Grid cell size in metres used to rasterise the XYZ point cloud.",
    )

    @field_validator("cell_size", mode="before")
    @classmethod
    def _normalize_cell_size_field(cls, value):
        return _normalize_cell_size(value)


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
    snap_dist: Annotated[float | str, Profile.USER] = Field(
        description=(
            "Maximum snapping distance to move the outlet to the nearest stream cell. "
            "Accepts SI-friendly values (for example 50, '50 m', '0.05 km')."
        ),
    )
    buff_area: Annotated[str | float, Profile.USER] = Field(
        description=(
            "Buffer around the watershed polygon. Numeric values keep legacy behavior "
            "(percentage of sqrt(area [km^2])). String values are interpreted as explicit "
            "distances (for example '500 m', '2 km')."
        ),
    )

    @field_validator("snap_dist", mode="before")
    @classmethod
    def _normalize_snap_dist_field(cls, value):
        return _normalize_snap_dist(value)

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
            "Buffer around the watershed polygon. Numeric values keep legacy behavior "
            "(percentage of sqrt(area [km^2])). String values are interpreted as explicit "
            "distances (for example '500 m', '2 km')."
        ),
    )

    @field_validator("buff_area", mode="before")
    @classmethod
    def _normalize_buff_area_field(cls, value):
        return _normalize_buff_area(value)


CatchDef: TypeAlias = Annotated[
    DemCatchDef | TxtCatchDef | OutletCatchDef | PolygonCatchDef,
    Field(discriminator="catch_def"),
]
"""Discriminated union of catchment definition variants."""


_LEGACY_FLAT_KEYS: frozenset[str] = frozenset(
    {
        "catch_def",
        "dem_init_path",
        "cell_size",
        "x_outlet",
        "y_outlet",
        "snap_dist",
        "buff_area",
        "polyg_shp_path",
    }
)


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
    min_stream_length_m: Annotated[float | str, Profile.USER] = Field(
        default=0.0,
        description=(
            "Minimum stream length used by short-segment pruning. "
            "Accepts SI-friendly values (for example 0, 250, '250 m', '0.5 km')."
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

    @field_validator("min_stream_length_m", mode="before")
    @classmethod
    def _normalize_min_stream_length(cls, value):
        length_m = float(
            parse_length_to_m(
                value,
                default_unit="m",
                label="geographic.river_network.min_stream_length_m",
            )
        )
        if length_m < 0.0:
            raise ValueError("geographic.river_network.min_stream_length_m must be >= 0.")
        return length_m

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

    @model_validator(mode="before")
    @classmethod
    def _remap_legacy_flat_payload(cls, data: Any) -> Any:
        """Remap legacy flat ``catch_def`` payloads to the nested ``catchment`` form.

        Supports two intake shapes for the catchment block:

        * Legacy flat (TOML and Python kwargs): ``{catch_def, dem_init_path, ...}``
          living at the top level of the geographic mapping.
        * New nested: ``{catchment: {catch_def, dem_init_path, ...}}``.

        When both are mixed, nested wins for already-set keys.
        """
        if not isinstance(data, dict):
            return data

        flat_keys = _LEGACY_FLAT_KEYS.intersection(data.keys())
        if not flat_keys:
            return data

        new_data = dict(data)
        nested = new_data.get("catchment")
        if nested is None:
            nested_payload: dict[str, Any] = {}
        elif isinstance(nested, dict):
            nested_payload = dict(nested)
        else:
            return data

        for key in flat_keys:
            value = new_data.pop(key)
            if value is None:
                continue
            nested_payload.setdefault(key, value)

        if nested_payload:
            new_data["catchment"] = nested_payload
        return new_data

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
