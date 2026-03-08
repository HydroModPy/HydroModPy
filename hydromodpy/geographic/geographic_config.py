from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.units import parse_length_to_m


class GeographicConfig(BaseModel):
    """
    Geographic configuration for watershed delineation.

    This model stores parameters used to extract and prepare the physical domain
    (watershed geometry and rasters) based on various possible input definitions.
    """

    model_config = ConfigDict(extra="forbid")

    catch_def: Annotated[
        Literal["dem", "txt", "from_outlet_coord", "from_polyg_shp"], ParamLevel("user")
    ] = Field(
        description=(
            "Catchment definition mode. "
            "'dem' = model domain defined directly from a DEM raster (dem_init_path required). "
            "'txt' = model domain from an XYZ text file (dem_init_path, cell_size required). "
            "'from_outlet_coord' = watershed from outlet coordinates "
            "(dem_init_path, x_outlet, y_outlet, snap_dist, buff_area required). "
            "'from_polyg_shp' = watershed from a polygon shapefile "
            "(dem_init_path, polyg_shp_path, buff_area required)."
        ),
    )

    dem_init_path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Path to the DEM raster used as input. "
            "For 'dem' and 'txt' modes: defines the model domain directly. "
            "For 'from_outlet_coord' and 'from_polyg_shp' modes: regional DEM used for flow analysis."
        ),
    )
    cell_size: Annotated[Optional[float], ParamLevel("user")] = Field(
        default=None,
        gt=0,
        description="Grid cell size in metres used to rasterise the XYZ point cloud. Required for 'txt' mode.",
    )
    x_outlet: Annotated[Optional[float], ParamLevel("user")] = Field(
        default=None,
        description="X coordinate of the watershed outlet in the projected CRS. Required for 'from_outlet_coord' mode.",
    )
    y_outlet: Annotated[Optional[float], ParamLevel("user")] = Field(
        default=None,
        description="Y coordinate of the watershed outlet in the projected CRS. Required for 'from_outlet_coord' mode.",
    )
    snap_dist: Annotated[Optional[float | str], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Maximum snapping distance to move the outlet to the nearest stream cell. "
            "Accepts SI-friendly values (for example 50, '50 m', '0.05 km'). "
            "Required for 'from_outlet_coord' mode."
        ),
    )
    buff_area: Annotated[Optional[str | float], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Buffer around the watershed polygon. Numeric values keep legacy behavior "
            "(percentage of sqrt(area [km^2])). String values are interpreted as explicit "
            "distances (for example '500 m', '2 km'). Required for "
            "'from_outlet_coord' and 'from_polyg_shp' modes."
        ),
    )
    polyg_shp_path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None,
        description="Path to the watershed polygon shapefile. Required for 'from_polyg_shp' mode.",
    )
    crs_project: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None,
        description="Target projected CRS for all outputs (e.g. 'EPSG:2154'). If not set, derived from the input DEM.",
    )
    dem_correc_type: Annotated[Literal["breach", "fill"], ParamLevel("user")] = Field(
        default="breach",
        description="DEM depression correction method. 'breach' (recommended) preserves natural flow paths. 'fill' raises sinks to their pour point.",
    )
    bottom_path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None,
        description="Path to a raster representing the aquifer bottom elevation. Must share the same grid as the model domain.",
    )
    reg_fold: Annotated[Optional[Path], ParamLevel("dev")] = Field(
        default=None,
        description="Folder with pre-computed regional flow rasters. When set, rasters are loaded instead of recomputed.",
    )

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
        mode = self.catch_def

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

