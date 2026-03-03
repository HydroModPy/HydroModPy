# -*- coding: utf-8 -*-
"""
This module manages the PyHELP inputs and outputs (io):
- inputs preparation (grid + climate CSVs)
- ready CSV normalization
- raster mapping utilities (DEM grid / lonlat->rowcol)
- NetCDF export (sparse & chunked writes)
"""

from pathlib import Path
from typing import Tuple
import shutil

import numpy as np
import pandas as pd
import netCDF4 as nc
import rasterio
from rasterio.transform import rowcol
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject

import logging
from .pyhelp_grid import PyhelpGrid
from .pyhelp_era5 import PyhelpEra5
from hydromodpy.pyhelp.core.processing import read_daily_help_output
from hydromodpy.tools.toolbox import transform_coordinates, filter_coordinates_by_shape

logger = logging.getLogger(__name__)


def normalize_ready_csvs(ready_csvs: Tuple[str | Path, str | Path, str | Path]):
    p, t, s = (Path(x).expanduser().resolve() for x in ready_csvs)
    for fp in (p, t, s):
        if not fp.exists():
            raise FileNotFoundError(fp)
    return p, t, s


def copy_climate_csvs_to_workdir(
    *,
    workdir: Path,
    precip: Path,
    airtemp: Path,
    solrad: Path,
):
    workdir.mkdir(parents=True, exist_ok=True)
    dst_p = workdir / "pyhelp_precip_input_data.csv"
    dst_t = workdir / "pyhelp_airtemp_input_data.csv"
    dst_s = workdir / "pyhelp_solrad_input_data.csv"
    shutil.copy2(precip, dst_p)
    shutil.copy2(airtemp, dst_t)
    shutil.copy2(solrad, dst_s)
    return dst_p, dst_t, dst_s


class RasterGrid:
    def __init__(self, *, height: int, width: int, transform, crs):
        self.height = int(height)
        self.width = int(width)
        self.transform = transform
        self.crs = crs


def load_dem_grid(dem_path: Path):
    dem_path = Path(dem_path)
    with rasterio.open(dem_path) as ds:
        return RasterGrid(height=ds.height, width=ds.width, transform=ds.transform, crs=ds.crs)


def lonlat_to_rowcol(grid: RasterGrid, lon: np.ndarray, lat: np.ndarray):
    dem_crs = CRS.from_user_input(grid.crs)
    if dem_crs.to_epsg() == 4326:
        xs, ys = lon, lat
    else:
        tr = Transformer.from_crs(4326, dem_crs, always_xy=True)
        xs, ys = tr.transform(lon, lat)
    rows, cols = rowcol(grid.transform, xs, ys)
    return np.asarray(rows, dtype=int), np.asarray(cols, dtype=int)


#Function to check wether input_grid_ready has same dimensions as resampled_dem
def expected_grid_rows_from_dem(dem_path: Path, shp: Path | None) -> int:
    with rasterio.open(dem_path) as ds:
        src_crs = ds.crs
    if src_crs is None:
        raise ValueError(f"DEM has no CRS: {dem_path}")

    coords = transform_coordinates(str(dem_path), str(src_crs), "EPSG:4326")
    if shp:
        coords = filter_coordinates_by_shape(coords, str(shp), "EPSG:4326")
    return len(coords)


