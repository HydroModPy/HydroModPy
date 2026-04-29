"""Raster I/O: loading, clipping, reprojecting, and exporting GeoTIFF/NetCDF."""

from __future__ import annotations

import datetime
import os
import re

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio as rio
import rasterio.enums  # noqa: F401 - used as rio.enums across this module
import rasterio.features
import xarray as xr
from pyproj import CRS
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info
from rasterio.warp import calculate_default_transform, reproject
from shapely.geometry import Point

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def clip_tif(tif_path, shp_path, out_path, maintain_dimensions, *, backend):
    """Clip a raster by a shapefile polygon using the supplied Whitebox backend."""
    backend.raster.clip_raster_to_polygon(
        tif_path,
        shp_path,
        out_path,
        maintain_dimensions=maintain_dimensions,
    )


def mask_by_dem(target_data, mask_data, cond_symb, value_masked):
    """Return a masked array based on *cond_symb* applied to *mask_data*."""
    ops = {
        "==": np.ma.masked_equal,
        "!=": np.ma.masked_not_equal,
    }
    if cond_symb in ops:
        return ops[cond_symb](mask_data, value_masked)
    cmp = {
        "<=": np.less_equal,
        ">=": np.greater_equal,
        ">": np.greater,
        "<": np.less,
    }
    return np.ma.masked_array(target_data, mask=cmp[cond_symb](mask_data, value_masked))


def load_to_numpy(
    file,
    src_crs=None,
    base_path: str = None,
    dst_crs=None,
    out_path: str = None,
):
    """Load a raster or vector file into a NumPy array aligned to *base_path*."""
    if base_path:
        with rio.open(base_path, "r") as base:
            base_profile = base.profile
            base_val = base.read(1)
    else:
        base_profile = None

    if isinstance(src_crs, str):
        src_crs = rio.crs.CRS.from_string(src_crs)
    elif isinstance(src_crs, int):
        src_crs = rio.crs.CRS.from_epsg(src_crs)
    if isinstance(dst_crs, str):
        dst_crs = rio.crs.CRS.from_string(dst_crs)
    elif isinstance(dst_crs, int):
        dst_crs = rio.crs.CRS.from_epsg(dst_crs)

    file_vect = None
    if isinstance(file, gpd.geodataframe.GeoDataFrame):
        file_vect = file
    elif os.path.splitext(file)[-1] in [".shp", ".dbf", ".shx"]:
        file_vect = gpd.read_file(file)
    elif os.path.splitext(file)[-1] in [".txt", ".csv"]:
        try:
            df = pd.read_csv(file, sep=";")
            geometry = [Point(xy) for xy in zip(df.x, df.y, strict=False)]
            df = df.drop(columns=["x", "y"])
            file_vect = gpd.GeoDataFrame(df, geometry=geometry)
        except Exception:
            logger.error(
                "Failed to read coordinate CSV %s; expected columns 'id;x;y'",
                file,
            )

    if file_vect is not None:
        if base_profile:
            if not file_vect.crs:
                if src_crs:
                    file_vect.set_crs(crs=src_crs, inplace=True, allow_override=True)
                else:
                    logger.error("Source CRS required to rasterize vector dataset")
                    return
            if not base_profile["crs"].is_valid:
                if dst_crs:
                    base_profile["crs"] = dst_crs
                else:
                    logger.error("Destination CRS required to rasterize vector dataset")
                    return
            file_vect.to_crs(crs=base_profile["crs"].to_epsg(), inplace=True)
            val = rio.features.rasterize(
                [(v.geometry, 1) for _, v in file_vect.iterrows()],
                out_shape=(base_profile["height"], base_profile["width"]),
                transform=base_profile["transform"],
                fill=base_profile["nodata"],
                all_touched=False,
            )
            data_profile = base_profile
        else:
            logger.error("Raster profile required to rasterize vector dataset")
            return
    else:
        with rio.open(file, "r") as data:
            data_profile = data.profile
            if src_crs and not data_profile["crs"].is_valid:
                data_profile["crs"] = src_crs
            val = data.read(1)

    if base_profile:
        if dst_crs and not base_profile["crs"].is_valid:
            base_profile["crs"] = dst_crs
        if data_profile != base_profile:
            if not data_profile["crs"].is_valid:
                logger.error("Source CRS required to reproject raster dataset")
                return
            if not base_profile["crs"].is_valid:
                logger.error("Destination CRS required to reproject raster dataset")
                return
            rio.warp.reproject(
                source=val,
                destination=base_val,
                src_transform=data_profile["transform"],
                src_crs=data_profile["crs"],
                src_nodata=data_profile["nodata"],
                dst_transform=base_profile["transform"],
                dst_crs=base_profile["crs"],
                dst_nodata=base_profile["nodata"],
                resampling=rasterio.enums.Resampling(1),
            )
            data_profile = base_profile
            val = base_val

    if out_path:
        with rio.open(out_path, "w", **data_profile) as dst:
            dst.write_band(1, val)

    if base_profile:
        dst_crs = base_profile["crs"]
        nodata = base_profile["nodata"]
    else:
        nodata = None

    if file_vect is not None:
        src_crs = file_vect.crs
    else:
        src_crs = data_profile["crs"]

    return val, src_crs, dst_crs, nodata


