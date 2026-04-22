"""
This module manages the PyHELP inputs and outputs (io):
- inputs preparation (grid + climate CSVs)
- ready CSV normalization
- raster mapping utilities (DEM grid / lonlat->rowcol)
- NetCDF export (sparse & chunked writes)
"""

import logging
import shutil
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.transform import rowcol
from rasterio.warp import calculate_default_transform, reproject

from hydromodpy.core.io.crs import filter_coordinates_by_shape, transform_coordinates

from ..core.processing import read_daily_help_output
from .pyhelp_grid import PyhelpGrid

logger = logging.getLogger(__name__)


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


# Function to check wether input_grid_ready has same dimensions as resampled_dem
def expected_grid_rows_from_dem(dem_path: Path, shp: Path | None):
    with rasterio.open(dem_path) as ds:
        src_crs = ds.crs
    if src_crs is None:
        raise ValueError(f"DEM has no CRS: {dem_path}")

    coords = transform_coordinates(str(dem_path), str(src_crs), "EPSG:4326")
    if shp:
        coords = filter_coordinates_by_shape(coords, str(shp), "EPSG:4326")
    return len(coords)


def make_pyhelp_inputs(
    grid_base, dem, shp, outdir, *, nc_folder=None, ready_csvs=None, grid_params=None
):

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    grid_csv = outdir / "pyhelp_input_grid_ready.csv"
    source_grid = Path(grid_base)

    dem250 = resample_dem(dem=Path(dem))

    expected_rows = expected_grid_rows_from_dem(dem250, Path(shp) if shp else None)

    # -----Input grid handling
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
            pass

    # other cases (including no grid_ready)
    grid = PyhelpGrid(str(source_grid), str(grid_csv), str(dem250), str(shp) if shp else None)

    if grid_params is not None:
        logger.debug("Updating grid parameters from config")
        grid.update_parameters(**vars(grid_params))
    else:
        grid.update_parameters()

    # -------- Climate handling
    if nc_folder and ready_csvs:
        raise ValueError("Must specify nc_folder OR ready climatic CSVs, not both")

    if nc_folder:
        precip_nc, temp_nc, solrad_nc = (Path(p).expanduser().resolve() for p in nc_folder)

        build_pyhelp_climate_csvs_from_nc(
            precip_nc=precip_nc,
            temp_nc=temp_nc,
            solrad_nc=solrad_nc,
            outdir=outdir,
            precip_var="PRETOT",
            temp_var="T",
            solrad_var="DLI",
        )

    elif ready_csvs:
        precip_csv, tair_csv, solrad_csv = (Path(p).expanduser().resolve() for p in ready_csvs)

        if precip_csv.parent != outdir.resolve():
            shutil.copy2(precip_csv, outdir / "pyhelp_precip_input_data.csv")
        if tair_csv.parent != outdir.resolve():
            shutil.copy2(tair_csv, outdir / "pyhelp_airtemp_input_data.csv")
        if solrad_csv.parent != outdir.resolve():
            shutil.copy2(solrad_csv, outdir / "pyhelp_solrad_input_data.csv")

    else:
        raise ValueError("Must specify nc_folder or ready climatic CSVs")

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
        profile.update(
            {
                "transform": transform,
                "width": width,
                "height": height,
                "compress": "lzw",
            }
        )

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


def nc_to_pyhelp_csv(nc_path: str | Path, var: str, out_csv: str | Path) -> Path:
    """
    NetCDF (time, y, x) -> PyHELP climatic CSV:
      row1: Latitude (dd), lat1, lat2, ...
      row2: Longitude (dd), lon1, lon2, ...
      row3: empty
      then: Date, v1, v2, ... (one row per day)
    """
    nc_path = Path(nc_path).expanduser().resolve()
    out_csv = Path(out_csv).expanduser().resolve()
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    ds = xr.open_dataset(nc_path)
    da = ds[var]  # (time, y, x)

    wkt = ds["spatial_ref"].attrs["crs_wkt"]
    tr = Transformer.from_crs(CRS.from_wkt(wkt), CRS.from_epsg(4326), always_xy=True)

    x = ds["x"].values.astype(float)
    y = ds["y"].values.astype(float)
    xx, yy = np.meshgrid(x, y)
    lon, lat = tr.transform(xx, yy)
    lon = lon.ravel()
    lat = lat.ravel()

    dates = pd.to_datetime(ds["time"].values).strftime("%d/%m/%Y")
    vals = da.values.reshape(da.shape[0], -1)
    # convert solar radiation W/m2 -> MJ/m2/day
    if var == "DLI":
        vals = vals * 0.0036

    # Write header (lat/lon) + blank line
    with out_csv.open("w", encoding="utf-8") as f:
        f.write("Latitude (dd)," + ",".join(map(str, lat)) + "\n")
        f.write("Longitude (dd)," + ",".join(map(str, lon)) + "\n")
        f.write("\n")

    # Append daily data (no header)
    df = pd.DataFrame(vals)
    df.insert(0, "Date", dates)
    df.to_csv(out_csv, mode="a", index=False, header=False)

    return out_csv