def make_pyhelp_inputs(grid_base, dem, shp, outdir, *, era5_folder=None, ready_csvs=None, grid_params=None):

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    grid_csv = outdir / "pyhelp_input_grid_ready.csv"
    source_grid = Path(grid_base)

    dem250 = resample_dem(dem=Path(dem))

    expected_rows = expected_grid_rows_from_dem(dem250, Path(shp) if shp else None)
    
    #-----Input grid handling
    # The grid_ready CSV is provided (already a ready grid)
    if source_grid.name == "pyhelp_input_grid_ready.csv" and source_grid.exists():
        try:
            df_ready = pd.read_csv(source_grid)
            nrows = len(df_ready)
        except Exception:
            nrows = -1

        # If dimension matches DEM 
        if nrows == expected_rows:
            if source_grid.resolve().parent != outdir.resolve():
                shutil.copy2(source_grid, grid_csv)
            return grid_csv

        # Otherwise regen from DEM250
        base_tmp = outdir / "pyhelp_input_grid_base.csv"
        try:
            df_ready.head(1).to_csv(base_tmp, index=False)
            source_grid = base_tmp
        except Exception:
            # If cannot read it, fall back to using the provided file as-is
            # (PyhelpGrid may fail)
            pass

    # other cases (including no grid_ready)
    grid = PyhelpGrid(
        str(source_grid),
        str(grid_csv),
        str(dem250),
        str(shp) if shp else None
    )

    if grid_params is not None:
        print("test")
        grid.update_parameters(**vars(grid_params))
    else:
        grid.update_parameters()

    #--------Climate handling
    if era5_folder and ready_csvs:
        raise ValueError("Argument error. Must specify raw era5 netCDF folder OR PyHELP ready climatic CSVs folder, not both")

    if era5_folder:
        era5_folder = Path(era5_folder)
        PyhelpEra5(str(era5_folder), shp).extract_era5_daily_timeseries()

        for fname in ("pyhelp_precip_input_data.csv",
                      "pyhelp_airtemp_input_data.csv",
                      "pyhelp_solrad_input_data.csv"):
            
            shutil.copy2(era5_folder / fname, outdir / fname)

    elif ready_csvs:
        precip_csv, tair_csv, solrad_csv = (
            Path(p).expanduser().resolve() for p in ready_csvs)
    
        if precip_csv.parent != outdir.resolve():
            shutil.copy2(precip_csv, outdir / "pyhelp_precip_input_data.csv")
    
        if tair_csv.parent != outdir.resolve():
            shutil.copy2(tair_csv, outdir / "pyhelp_airtemp_input_data.csv")
    
        if solrad_csv.parent != outdir.resolve():
            shutil.copy2(solrad_csv, outdir / "pyhelp_solrad_input_data.csv")

    else:
        raise ValueError("Must specify raw era5 netCDF folder or PyHELP ready climatic CSVs folder,")

    return grid_csv



def resample_dem(
    dem: Path,
    resolution: float = 250.0,
    resampling_method: Resampling = Resampling.bilinear,
        ):

    dem = Path(dem).expanduser().resolve()
    dem_out = dem.with_name(f"{dem.stem}_250{dem.suffix}")

    if dem_out.exists():
        return dem_out

    with rasterio.open(dem) as src:

        transform, width, height = calculate_default_transform(
            src.crs,
            src.crs,
            src.width,
            src.height,
            *src.bounds,
            resolution=resolution,
        )

        profile = src.profile.copy()
        profile.update({
            "transform": transform,
            "width": width,
            "height": height,
            "compress": "lzw",
        })

        with rasterio.open(dem_out, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=src.crs,
                resampling=resampling_method,
            )

    return dem_out
    

