# -*- coding: utf-8 -*-
"""
Created on Thu Jan  8 15:45:38 2026

@author: pelissierm
"""

import time
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio as rio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.mask import mask
from rasterio.transform import rowcol
from shapely.geometry import mapping
from pathlib import Path


#%% Logging
class _Timer:
    def __init__(self, logger=None):
        self.logger = logger

    def step(self, name):
        return _TimerStep(self.logger, name)

class _TimerStep:
    def __init__(self, logger, name):
        self.logger = logger
        self.name = name
        self.t0 = None

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        dt = time.perf_counter() - self.t0
        if self.logger:
            self.logger.info(f"[grid] {self.name}: {dt:.3f}s")


#%% WorldCover LUTs
WC_EZD = {10: 213.36, 20: 121.92, 30: 111.64, 40: 111.64, 50: 111.64, 60: 69.79, 70: 0.0, 80: 0.0, 90: 69.79, 95: 70.0, 100: 69.79}
WC_LAI = {10: 5.5, 20: 2.1, 30: 1.7, 40: 3.6, 50: 1.5, 60: 1.3, 70: 0.0, 80: 0.0, 90: 6.0, 95: 5.0, 100: 6.0}
WC_GS  = {10: 147, 20: 147, 30: 147, 40: 147, 50: 147, 60: 147, 70: 0,  80: 0,  90: 147, 95: 147, 100: 147}
WC_GE  = {10: 269, 20: 269, 30: 269, 40: 269, 50: 269, 60: 269, 70: 0,  80: 0,  90: 269, 95: 269, 100: 269}
WC_KSAT = {
    10: 2.75e-2, 20: 3.35e-4, 30: 1.2e-3, 40: 8.0e-4, 50: 1.0e-6,
    60: 1.0e-4, 70: 1.0e-6, 80: 1.0e-4, 90: 2.0e-4, 95: 2.0e-4, 100: 3.0e-4
}


#%%Private functions

# Transformer cache
_TRANSFORMERS = {}

def _get_transformer(src_crs, dst_crs):
    key = (str(src_crs), str(dst_crs))
    t = _TRANSFORMERS.get(key)
    if t is None:
        t = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
        _TRANSFORMERS[key] = t
    return t


# Raster open/clip
def _open_raster(path, clip_shp=None):
    if clip_shp is None:
        return None, rio.open(path)

    with rio.open(path) as src:
        gdf = gpd.read_file(clip_shp)
        if src.crs and gdf.crs and gdf.crs != src.crs:
            gdf = gdf.to_crs(src.crs)

        geoms = [mapping(g) for g in gdf.geometry if g is not None and not g.is_empty]
        data, transform = mask(src, geoms, crop=True)

        prof = src.profile.copy()
        prof.setdefault("driver", "GTiff")
        prof.update(height=data.shape[1], width=data.shape[2], transform=transform)

    mem = MemoryFile()
    ds = mem.open(**prof)
    ds.write(data)
    return mem, ds


def _close(mem, ds):
    try:
        ds.close()
    finally:
        if mem is not None:
            mem.close()

# Coordinate transforms
def _to_wgs84_from_raster(ds, xs, ys):
    if ds.crs is None or ds.crs.is_geographic:
        return xs.astype(float), ys.astype(float)
    t = _get_transformer(ds.crs, "EPSG:4326")
    lon, lat = t.transform(xs, ys)
    return np.asarray(lon, float), np.asarray(lat, float)


def _to_raster_crs(ds, lon, lat):
    if ds.crs is None or ds.crs.is_geographic:
        return lon, lat
    t = _get_transformer("EPSG:4326", ds.crs)
    x, y = t.transform(lon, lat)
    return np.asarray(x, float), np.asarray(y, float)

# Cleaning + fill
def _meanfill(a, zero_to_mean=False):
    if not np.any(np.isfinite(a)):
        return a
    m = float(np.nanmean(a))
    b = a.copy()
    b[np.isnan(b)] = m
    if zero_to_mean:
        b[b == 0] = m
    return b

# LUT mapping
def _lut_apply(codes, lut, default=np.nan):
    keys = np.array(sorted(lut.keys()), dtype=np.int32)
    vals = np.array([lut[int(k)] for k in keys], dtype=float)
    out = np.full(codes.shape, default, dtype=float)
    pos = np.searchsorted(keys, codes)
    ok = (pos >= 0) & (pos < keys.size) & (keys[pos] == codes)
    out[ok] = vals[pos[ok]]
    return out


