# -*- coding: utf-8 -*-
"""
Created on Tue Oct 14 11:58:51 2025

@author: Pelissierm
"""

# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import os
import shutil
import numpy as np
import pandas as pd
import xarray as xr
import rioxarray as rxr
from rasterio.transform import rowcol
from pyproj import CRS, Transformer

from hydromodpy.tools import get_logger

from hydromodpy.pyhelp.daily_output import read_daily_help_output

logger = get_logger(__name__)

def pyhelp_outputs_rasterized_netcdf(
    *,
    workdir: str | Path,
    outpath: str | Path,
    grid_csv: str | Path,
    dem: str | Path,
    compress_level: int = 4,
    clean_temp: bool = True,
) -> Path:

    workdir = Path(workdir)
    outpath = Path(outpath)
    grid_csv = Path(grid_csv)
    dem_fp = Path(dem)

    logger.info("Generating PyHELP NetCDF cubes from daily outputs")

    temp_dir = workdir / "help_input_files" / ".temp"
    if not temp_dir.exists():
        logger.warning("Temporary directory %s not found; skipping NetCDF export", temp_dir)
        return None

    out_files = sorted(temp_dir.glob("*.OUT"))
    if not out_files:
        logger.warning("No .OUT files detected in %s; NetCDF export aborted", temp_dir)
        return None

    dates_ref = None
    cids, xs, ys = [], [], []
    stacks = {"runoff": [], "evapo": [], "rechg": []}

    # grille points
    df_grid = pd.read_csv(grid_csv)
    df_grid["cid"] = df_grid["cid"].astype(str)
    xy_dict = dict(zip(df_grid["cid"], zip(df_grid["lon_dd"], df_grid["lat_dd"])))

    # lecture sorties pyhelp point par point
    for fp in out_files:
        cid = fp.stem
        data = read_daily_help_output(fp)
        if not data["rain"]:
            continue

        # dates
        dates = [
            pd.Timestamp(y, 1, 1) + pd.Timedelta(days=d - 1)
            for y, d in zip(data["years"], data["days"])
        ]
        if dates_ref is None:
            dates_ref = pd.Index(dates, name="time")
        elif len(dates) != len(dates_ref):
            logger.warning("Skipping cell %s due to inconsistent time series length", cid)
            continue

        # valeurs
        stacks["runoff"].append(np.asarray(data["runoff"], dtype="float32"))
        stacks["evapo"].append(np.asarray(data["et"], dtype="float32"))
        stacks["rechg"].append(np.asarray(data["leak_last"], dtype="float32"))

        # coordonnées x/y (lon/lat)
        x, y = xy_dict.get(cid)
        cids.append(cid)
        xs.append(x)
        ys.append(y)

    if not cids:
        logger.warning("No valid daily outputs read; NetCDF export aborted")
        return None

    # Lire géométrie du DEM
    dem_raster = rxr.open_rasterio(dem_fp, masked=True)
    H, W = dem_raster.rio.height, dem_raster.rio.width
    T = dem_raster.rio.transform()
    crs = dem_raster.rio.crs

    # coords points to ndarray
    xs_arr = np.asarray(xs, dtype=float)
    ys_arr = np.asarray(ys, dtype=float)

    # Reprojection si DEM projeté (en mètres)
    # géographique = lat/lon
    if crs and not CRS.from_user_input(crs).is_geographic:
        tr = Transformer.from_crs("EPSG:4326", CRS.from_user_input(crs), always_xy=True)
        xs_arr, ys_arr = tr.transform(xs_arr, ys_arr)
        xs_arr = np.asarray(xs_arr, dtype=float)
        ys_arr = np.asarray(ys_arr, dtype=float)

    # coord en indices pixel
    rows, cols = rowcol(T, xs_arr, ys_arr, op=round)
    rows = np.asarray(rows, dtype=int)
    cols = np.asarray(cols, dtype=int)

    flat = rows * W + cols  # index 1D des pixels

    # Coords x/y (centres de pixels)
    x_coords = (T.c + T.a * (np.arange(W) + 0.5)).astype(float)
    y_coords = (T.f + T.e * (np.arange(H) + 0.5)).astype(float)


    _geo_transform = f"{T.c}, {T.a}, {T.b}, {T.f}, {T.d}, {T.e}"

    ds_grid = xr.Dataset(
        coords={
            "time": dates_ref,
            "y": ("y", y_coords),
            "x": ("x", x_coords),
        },
        attrs={
            "GeoTransform": _geo_transform,  # aide QGIS/GDAL
        },
    )

    _wkt = CRS.from_user_input(crs).to_wkt()
    ds_grid = ds_grid.rio.write_crs(_wkt).rio.write_transform(T)


    # (time, cell) en (time, y, x) via index plat
    nt = len(dates_ref)
    for v in ("runoff", "evapo", "rechg"):
        A = np.column_stack(stacks[v]).astype("float32")  # (nt, npts)
        cube_flat = np.full((nt, H * W), np.nan, dtype="float32")
        cube_flat[:, flat] = A  # affectation 1:1
        cube = cube_flat.reshape(nt, H, W)

        ds_grid[v] = xr.DataArray(
            cube,
            dims=("time", "y", "x"),
            coords={"time": ds_grid.time, "y": ds_grid.y, "x": ds_grid.x},
            attrs={"units": "mm", "grid_mapping": "spatial_ref", "coordinates": "y x"},
        )

    # NetCDF
    nc_grid = outpath / "_pyhelp_outputs_grid.nc"
    enc = {v: {"zlib": True, "complevel": compress_level} for v in ("runoff", "evapo", "rechg")}
    enc["spatial_ref"] = {"zlib": False}
    ds_grid.to_netcdf(nc_grid, format="NETCDF4", encoding=enc)

    logger.info("NetCDF grid export complete: %s", nc_grid)

    if clean_temp:
        shutil.rmtree(workdir / "help_input_files" / ".temp")
        logger.debug("Removed temporary directory %s", workdir / "help_input_files" / ".temp")


    return nc_grid
