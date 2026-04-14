from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config.param_level import ParamLevel, VisibleWhen
from hydromodpy.spatial.geographic.synthetic.config import SyntheticGeographicConfig
from hydromodpy.core.units import parse_length_to_m


class RiverNetworkConfig(BaseModel):
    """Optional stream-network extraction settings for geographic preprocessing."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description=(
            "Enable DEM-based river-network extraction from flow accumulation "
            "during geographic preprocessing."
        ),
    )
    threshold_mode: Annotated[Literal["area_km2", "cells"], ParamLevel("user")] = Field(
        default="area_km2",
        description=(
            "Stream-initiation threshold selector. "
            "'area_km2' uses contributing area in km^2. "
            "'cells' uses contributing-cell count directly."
        ),
    )
    threshold_area_km2: Annotated[
        float | None,
        ParamLevel("user"),
        VisibleWhen("threshold_mode", "area_km2"),
    ] = Field(
        default=None,
        description=(
            "Contributing area threshold (km^2), required when "
            "threshold_mode='area_km2'."
        ),
    )
    threshold_cells: Annotated[
        float | None,
        ParamLevel("user"),
        VisibleWhen("threshold_mode", "cells"),
    ] = Field(
        default=None,
        description=(
            "Contributing-cell threshold, required when threshold_mode='cells'."
        ),
    )
    prune_short_streams: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description="If true, remove short stream segments after extraction.",
    )
    min_stream_length_m: Annotated[float | str, ParamLevel("user")] = Field(
        default=0.0,
        description=(
            "Minimum stream length used by short-segment pruning. "
            "Accepts SI-friendly values (for example 0, 250, '250 m', '0.5 km')."
        ),
    )
    compute_strahler_order: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Compute Strahler order raster from extracted streams.",
    )
    compute_stream_links: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Compute stream-link identifier raster from extracted streams.",
    )
    all_vertices: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description=(
            "Forwarded to Whitebox raster_streams_to_vector. "
            "False keeps a lighter vector geometry."
        ),
    )

    @field_validator("threshold_area_km2", "threshold_cells", mode="before")
    @classmethod
    def _normalize_optional_thresholds(cls, value):
        if value is None:
            return None
        return float(value)

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
    def _validate_threshold_payload(self) -> "RiverNetworkConfig":
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


class GeographicConfig(BaseModel):
    """
    Geographic configuration for watershed delineation.

    This model stores parameters used to extract and prepare the physical domain
    (watershed geometry and rasters) based on various possible input definitions.
    """

    model_config = ConfigDict(extra="forbid")

    source_mode: Annotated[
        Literal["standard", "synthetic"], ParamLevel("user")
    ] = Field(
        default="standard",
        description=(
            "Geographic runtime mode. "
            "'standard' keeps the historical DEM/outlet/polygon workflow. "
            "'synthetic' builds one analytical support from [geographic.synthetic]."
        ),
    )
    catch_def: Annotated[
        Literal["dem", "txt", "from_outlet_coord", "from_polyg_shp"] | None,
        ParamLevel("user"),
    ] = Field(
        default=None,
        description=(
            "Catchment definition mode used when source_mode='standard'. "
            "'dem' = model domain defined directly from a DEM raster (dem_init_path required). "
            "'txt' = model domain from an XYZ text file (dem_init_path, cell_size required). "
            "'from_outlet_coord' = watershed from outlet coordinates "
            "(dem_init_path, x_outlet, y_outlet, snap_dist, buff_area required). "
            "'from_polyg_shp' = watershed from a polygon shapefile "
            "(dem_init_path, polyg_shp_path, buff_area required)."
        ),
    )

    dem_init_path: Annotated[
        Path | None,
        ParamLevel("user"),
        VisibleWhen("source_mode", "standard"),
    ] = Field(
        default=None,
        description=(
            "Path to the DEM raster used as input. "
            "For 'dem' and 'txt' modes: defines the model domain directly. "
            "For 'from_outlet_coord' and 'from_polyg_shp' modes: regional DEM used for flow analysis."
        ),
    )
    cell_size: Annotated[
        float | None,
        ParamLevel("user"),
        VisibleWhen("catch_def", "txt"),
    ] = Field(
        default=None,
        gt=0,
        description="Grid cell size in metres used to rasterise the XYZ point cloud. Required for 'txt' mode.",
    )
    x_outlet: Annotated[
        float | None,
        ParamLevel("user"),
        VisibleWhen("catch_def", "from_outlet_coord"),
    ] = Field(
        default=None,
        description="X coordinate of the watershed outlet in the projected CRS. Required for 'from_outlet_coord' mode.",
    )
    y_outlet: Annotated[
        float | None,
        ParamLevel("user"),
        VisibleWhen("catch_def", "from_outlet_coord"),
    ] = Field(
        default=None,
        description="Y coordinate of the watershed outlet in the projected CRS. Required for 'from_outlet_coord' mode.",
    )
    snap_dist: Annotated[
        float | str | None,
        ParamLevel("user"),
        VisibleWhen("catch_def", "from_outlet_coord"),
    ] = Field(
        default=None,
        description=(
            "Maximum snapping distance to move the outlet to the nearest stream cell. "
            "Accepts SI-friendly values (for example 50, '50 m', '0.05 km'). "
            "Required for 'from_outlet_coord' mode."
        ),
    )
    buff_area: Annotated[
        str | float | None,
        ParamLevel("user"),
        VisibleWhen("catch_def", ("from_outlet_coord", "from_polyg_shp")),
    ] = Field(
        default=None,
        description=(
            "Buffer around the watershed polygon. Numeric values keep legacy behavior "
            "(percentage of sqrt(area [km^2])). String values are interpreted as explicit "
            "distances (for example '500 m', '2 km'). Required for "
            "'from_outlet_coord' and 'from_polyg_shp' modes."
        ),
    )
    polyg_shp_path: Annotated[
        Path | None,
        ParamLevel("user"),
        VisibleWhen("catch_def", "from_polyg_shp"),
    ] = Field(
        default=None,
        description="Path to the watershed polygon shapefile. Required for 'from_polyg_shp' mode.",
    )
    crs_project: Annotated[str | None, ParamLevel("user")] = Field(
        default=None,
        description="Target projected CRS for all outputs (e.g. 'EPSG:2154'). If not set, derived from the input DEM.",
    )
    dem_correc_type: Annotated[Literal["breach", "fill"], ParamLevel("user")] = Field(
        default="breach",
        description="DEM depression correction method. 'breach' (recommended) preserves natural flow paths. 'fill' raises sinks to their pour point.",
    )
    bottom_path: Annotated[Path | None, ParamLevel("user")] = Field(
        default=None,
        description="Path to a raster representing the aquifer bottom elevation. Must share the same grid as the model domain.",
    )
    reg_fold: Annotated[Path | None, ParamLevel("dev")] = Field(
        default=None,
        description="Folder with pre-computed regional flow rasters. When set, rasters are loaded instead of recomputed.",
    )
    synthetic: Annotated[SyntheticGeographicConfig, ParamLevel("user")] = Field(
        default_factory=SyntheticGeographicConfig,
        description=(
            "Synthetic geographic support used when source_mode='synthetic'. "
            "This analytical mode bypasses watershed delineation from external DEM files."
        ),
    )
    river_network: Annotated[RiverNetworkConfig, ParamLevel("user")] = Field(
        default_factory=RiverNetworkConfig,
        description=(
            "Optional DEM-derived river-network extraction settings. "
            "When disabled, no stream network is generated in geographic preprocessing."
        ),
    )
    reuse_existing_outputs: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description=(
            "If true, reuse previously generated geographic artifacts when the "
            "cached fingerprint matches the current DEM, outlet/polygon and "
            "geographic settings. This is useful for profiling repeated "
            "simulation runs in the same workspace."
        ),
    )

    write_intermediates: Annotated[bool, ParamLevel("dev")] = Field(
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

    @field_validator("snap_dist", mode="before")
    @classmethod
    def _normalize_snap_dist(cls, value):
        if value is None:
            return None
        snap_m = float(parse_length_to_m(value, default_unit="m", label="geographic.snap_dist"))
        if snap_m <= 0.0:
            raise ValueError("geographic.snap_dist must be > 0.")
        return snap_m

    @field_validator("cell_size", mode="before")
    @classmethod
    def _normalize_cell_size(cls, value):
        if value is None:
            return None
        cell_size_m = float(parse_length_to_m(value, default_unit="m", label="geographic.cell_size"))
        if cell_size_m <= 0.0:
            raise ValueError("geographic.cell_size must be > 0.")
        return cell_size_m

    @field_validator("buff_area", mode="before")
    @classmethod
    def _normalize_buff_area(cls, value):
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
            # Keep string-mode contract expected by catchment_domain.
            return f"{dist_m}"

        pct = float(value)
        if pct <= 0.0:
            raise ValueError("geographic.buff_area percent must be > 0.")
        return pct

    @model_validator(mode="after")
    def _check_mode_requirements(self) -> "GeographicConfig":
        """
        Validates the configuration based on the selected catchment definition mode.

        Returns
        -------
        GeographicConfig
            The validated current instance.

        Raises
        ------
        ValueError
            If required parameters are missing for the selected mode.
        """
        if self.uses_synthetic_geographic():
            return self

        mode = self.catch_def
        if mode is None:
            raise ValueError(
                "geographic.catch_def is required when geographic.source_mode='standard'."
            )

        if mode in ("dem", "txt"):
            if not self.dem_init_path:
                raise ValueError(
                    f"catch_def='{mode}' requires 'dem_init_path' "
                    "(path to the DEM raster or XYZ text file)."
                )
            if mode == "txt" and self.cell_size is None:
                raise ValueError(
                    "catch_def='txt' requires 'cell_size' (grid resolution in metres)."
                )

        elif mode == "from_outlet_coord":
            missing = [
                name
                for name, val in [
                    ("dem_init_path", self.dem_init_path),
                    ("x_outlet", self.x_outlet),
                    ("y_outlet", self.y_outlet),
                    ("snap_dist", self.snap_dist),
                    ("buff_area", self.buff_area),
                ]
                if val is None
            ]
            if missing:
                raise ValueError(
                    f"catch_def='from_outlet_coord' requires: {', '.join(missing)}."
                )

        elif mode == "from_polyg_shp":
            missing = [
                name
                for name, val in [
                    ("dem_init_path", self.dem_init_path),
                    ("polyg_shp_path", self.polyg_shp_path),
                    ("buff_area", self.buff_area),
                ]
                if val is None
            ]
            if missing:
                raise ValueError(
                    f"catch_def='from_polyg_shp' requires: {', '.join(missing)}."
                )

        return self