def load_to_xarray(file, src_crs=None, main_var=None, base_path: str = None, dst_crs=None):
    """Load a raster/NetCDF into an xarray Dataset, optionally reprojected."""
    if base_path:
        with rio.open(base_path, "r") as base:
            base_profile = base.profile
    else:
        base_profile = None

    if isinstance(src_crs, str):
        src_crs = rio.crs.CRS.from_string(src_crs)
    elif isinstance(src_crs, int):
        src_crs = rio.crs.CRS.from_epsg(src_crs)
    if isinstance(dst_crs, str):
        dst_crs = rio.crs.CRS.from_string(dst_crs)
    elif isinstance(dst_crs, int):
        dst_crs = rio.crs.CRS.from_epsg(dst_crs)

    if isinstance(file, str):
        ext = os.path.splitext(file)[-1].casefold()
        if ext in (".tif", ".tiff"):
            with xr.open_dataset(file) as ds:
                ds.load()
            ds = ds.squeeze("band")
            ds = ds.drop_vars("band")
            if main_var:
                ds = ds.rename({"band_data": main_var})
        elif ext == ".nc":
            try:
                with xr.open_dataset(file, decode_coords="all") as ds:
                    ds.load()
            except ValueError:
                logger.warning("Unable to decode NetCDF time units; falling back to manual parsing")
                with xr.open_dataset(file, decode_coords="all", decode_times=False) as ds:
                    ds.load()

                try:
                    ds.time.attrs["units"]
                except Exception:
                    logger.error("No time unit metadata found in NetCDF dataset")
                    return

                timeunit = ds.time.attrs["units"].split()[0].casefold()
                if timeunit in ("month", "months", "mois"):
                    freq = "MS"
                elif timeunit in ("day", "days", "jour", "jours"):
                    freq = "1D"

                initdate_pattern = re.compile(r"\d{2,4}.*\d{2,4}")
                initdate = initdate_pattern.search(ds.time.attrs["units"]).group()

                if initdate[2].isnumeric():
                    sep = initdate[4]
                    initdate = datetime.datetime.strptime(initdate, f"%Y{sep}%m{sep}%d")
                else:
                    sep = initdate[2]
                    initdate = datetime.datetime.strptime(initdate, f"%d{sep}%m{sep}%Y")

                start_date = pd.Series(
                    pd.date_range(initdate, periods=int(ds.time[0]) + 1, freq=freq)
                ).iloc[-1]
                date_index = pd.date_range(start=start_date, periods=len(ds.time), freq=freq)
                ds["time"] = date_index
        else:
            logger.error("File extension %s not supported for xarray loading", ext)
            return
    elif isinstance(file, xr.core.dataset.Dataset):
        ds = file

    def _is_crs_invalid(crs):
        if crs is None:
            return True
        crs_str = str(crs)
        invalid_patterns = [
            "EngineeringCRS",
            "Unknown engineering datum",
            "LOCAL_CS",
            'UNIT["unknown"',
            "unnamed",
        ]
        if any(p in crs_str for p in invalid_patterns):
            return True
        try:
            return crs.to_dict().get("type") == "EngineeringCRS"
        except Exception:
            return False

    if src_crs:
        current_crs = ds.rio.crs
        if _is_crs_invalid(current_crs) or "spatial_ref" not in ds.coords:
            if "spatial_ref" in ds.coords:
                ds = ds.drop_vars("spatial_ref")
            ds.rio.write_crs(src_crs, inplace=True)

    data_transform = ds.rio.transform()

    if base_profile:
        if dst_crs and _is_crs_invalid(base_profile["crs"]):
            base_profile["crs"] = dst_crs
        if (data_transform != base_profile["transform"]) | (ds.rio.crs != base_profile["crs"]):
            if _is_crs_invalid(ds.rio.crs):
                logger.error("Source CRS required to reproject xarray dataset")
                return
            if _is_crs_invalid(base_profile["crs"]):
                logger.error("Destination CRS required to reproject xarray dataset")
                return
            ds = ds.rio.reproject(
                dst_crs=base_profile["crs"],
                transform=base_profile["transform"],
                shape=(base_profile["height"], base_profile["width"]),
                nodata=np.nan,
                resampling=rasterio.enums.Resampling(1),
            )
    elif dst_crs is not None:
        if _is_crs_invalid(ds.rio.crs):
            logger.error(
                "Source CRS required to reproject - current CRS is invalid: %s",
                ds.rio.crs,
            )
            return
        ds = ds.rio.reproject(dst_crs=dst_crs)

    if "units" in ds.x.attrs and ds.x.attrs["units"].casefold() in (
        "m",
        "meter",
        "meters",
        "metre",
        "metres",
    ):
        ds.x.attrs = {
            "standard_name": "projection_x_coordinate",
            "long_name": "x coordinate of projection",
            "units": "Meter",
        }
        ds.y.attrs = {
            "standard_name": "projection_y_coordinate",
            "long_name": "y coordinate of projection",
            "units": "Meter",
        }
    elif "units" in ds.x.attrs and "deg" in ds.x.attrs["units"]:
        ds.longitude.attrs = {"long_name": "longitude", "units": "degrees_east"}
        ds.latitude.attrs = {"long_name": "latitude", "units": "degrees_north"}

    return ds


