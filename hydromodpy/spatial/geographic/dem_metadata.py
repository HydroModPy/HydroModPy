"""Read and normalize DEM-derived metadata from watershed rasters.

Defines the geographic metadata contract consumed by ``CatchmentDelineation``
and downstream runtime components.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from pathlib import Path

import certifi
import geopy.geocoders
import numpy as np
import rasterio
from geopy.exc import GeocoderServiceError
from geopy.geocoders import Nominatim
from pyproj import Transformer


@dataclass(frozen=True)
class DemMetadata:
    """DEM-derived raster metadata for the geographic runtime.

    The dataclass stores the clipped DEM arrays, geotransform, pixel size,
    projected bounds, centroid, optional WGS84 corner coordinates, and optional
    French department code. ``CatchmentDelineation`` uses it to expose the
    legacy runtime attributes expected by domain and solver code.
    """

    crs: str | None
    dem_box_buff_data: np.ndarray = field(repr=False)
    dem_buff_data: np.ndarray = field(repr=False)
    dem_data: np.ndarray = field(repr=False)
    nodata: float | None
    geodata: tuple[float, float, float, float, float, float]
    x_pixel: int
    y_pixel: int
    resolution_x: float
    resolution_y: float
    dx: float
    dy: float
    resolution: float
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    x_coord: np.ndarray = field(repr=False)
    y_coord: np.ndarray = field(repr=False)
    centroid: list[float]
    centroid_long_lat: tuple[float, float] | None = None
    ur_long_lat: tuple[float, float] | None = None
    ul_long_lat: tuple[float, float] | None = None
    lr_long_lat: tuple[float, float] | None = None
    ll_long_lat: tuple[float, float] | None = None
    centroid_long_lat_Greenwich: list[float] | None = None
    dep_code: int | None = None

    def as_georeferencing(self) -> dict[str, object]:
        """Return the narrow georeferencing payload historically consumed by Domain."""
        return {
            "crs": self.crs,
            "dx": self.dx,
            "dy": self.dy,
            "xmin": self.xmin,
            "xmax": self.xmax,
            "ymin": self.ymin,
            "ymax": self.ymax,
        }

    def runtime_attributes(self) -> dict[str, object]:
        """Return the ``CatchmentDelineation`` attributes derived from these rasters."""
        attrs: dict[str, object] = {
            "dem_box_buff_data": self.dem_box_buff_data,
            "dem_buff_data": self.dem_buff_data,
            "dem_data": self.dem_data,
            "nodata": self.nodata,
            "geodata": self.geodata,
            "x_pixel": self.x_pixel,
            "y_pixel": self.y_pixel,
            "resolution_x": self.resolution_x,
            "resolution_y": self.resolution_y,
            "dx": self.dx,
            "dy": self.dy,
            "resolution": self.resolution,
            "xmin": self.xmin,
            "xmax": self.xmax,
            "ymin": self.ymin,
            "ymax": self.ymax,
            "x_coord": self.x_coord,
            "y_coord": self.y_coord,
            "centroid": self.centroid,
        }
        optional = {
            "centroid_long_lat": self.centroid_long_lat,
            "ur_long_lat": self.ur_long_lat,
            "ul_long_lat": self.ul_long_lat,
            "lr_long_lat": self.lr_long_lat,
            "ll_long_lat": self.ll_long_lat,
            "centroid_long_lat_Greenwich": self.centroid_long_lat_Greenwich,
            "dep_code": self.dep_code,
        }
        for key, value in optional.items():
            if value is not None:
                attrs[key] = value
        return attrs


def _resolve_lon_lat_metadata(
    *,
    crs_project: str | None,
    centroid: list[float],
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
) -> dict[str, object]:
    """Project watershed bounds and centroid to WGS84 when possible."""
    if crs_project is None:
        return {}

    transformer = Transformer.from_crs(crs_project, "epsg:4326")
    centroid_long_lat = transformer.transform(centroid[0], centroid[1])
    ur_long_lat = transformer.transform(xmax, ymax)
    ul_long_lat = transformer.transform(xmin, ymax)
    lr_long_lat = transformer.transform(xmax, ymin)
    ll_long_lat = transformer.transform(xmin, ymin)
    centroid_long_lat_Greenwich = [
        centroid_long_lat[0],
        centroid_long_lat[1],
    ]
    if centroid_long_lat_Greenwich[1] < 0:
        centroid_long_lat_Greenwich[1] += 360

    return {
        "centroid_long_lat": centroid_long_lat,
        "ur_long_lat": ur_long_lat,
        "ul_long_lat": ul_long_lat,
        "lr_long_lat": lr_long_lat,
        "ll_long_lat": ll_long_lat,
        "centroid_long_lat_Greenwich": centroid_long_lat_Greenwich,
    }


def _resolve_dep_code(
    *,
    centroid_long_lat_Greenwich: list[float] | None,
    locator_factory: object,
) -> int | None:
    """Resolve one French department code from reverse geocoding when possible."""
    if centroid_long_lat_Greenwich is None:
        return None

    try:
        locator = locator_factory(user_agent="google")
        location = locator.reverse(
            f"{centroid_long_lat_Greenwich[0]},{centroid_long_lat_Greenwich[1]}",
            timeout=120,
        )
    except OSError:
        try:
            ctx = ssl.create_default_context(cafile=certifi.where())
            geopy.geocoders.options.default_ssl_context = ctx
            locator = locator_factory(user_agent="google")
            location = locator.reverse(
                f"{centroid_long_lat_Greenwich[0]},{centroid_long_lat_Greenwich[1]}",
                timeout=120,
            )
        except Exception:
            return None
    except GeocoderServiceError:
        return None
    except Exception:
        return None

    try:
        return int(location.address.split(",")[-2][0:3])
    except Exception:
        return None


def read_dem_metadata(
    *,
    watershed_box_buff_dem_path: str | Path,
    watershed_buff_dem_path: str | Path,
    watershed_dem_path: str | Path,
    crs_project: str | None,
    locator_factory: object = Nominatim,
) -> DemMetadata:
    """Read clipped DEM rasters and return normalized geographic metadata.

    The function extracts grid shape, nodata, projected bounds, resolution,
    centroid coordinates, optional WGS84 coordinates, and optional department
    code. It returns a ``DemMetadata`` object instead of mutating the
    ``CatchmentDelineation`` instance directly.
    """
    with rasterio.open(str(watershed_box_buff_dem_path)) as box_buff_dem_src:
        dem_box_buff_data = box_buff_dem_src.read(1)
    with rasterio.open(str(watershed_buff_dem_path)) as buff_dem_src:
        dem_buff_data = buff_dem_src.read(1)
    with rasterio.open(str(watershed_dem_path)) as dem_src:
        dem_data = dem_src.read(1)
        nodata = dem_src.nodata
        geodata = dem_src.transform.to_gdal()

    x_pixel = dem_box_buff_data.shape[1]
    y_pixel = dem_box_buff_data.shape[0]
    resolution_x = float(geodata[1])
    resolution_y = float(geodata[5])
    dx = abs(resolution_x)
    dy = abs(resolution_y)
    xmin = float(geodata[0])
    ymax = float(geodata[3])
    xmax = xmin + x_pixel * resolution_x
    ymin = ymax + y_pixel * resolution_y
    x_coord = np.linspace(1, x_pixel, x_pixel) * resolution_x + xmin
    y_coord = ymax - (np.linspace(1, y_pixel, y_pixel) * resolution_x)
    centroid = [
        xmin + ((xmax - xmin) / 2),
        ymin + ((ymax - ymin) / 2),
    ]

    lon_lat_attrs: dict[str, object] = {}
    try:
        lon_lat_attrs = _resolve_lon_lat_metadata(
            crs_project=crs_project,
            centroid=centroid,
            xmin=xmin,
            xmax=xmax,
            ymin=ymin,
            ymax=ymax,
        )
    except Exception:
        lon_lat_attrs = {}

    dep_code = _resolve_dep_code(
        centroid_long_lat_Greenwich=lon_lat_attrs.get("centroid_long_lat_Greenwich"),
        locator_factory=locator_factory,
    )

    return DemMetadata(
        crs=crs_project,
        dem_box_buff_data=dem_box_buff_data,
        dem_buff_data=dem_buff_data,
        dem_data=dem_data,
        nodata=nodata,
        geodata=geodata,
        x_pixel=x_pixel,
        y_pixel=y_pixel,
        resolution_x=resolution_x,
        resolution_y=resolution_y,
        dx=dx,
        dy=dy,
        resolution=resolution_x,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        x_coord=x_coord,
        y_coord=y_coord,
        centroid=centroid,
        centroid_long_lat=lon_lat_attrs.get("centroid_long_lat"),
        ur_long_lat=lon_lat_attrs.get("ur_long_lat"),
        ul_long_lat=lon_lat_attrs.get("ul_long_lat"),
        lr_long_lat=lon_lat_attrs.get("lr_long_lat"),
        ll_long_lat=lon_lat_attrs.get("ll_long_lat"),
        centroid_long_lat_Greenwich=lon_lat_attrs.get("centroid_long_lat_Greenwich"),
        dep_code=dep_code,
    )