def build_pyhelp_climate_csvs_from_nc(
    *,
    precip_nc: str | Path,
    temp_nc: str | Path,
    solrad_nc: str | Path,
    outdir: str | Path,
    precip_var: str = "PRETOT",
    temp_var: str = "T",
    solrad_var: str = "DLI",
) -> tuple[Path, Path, Path]:
    outdir = Path(outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    p = nc_to_pyhelp_csv(precip_nc, precip_var, outdir / "pyhelp_precip_input_data.csv")
    t = nc_to_pyhelp_csv(temp_nc, temp_var, outdir / "pyhelp_airtemp_input_data.csv")
    s = nc_to_pyhelp_csv(solrad_nc, solrad_var, outdir / "pyhelp_solrad_input_data.csv")
    return p, t, s


def export_daily_outputs_to_netcdf(
    *,
    workdir: Path,
    outpath: Path,
    grid_csv: Path,
    dem: Path,
    compress_level: int = 4,
    clean_temp: bool = True,
):
    """Export daily HELP outputs to a raster NetCDF"""

    temp_dir = workdir / "help_input_files" / ".temp"
    if not temp_dir.exists():
        raise FileNotFoundError(f"Missing HELP temp output directory: {temp_dir}")

    out_files = sorted(temp_dir.glob("*.OUT"))
    if not out_files:
        raise FileNotFoundError(f"No .OUT files found in {temp_dir}")

    # cid -> lon/lat
    df = pd.read_csv(grid_csv)
    df["cid"] = df["cid"].astype(str)
    if not {"lon_dd", "lat_dd"} <= set(df.columns):
        raise ValueError("grid_csv must contain lon_dd and lat_dd columns")
    xy = df.set_index("cid")[["lon_dd", "lat_dd"]]

    # collect valid cells + common time axis
    time_index = None
    cells = []
    for fp in out_files:
        cid = fp.stem
        if cid not in xy.index:
            continue
        data = read_daily_help_output(str(fp))
        if np.asarray(data.get("rain", [])).size == 0:
            continue
        dates = [
            pd.Timestamp(int(y), 1, 1) + pd.Timedelta(days=int(d) - 1)
            for y, d in zip(data["years"], data["days"], strict=False)
        ]
        if time_index is None:
            time_index = pd.DatetimeIndex(dates, name="time")
        if len(dates) == len(time_index):
            cells.append((cid, fp))
        else:
            logger.warning("Skipping %s: inconsistent daily length", cid)

    if time_index is None or not cells:
        raise RuntimeError("No valid daily outputs to export")

    # map cells to DEM rows/cols
    grid = load_dem_grid(Path(dem))
    lons = xy.loc[[c for c, _ in cells], "lon_dd"].to_numpy()
    lats = xy.loc[[c for c, _ in cells], "lat_dd"].to_numpy()
    rows, cols = lonlat_to_rowcol(grid, lons, lats)

    T, H, W = grid.transform, grid.height, grid.width
    x_coords = (T.c + T.a * (np.arange(W) + 0.5)).astype("float64")
    y_coords = (T.f + T.e * (np.arange(H) + 0.5)).astype("float64")

    outpath = Path(outpath).expanduser().resolve()
    outpath.parent.mkdir(parents=True, exist_ok=True)

    # NetCDF writing
    ds = nc.Dataset(outpath, "w", format="NETCDF4")
    try:
        ds.createDimension("time", len(time_index))
        ds.createDimension("y", H)
        ds.createDimension("x", W)

        time_var = ds.createVariable("time", "f8", ("time",))
        time_var.units = "days since 1970-01-01 00:00:00"
        time_var.calendar = "proleptic_gregorian"
        time_var[:] = nc.date2num(time_index.to_pydatetime(), time_var.units, time_var.calendar)

        ds.createVariable("y", "f8", ("y",))[:] = y_coords
        ds.createVariable("x", "f8", ("x",))[:] = x_coords

        # spatial metadata
        try:
            if grid.crs:
                ds.createVariable("spatial_ref", "i4").spatial_ref = CRS.from_user_input(
                    grid.crs
                ).to_wkt()
        except Exception:
            pass
        ds.GeoTransform = f"{T.c}, {T.a}, {T.b}, {T.f}, {T.d}, {T.e}"

        chunks = (1, min(512, H), min(512, W))
        vkw = dict(
            zlib=(compress_level > 0),
            complevel=int(compress_level),
            chunksizes=chunks,
            fill_value=np.nan,
        )

        v_runoff = ds.createVariable("runoff", "f4", ("time", "y", "x"), **vkw)
        v_evapo = ds.createVariable("evapo", "f4", ("time", "y", "x"), **vkw)
        v_rechg = ds.createVariable("rechg", "f4", ("time", "y", "x"), **vkw)
        for v in (v_runoff, v_evapo, v_rechg):
            v.units = "mm/day"

        for (cid, fp), r, c in zip(cells, rows, cols, strict=False):
            data = read_daily_help_output(str(fp))
            v_runoff[:, r, c] = np.asarray(data["runoff"], dtype="float32")
            v_evapo[:, r, c] = np.asarray(data["et"], dtype="float32")
            rechg = data.get("leak_last", data.get("leak last"))
            if rechg is None:
                raise KeyError(f"Recharge key not found in daily output for cid={cid}")
            v_rechg[:, r, c] = np.asarray(rechg, dtype="float32")

        ds.sync()
    finally:
        ds.close()

    if clean_temp:
        for fp in out_files:
            try:
                fp.unlink()
            except Exception:
                pass

    logger.info("NetCDF written to %s", outpath)
    return outpath
