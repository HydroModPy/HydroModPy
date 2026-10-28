"""The catchment definitions of ``[geographic]``, one class per way to give the catchment.

The catchment comes from a DEM, an XYZ text grid, an outlet point or a polygon
shapefile. ``CatchDef`` is the tagged union the table reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.core.units import UREG, LengthMeters

__all__ = [
    "CatchDef",
    "DemCatchDef",
    "OutletCatchDef",
    "PolygonCatchDef",
    "TxtCatchDef",
]


def _normalize_buff_area(value):
    """Return ``buff_area`` in the one form that says which rule it selects.

    The form, not the type or the magnitude, carries the meaning downstream
    (``catchment_domain.buffer_rule_of``):

    - ``"10%"`` or ``"10 %"`` becomes the string ``"10%"``: the buffered
      catchment covers 10 per cent more area than the catchment;
    - ``"150 m"``, ``"0.15 km"`` or ``"150"`` becomes ``"150.0 m"``: an explicit
      distance, a string with no unit being metres;
    - a bare number stays a float: the legacy v1 rule, which a sealed run
      still carries and must replay.

    A run is re-read from its own sealed config, so this validator reads what
    it wrote: ``normalize(normalize(x)) == normalize(x)``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        if token == "":
            raise ValueError("geographic.catchment.buff_area cannot be empty.")
        if token.endswith("%"):
            pct = float(token[:-1].strip())
            if pct <= 0.0:
                raise ValueError("geographic.catchment.buff_area percent must be > 0.")
            return f"{int(pct)}%" if pct.is_integer() else f"{pct!r}%"
        quantity = UREG(token)
        if quantity.dimensionless:
            dist_m = float(quantity.magnitude)
        else:
            dist_m = float(quantity.to("m").magnitude)
        if dist_m <= 0.0:
            raise ValueError("geographic.catchment.buff_area distance must be > 0.")
        return f"{dist_m!r} m"
    pct = float(value)
    if pct <= 0.0:
        raise ValueError("geographic.catchment.buff_area percent must be > 0.")
    return pct


_BUFF_AREA_DESCRIPTION = (
    "Margin around the watershed polygon. A percentage ('10%') enlarges the "
    "catchment AREA by that share, the rule of Abherve et al. (2023): the "
    "distance is solved on the real polygon, then snapped to the DEM grid. A "
    "length ('500 m', '2 km') is an explicit distance, snapped to the DEM grid "
    "like the percentage. A bare number (10) keeps "
    "the rule of version 1, 10 per cent of sqrt(area in km2) km, about 50 per cent "
    "more area on a real catchment, and warns: it lets a sealed run replay its "
    "domain."
)


MISSING_CATCHMENT = (
    "geographic.catchment.catch_def is required when "
    "geographic.source_mode='standard'. Add a [geographic.catchment] table "
    'with catch_def = "dem", "txt", "from_outlet_coord" or "from_polyg_shp".'
)


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
    dem_resolution: Annotated[LengthMeters | None, Profile.USER] = Field(
        default=None,
        description=(
            "Cell size the DEM is aggregated to before anything is delineated, a length "
            "('75 m', a bare number in metres). The routing surface, the catchment, the "
            "mesh and the model top all take it. Unset keeps the pixel of the DEM file, "
            "which is what the mesh follows otherwise: 25 m for a BD ALTI download. "
            "Aggregation only: each coarse cell is the mean of the fine pixels it covers, "
            "nodata left out, on a grid aligned on the upper-left corner of the DEM; a "
            "value finer than the DEM's own pixel is refused when the run starts. The "
            "DEM file is not changed, the aggregated copy lives in the geographic "
            "products of the run."
        ),
        examples=["75 m"],
        json_schema_extra={"unit": "m"},
    )

    @field_validator("dem_resolution")
    @classmethod
    def _positive_dem_resolution(cls, value: float | None) -> float | None:
        """Refuse a cell size that is zero or negative."""
        if value is not None and not value > 0.0:
            raise ValueError(f"dem_resolution = {value:g} m: a cell size is a positive length.")
        return value

    @field_validator("buff_area", mode="before", check_fields=False)
    @classmethod
    def _normalize_buff_area_field(cls, value):
        """Normalize ``buff_area`` of the two variants that declare it."""
        return _normalize_buff_area(value)