def export_daily_outputs_to_netcdf(
    *,
    workdir: Path,
    outpath: Path,
    grid_csv: Path,
    dem: Path,
    compress_level: int = 4,
    clean_temp: bool = True,
):
    """Export daily HELP outputs (*.OUT) to a raster NetCDF"""

    temp_dir = workdir / "help_input_files" / ".temp"
    if not temp_dir.exists():
        raise FileNotFoundError(f"Missing HELP temp output directory: {temp_dir}")

    out_files = sorted(temp_dir.glob("*.OUT"))
    if not out_files:
        raise FileNotFoundError(f"No .OUT files found in {temp_dir}")

    # Grid mapping cid -> lon/lat
    df_grid = pd.read_csv(grid_csv)
    df_grid["cid"] = df_grid["cid"].astype(str)
    if "lon_dd" not in df_grid.columns or "lat_dd" not in df_grid.columns:
        raise ValueError("grid_csv must contain lon_dd and lat_dd columns")
    xy = df_grid.set_index("cid")[["lon_dd", "lat_dd"]]

    # Fetch time axis from first valid cell
    time_index = None
    sample_len = None

    # Scan to collect valid cells and their data paths
    cells = []
    for fp in out_files:
        cid = fp.stem
        if cid not in xy.index:
            continue
        data = read_daily_help_output(str(fp))
        if np.asarray(data["rain"]).size == 0:
            continue

        dates = [
            pd.Timestamp(int(y), 1, 1) + pd.Timedelta(days=int(d) - 1)
            for y, d in zip(data["years"], data["days"])
        ]
        if time_index is None:
            time_index = pd.DatetimeIndex(dates, name="time")
            sample_len = len(time_index)

        if len(dates) != sample_len:
            logger.warning(
                "Skipping %s: inconsistent daily length (%d != %d)",
                cid, len(dates), sample_len
            )
            continue

        cells.append((cid, fp))

    if not cells or time_index is None:
        raise RuntimeError("No valid daily outputs to export")
        
    #dem250 = r"C:\Users\mathi\dev2\HydroModPy\examples\results\example12\results_stable\geographic\watershed_box_buff_dem_250.tif"
    
    grid = load_dem_grid(Path(dem))
    lons = xy.loc[[c for c, _ in cells], "lon_dd"].to_numpy()
    lats = xy.loc[[c for c, _ in cells], "lat_dd"].to_numpy()
    rows, cols = lonlat_to_rowcol(grid, lons, lats)

    # Compute x/y coordinate vectors from raster Affine transform (pixel centers)
    T = grid.transform
    H, W = grid.height, grid.width

    # If there is rotation/shear, 1D coords are not strictly valid; still proceed.
    if getattr(T, "b", 0.0) != 0.0 or getattr(T, "d", 0.0) != 0.0:
        logger.warning(
            "DEM transform has rotation/shear (b=%s, d=%s). "
            "Export uses 1D x/y vectors; verify alignment in GIS.",
            T.b, T.d
        )

    x_coords = (T.c + T.a * (np.arange(W) + 0.5)).astype("float64")
    y_coords = (T.f + T.e * (np.arange(H) + 0.5)).astype("float64")

    # CRS + GDAL GeoTransform string
    crs_wkt = None
    try:
        if grid.crs:
            crs_wkt = CRS.from_user_input(grid.crs).to_wkt()
    except Exception:
        crs_wkt = None

    geotransform_gdal = f"{T.c}, {T.a}, {T.b}, {T.f}, {T.d}, {T.e}"

    # Create NetCDF
    outpath = Path(outpath).expanduser().resolve()
    outpath.parent.mkdir(parents=True, exist_ok=True)

    ds = nc.Dataset(outpath, "w", format="NETCDF4")
    try:
        ds.createDimension("time", len(time_index))
        ds.createDimension("y", H)
        ds.createDimension("x", W)

        # Coordinates
        time_var = ds.createVariable("time", "f8", ("time",))
        time_units = "days since 1970-01-01 00:00:00"
        time_calendar = "proleptic_gregorian"
        time_var.units = time_units
        time_var.calendar = time_calendar
        time_var[:] = nc.date2num(
            time_index.to_pydatetime(),
            units=time_units,
            calendar=time_calendar,
        )

        y_var = ds.createVariable("y", "f8", ("y",))
        x_var = ds.createVariable("x", "f8", ("x",))
        y_var[:] = y_coords
        x_var[:] = x_coords

        # CRS metadata
        if crs_wkt:
            crs_var = ds.createVariable("spatial_ref", "i4")
            crs_var.spatial_ref = crs_wkt
        ds.GeoTransform = geotransform_gdal

        # Data vars
        chunks = (1, min(512, H), min(512, W))
        kwargs = dict(
            zlib=(compress_level > 0),
            complevel=compress_level,
            chunksizes=chunks,
            fill_value=np.nan,
        )

        v_runoff = ds.createVariable("runoff", "f4", ("time", "y", "x"), **kwargs)
        v_evapo  = ds.createVariable("evapo",  "f4", ("time", "y", "x"), **kwargs)
        v_rechg  = ds.createVariable("rechg",  "f4", ("time", "y", "x"), **kwargs)

        v_runoff.units = "mm/day"
        v_evapo.units  = "mm/day"
        v_rechg.units  = "mm/day"

        # Sparse writes
        for (cid, fp), r, c in zip(cells, rows, cols):
            data = read_daily_help_output(str(fp))
            v_runoff[:, r, c] = np.asarray(data["runoff"], dtype="float32")
            v_evapo[:,  r, c] = np.asarray(data["et"], dtype="float32")

            # robust key for recharge (old/new parser)
            if "leak_last" in data:
                rechg = data["leak_last"]
            elif "leak last" in data:
                rechg = data["leak last"]
            else:
                raise KeyError(f"Recharge key not found in daily output for cid={cid}")

            v_rechg[:,  r, c] = np.asarray(rechg, dtype="float32")

        ds.sync()
    finally:
        ds.close()

    if clean_temp:
        # keep folder but remove OUT to reduce space
        for fp in out_files:
            try:
                fp.unlink()
            except Exception:
                pass

    logger.info("NetCDF written to %s", outpath)
    return outpath