# Sampling 
def _sample_band(ds, xs, ys, band=1, invalid_below=-9000.0, chunk_size=200_000):
    n = xs.shape[0]
    out = np.full(n, np.nan, dtype=float)

    valid = np.isfinite(xs) & np.isfinite(ys)
    if not np.any(valid):
        return out

    idx = np.where(valid)[0]

    for s in range(0, idx.size, chunk_size):
        sl = idx[s:s + chunk_size]
        coords = list(zip(xs[sl], ys[sl]))
        it = ds.sample(coords, indexes=band)
        vals = np.fromiter((float(v[0]) for v in it), dtype=float, count=len(coords))

        nd = ds.nodata
        if nd is not None and np.isfinite(nd):
            vals = np.where(np.isclose(vals, nd), np.nan, vals)
        if invalid_below is not None:
            vals = np.where(vals <= invalid_below, np.nan, vals)

        out[sl] = vals

    return out


def _sample_bands(ds, xs, ys, bands=(1, 2, 3, 4), invalid_below=-9000.0, chunk_size=200_000):
    n = xs.shape[0]
    out = np.full((n, len(bands)), np.nan, dtype=float)

    valid = np.isfinite(xs) & np.isfinite(ys)
    if not np.any(valid):
        return out

    idx = np.where(valid)[0]

    for s in range(0, idx.size, chunk_size):
        sl = idx[s:s + chunk_size]
        coords = list(zip(xs[sl], ys[sl]))
        it = ds.sample(coords, indexes=list(bands))
        vals = np.vstack([np.asarray(v, dtype=float) for v in it]) if coords else np.empty((0, len(bands)))

        nd = ds.nodata
        if nd is not None and np.isfinite(nd):
            vals[np.isclose(vals, nd)] = np.nan
        if invalid_below is not None:
            vals[vals <= invalid_below] = np.nan

        out[sl, :] = vals

    return out


# WorldCover codes extraction
def _worldcover_codes(ds, wc_array, xs, ys, fill=-9999):
    H, W = wc_array.shape
    codes = np.full(xs.shape[0], fill, dtype=np.int32)

    valid = np.isfinite(xs) & np.isfinite(ys)
    if not np.any(valid):
        return codes

    r, c = rowcol(ds.transform, xs[valid], ys[valid])
    r = np.asarray(r)
    c = np.asarray(c)

    inside = (r >= 0) & (r < H) & (c >= 0) & (c < W)
    if not np.any(inside):
        return codes

    idx = np.where(valid)[0]
    good = idx[inside]
    codes[good] = wc_array[r[inside], c[inside]]
    return codes


#%% Bundle
class RasterBundle:
    def __init__(self, dem, cn, slope, depth, hydroprops, worldcover):
        self.dem = dem
        self.cn = cn
        self.slope = slope
        self.depth = depth
        self.hydroprops = hydroprops
        self.worldcover = worldcover


