from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, model_validator


@dataclass(frozen=True)
class ParamLevel:
    """
    Metadata tag for parameter visibility level (user, dev, expert).

    This class wraps a string indicating the visibility/complexity level
    of configuration fields for auto-generating interfaces or documentation.
    """

    level: str


class GeographicConfig(BaseModel):
    """
    Geographic configuration for watershed delineation.

    This model stores parameters used to extract and prepare the physical domain
    (watershed geometry and rasters) based on various possible input definitions.
    """

    catch_def: Annotated[
        Literal["dem", "txt", "from_outlet_coord", "from_polyg_shp"], ParamLevel("user")
    ] = Field(
        description=(
            "Catchment definition mode. "
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
    snap_dist: Annotated[Optional[int], ParamLevel("user")] = Field(
        default=None,
        gt=0,
        description="Maximum snapping distance (m) to move the outlet to the nearest stream cell. Required for 'from_outlet_coord' mode.",
    )
    buff_area: Annotated[Optional[float], ParamLevel("user")] = Field(
        default=None,
        gt=0,
        description="Buffer around the watershed polygon as a percentage of sqrt(area [km²]). Required for 'from_outlet_coord' and 'from_polyg_shp' modes.",
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