class DemCatchDef(_CatchDefBase):
    """Model domain defined directly from a DEM raster."""

    catch_def: Annotated[Literal["dem"], Profile.USER] = Field(
        default="dem",
        description="Catchment defined by the DEM raster extent.",
    )
    dem_init_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="dem", category="data"),
    ] = Field(
        description=(
            "Path to the DEM raster that is the model domain. A relative path is read "
            "from the project root (the folder of project.toml); a bare file name is also looked up in "
            "the dem folder of the workspace data. May be left out only when "
            "[[data.dem.sources]] declares the DEM."
        ),
        examples=["dem.tif"],
    )


class TxtCatchDef(_CatchDefBase):
    """Model domain defined from an XYZ text grid plus a cell size."""

    catch_def: Annotated[Literal["txt"], Profile.USER] = Field(
        default="txt",
        description=(
            "Catchment defined from an XYZ text grid (cell_size required). Not implemented: "
            "a document that selects it is refused when it loads."
        ),
    )
    cell_size: Annotated[LengthMeters, Profile.USER] = Field(
        gt=0,
        description=(
            "Grid cell size in metres used to rasterise the XYZ point cloud. "
            "Accepts inline units (e.g. '25 m', '0.025 km')."
        ),
        examples=["25 m"],
    )


class OutletCatchDef(_CatchDefBase):
    """Watershed delineated from an outlet coordinate."""

    catch_def: Annotated[Literal["from_outlet_coord"], Profile.USER] = Field(
        default="from_outlet_coord",
        description="Watershed delineated from outlet coordinates on a regional DEM.",
    )
    x_outlet: Annotated[float, Profile.USER] = Field(
        description="Easting of the watershed outlet in the projected CRS of the project, in metres.",
        examples=[352400.0],
        json_schema_extra=field_metadata(unit="m", site_scoped=True),
    )
    y_outlet: Annotated[float, Profile.USER] = Field(
        description="Northing of the watershed outlet in the projected CRS of the project, in metres.",
        examples=[6788300.0],
        json_schema_extra=field_metadata(unit="m", site_scoped=True),
    )
    snap_dist: Annotated[LengthMeters, Profile.USER] = Field(
        gt=0.0,
        description=(
            "Width (metres) of the square window the outlet is moved inside, centred on the "
            "declared coordinate. Not a maximum displacement: the window reaches "
            "floor(snap_dist / (2 * cell size)) cells on each side, so a value equal to the "
            "cell size moves nothing, and 150 m on a 25 m grid reaches 3 cells, 75 m. "
            "snap_method says where the outlet lands in the window. "
            "Accepts inline units (e.g. 50, '50 m', '0.05 km')."
        ),
        examples=["150 m"],
    )
    snap_method: Annotated[Literal["window", "jenson"], Profile.USER] = Field(
        default="window",
        description=(
            "Where the outlet lands inside the window of snap_dist. 'window' (default) takes "
            "the cell with the largest flow accumulation, so it can land on a larger stream "
            "that lies in the window beside the one the outlet was declared on. 'jenson' "
            "takes the nearest cell of the stream network drawn from the DEM (Jenson and "
            "Domingue 1988, as used by Lindsay, Rothwell and Davies 2008), so it stays on the "
            "nearest stream, and it refuses an outlet with no stream cell in its window. "
            "The network is the cells that drain more than the threshold of "
            "[geographic.river_network] (threshold_area_km2 in km^2, or threshold_cells), "
            "which 'jenson' needs even when that section is not enabled. It is computed from "
            "the DEM: no observed network is read."
        ),
    )
    buff_area: Annotated[str | float, Profile.USER] = Field(
        description=_BUFF_AREA_DESCRIPTION, examples=["10%"]
    )


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
        examples=["watershed.shp"],
        json_schema_extra=field_metadata(site_scoped=True),
    )
    buff_area: Annotated[str | float, Profile.USER] = Field(
        description=_BUFF_AREA_DESCRIPTION, examples=["10%"]
    )


CatchDef: TypeAlias = Annotated[
    DemCatchDef | TxtCatchDef | OutletCatchDef | PolygonCatchDef,
    Field(discriminator="catch_def", description="Catchment definition discriminator."),
]
