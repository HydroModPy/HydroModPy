from dataclasses import dataclass
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, model_validator


@dataclass(frozen=True)
class ParamLevel:
    """Metadata tag for parameter visibility level (user, dev, expert)."""
    level: str


class GeographicConfig(BaseModel):
    """Geographic configuration for watershed delineation."""

    catch_def: Annotated[Literal["dem", "txt", "from_outlet_coord", "from_polyg_shp"], ParamLevel("user")] = Field(
        description=(
            "Catchment definition mode. "
            "'dem' = model domain from a raster DEM (from_dem required). "
            "'txt' = model domain from an XYZ text file (from_dem, cell_size required). "
            "'from_outlet_coord' = watershed from outlet coordinates "
            "(dem_path, x_outlet, y_outlet, snap_dist, buff_percent required). "
            "'from_polyg_shp' = watershed from a polygon shapefile "
            "(dem_path, from_shp, buff_percent required)."
        ),
    )

    dem_path: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Path to the regional DEM raster used for flow analysis. "
            "Required for 'xy' and 'shp' modes."
        ),
    )

    from_dem: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Path to the DEM raster ('dem' mode) or XYZ text file ('txt' mode) "
            "that defines the model domain directly."
        ),
    )
    cell_size: Annotated[Optional[float], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Grid cell size in metres used to rasterise the XYZ point cloud. "
            "Required for 'txt' mode."
        ),
    )

    x_outlet: Annotated[Optional[float], ParamLevel("user")] = Field(
        default=None,
        description=(
            "X coordinate of the watershed outlet in the projected CRS. "
            "Required for 'xy' mode."
        ),
    )
    y_outlet: Annotated[Optional[float], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Y coordinate of the watershed outlet in the projected CRS. "
            "Required for 'xy' mode."
        ),
    )
    snap_dist: Annotated[Optional[int], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Maximum snapping distance (m) used to move the outlet point "
            "to the nearest stream cell. Required for 'xy' mode."
        ),
    )

    buff_percent: Annotated[Optional[float], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Buffer added around the watershed polygon, expressed as a "
            "percentage of sqrt(area [km²]). Required for 'xy' and 'shp' modes."
        ),
    )

    from_shp: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Path to the watershed polygon shapefile. "
            "Required for 'shp' mode."
        ),
    )

    crs_project: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Target projected CRS for all outputs (e.g. 'EPSG:2154'). "
            "Optional: if not set, the CRS is derived from the input DEM. "
            "Applies to all modes."
        ),
    )
    dem_correc_type: Annotated[Literal["breach", "fill"], ParamLevel("user")] = Field(
        default="breach",
        description=(
            "DEM depression correction method used for flow analysis. "
            "'breach' (recommended) preserves natural flow paths. "
            "'fill' raises sinks to the level of their pour point."
        ),
    )
    bottom_path: Annotated[Optional[str], ParamLevel("dev")] = Field(
        default=None,
        description=(
            "Path to a raster representing the aquifer bottom elevation. "
            "Must share the same grid as the model domain."
        ),
    )
    reg_fold: Annotated[Optional[str], ParamLevel("dev")] = Field(
        default=None,
        description=(
            "Folder containing pre-computed regional flow rasters "
            "(region_fill.tif, region_direc.tif, region_acc.tif, region_down.tif). "
            "When set, rasters are loaded from this folder instead of being recomputed."
        ),
    )

    @model_validator(mode="after")
    def _check_mode_requirements(self) -> "GeographicConfig":
        mode = self.catch_def

        if mode in ("dem", "txt"):
            if not self.from_dem:
                raise ValueError(
                    f"catch_def='{mode}' requires 'from_dem' "
                    "(path to the DEM raster or XYZ text file)."
                )
            if mode == "txt" and self.cell_size is None:
                raise ValueError(
                    "catch_def='txt' requires 'cell_size' "
                    "(grid resolution in metres)."
                )

        elif mode == "from_outlet_coord":
            missing = [
                name
                for name, val in [
                    ("dem_path",     self.dem_path),
                    ("x_outlet",     self.x_outlet),
                    ("y_outlet",     self.y_outlet),
                    ("snap_dist",    self.snap_dist),
                    ("buff_percent", self.buff_percent),
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
                    ("dem_path",     self.dem_path),
                    ("from_shp",     self.from_shp),
                    ("buff_percent", self.buff_percent),
                ]
                if val is None
            ]
            if missing:
                raise ValueError(
                    f"catch_def='from_polyg_shp' requires: {', '.join(missing)}."
                )

        return self