def export_tif(base_dem_path, data_to_tif, data_tif_path, data_nodata_val=None, data_crs=None):
    """Export a 2-D array as GeoTIFF using *base_dem_path* as spatial reference."""
    with rio.open(base_dem_path) as src:
        ras_meta = src.profile
    data_dtype = data_to_tif.dtype
    ras_meta["dtype"] = data_dtype
    if data_nodata_val is not None:
        ras_meta["nodata"] = data_nodata_val
    if data_crs is not None:
        if isinstance(data_crs, str):
            ras_meta["crs"] = rio.crs.CRS.from_string(data_crs)
        elif isinstance(data_crs, int):
            ras_meta["crs"] = rio.crs.CRS.from_epsg(data_crs)
        else:
            ras_meta["crs"] = data_crs
    with rio.open(data_tif_path, "w", **ras_meta) as dst:
        dst.write(data_to_tif, 1)


def reproject_tif(raw_dem_path, wgs_dem_path, utm_dem_path):
    """Reproject a raster from its source CRS to WGS-84 then to local UTM."""
    with rio.open(raw_dem_path) as src:
        dst_crs = rio.crs.CRS.from_epsg(4326)
        transform_, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        kwargs = src.meta.copy()
        kwargs.update({"crs": dst_crs, "transform": transform_, "width": width, "height": height})
        with rio.open(wgs_dem_path, "w", **kwargs) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rio.band(src, band),
                    destination=rio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform_,
                    dst_crs=dst_crs,
                    resampling=rio.enums.Resampling.bilinear,
                )

    with rio.open(wgs_dem_path) as wgs_dem:
        wgs_dem_data = wgs_dem.read(1)
        geodata = wgs_dem.transform.to_gdal()
        x_pixel = wgs_dem_data.shape[1]
        y_pixel = wgs_dem_data.shape[0]
        resolution_x = geodata[1]
        resolution_y = geodata[5]
        xmin = geodata[0]
        ymax = geodata[3]
        xmax = xmin + x_pixel * resolution_x
        ymin = ymax + y_pixel * resolution_y
        centroid = [xmin + ((xmax - xmin) / 2), ymin + ((ymax - ymin) / 2)]

        lon, lat = centroid
        utm_crs_list = query_utm_crs_info(
            datum_name="WGS 84",
            area_of_interest=AreaOfInterest(
                west_lon_degree=lon,
                south_lat_degree=lat,
                east_lon_degree=lon,
                north_lat_degree=lat,
            ),
        )
        utm_crs = CRS.from_epsg(utm_crs_list[0].code).srs

        dst_crs = rio.crs.CRS.from_string(utm_crs)
        transform_, width, height = calculate_default_transform(
            wgs_dem.crs, dst_crs, wgs_dem.width, wgs_dem.height, *wgs_dem.bounds
        )
        kwargs = wgs_dem.meta.copy()
        kwargs.update({"crs": dst_crs, "transform": transform_, "width": width, "height": height})
        with rio.open(utm_dem_path, "w", **kwargs) as dst:
            for band in range(1, wgs_dem.count + 1):
                reproject(
                    source=rio.band(wgs_dem, band),
                    destination=rio.band(dst, band),
                    src_transform=wgs_dem.transform,
                    src_crs=wgs_dem.crs,
                    dst_transform=transform_,
                    dst_crs=dst_crs,
                    resampling=rio.enums.Resampling.bilinear,
                )
    return utm_crs