#%% Public
def build_grid_from_dem(
    *,
    template_csv,
    out_csv,
    rasters,          
    clip_shp=None,
    glacier_shp=None,
    cid_start=0,
    default_ksat=1.0e-4,
    glacier_cn=98,
    glacier_ksat=1e-7,
    chunk_size=200_000,
    logger=None
):

    T = _Timer(logger)

    with T.step("read template"):
        tpl = pd.read_csv(template_csv)
        if tpl.shape[0] < 1:
            raise ValueError("template_csv must have at least one row.")
        tpl_row = tpl.iloc[0].to_dict()
        base_cols = list(tpl.columns)

    # 1) DEM grid (pixel centers)
    with T.step("build DEM-aligned grid"):
        mem, ds = _open_raster(rasters.dem, clip_shp)
        try:
            H, W = ds.height, ds.width
            tr = ds.transform
            r = np.repeat(np.arange(H), W)
            c = np.tile(np.arange(W), H)
            xs = tr.c + c * tr.a + r * tr.b + 0.5 * (tr.a + tr.b)
            ys = tr.f + c * tr.d + r * tr.e + 0.5 * (tr.d + tr.e)
            lon, lat = _to_wgs84_from_raster(ds, xs, ys)
        finally:
            _close(mem, ds)

        N = H * W
        df = pd.DataFrame([tpl_row] * N)[base_cols]
        df["cid"] = np.arange(cid_start, cid_start + N, dtype=int)
        df["lat_dd"] = lat
        df["lon_dd"] = lon

    LON = df["lon_dd"].to_numpy(float)
    LAT = df["lat_dd"].to_numpy(float)

    # 2) CN
    with T.step("CN"):
        mem, ds = _open_raster(rasters.cn, clip_shp)
        try:
            x, y = _to_raster_crs(ds, LON, LAT)
            v = _sample_band(ds, x, y, band=1, chunk_size=chunk_size)
            df["CN"] = _meanfill(v, zero_to_mean=True)
        finally:
            _close(mem, ds)

    # 3) slope
    with T.step("slope"):
        mem, ds = _open_raster(rasters.slope, clip_shp)
        try:
            x, y = _to_raster_crs(ds, LON, LAT)
            v = _sample_band(ds, x, y, band=1, chunk_size=chunk_size)
            v[(v < 0) | (v > 300)] = np.nan
            df["slope1"] = _meanfill(v)
        finally:
            _close(mem, ds)

    # 4) thick
    with T.step("depth"):
        mem, ds = _open_raster(rasters.depth, clip_shp)
        try:
            x, y = _to_raster_crs(ds, LON, LAT)
            df["thick1"] = _meanfill(_sample_band(ds, x, y, band=1, chunk_size=chunk_size))
        finally:
            _close(mem, ds)

    # 5) hydroprops (4 bands)
    with T.step("hydroprops"):
        mem, ds = _open_raster(rasters.hydroprops, clip_shp)
        try:
            x, y = _to_raster_crs(ds, LON, LAT)
            V = _sample_bands(ds, x, y, bands=(1, 2, 3, 4), chunk_size=chunk_size)
            poro, ksat, fc, wp = V[:, 0], V[:, 1], V[:, 2], V[:, 3]

            poro[(poro < 0) | (poro > 0.86)] = np.nan
            ksat[ksat <= 0] = np.nan
            fc[(fc < 0) | (fc > 0.8)] = np.nan
            wp[(wp < 0) | (wp > 0.7)] = np.nan

            df["poro1"] = _meanfill(poro, zero_to_mean=True)
            df["ksat1"] = _meanfill(ksat, zero_to_mean=True) / 86400.0
            df["fc1"]   = _meanfill(fc,   zero_to_mean=True)
            df["wp1"]   = _meanfill(wp,   zero_to_mean=True)
        finally:
            _close(mem, ds)

    # 6) WorldCover
    with T.step("worldcover"):
        mem, ds = _open_raster(rasters.worldcover, clip_shp)
        try:
            x, y = _to_raster_crs(ds, LON, LAT)
            wc = ds.read(1).astype(np.int32)
            codes = _worldcover_codes(ds, wc, x, y)

            df["LAI"] = _meanfill(_lut_apply(codes, WC_LAI, default=0.0))
            df["EZD"] = _meanfill(_lut_apply(codes, WC_EZD, default=0.0))

            ctx = np.ones(len(df), dtype=int)
            ctx[codes == 50] = 4
            ctx[codes == 80] = 0
            df["context"] = ctx

            df["growth_start"] = _lut_apply(codes, WC_GS, default=np.nan)
            df["growth_end"]   = _lut_apply(codes, WC_GE, default=np.nan)
            
            df["growth_start"] = _meanfill(df["growth_start"].to_numpy(float))
            df["growth_end"]   = _meanfill(df["growth_end"].to_numpy(float))


            mapped = _lut_apply(codes, WC_KSAT, default=np.nan)
            fillv = np.full(len(df), float(default_ksat), dtype=float)
            ok = np.isfinite(mapped)
            fillv[ok] = mapped[ok]
            ksat1 = df["ksat1"].to_numpy(float)
            df["ksat1"] = np.where(np.isfinite(ksat1), ksat1, fillv)
        finally:
            _close(mem, ds)

    # 7) Glacier 
    if glacier_shp is not None:
        with T.step("glacier join"):
            pts = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon_dd"], df["lat_dd"]), crs="EPSG:4326")
            gla = gpd.read_file(glacier_shp, bbox=tuple(pts.total_bounds)).to_crs(pts.crs)
            j = gpd.sjoin(pts, gla[["geometry"]], how="left", predicate="within")
            is_gla = j["index_right"].notna().to_numpy()
            df.loc[is_gla, "CN"] = glacier_cn
            df.loc[is_gla, "ksat1"] = glacier_ksat
            df.drop(columns=["geometry"], inplace=True, errors="ignore")

    with T.step("write CSV"):
        Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_csv, index=False)


