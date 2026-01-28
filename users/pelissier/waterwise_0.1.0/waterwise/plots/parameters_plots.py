# -*- coding: utf-8 -*-
"""
Created on Tue Jan 27 09:08:12 2026

@author: pelissierm
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple, Union

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import LightSource
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MplPath
from mpl_toolkits.axes_grid1 import make_axes_locatable
from rasterio.mask import mask
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy.ndimage import gaussian_filter


logger = logging.getLogger(__name__)



#%% WorldCover tables (code -> parameter value)

WC_EZD = {
    10: 213.36, 20: 121.92, 30: 111.64, 40: 111.64, 50: 111.64, 60: 69.79,
    70: 0.0, 80: 0.0, 90: 69.79, 95: 70.0, 100: 69.79
}
WC_LAI = {
    10: 5.5, 20: 2.1, 30: 1.7, 40: 3.6, 50: 1.5, 60: 1.3,
    70: 0.0, 80: 0.0, 90: 6.0, 95: 0.3, 100: 0.3
}
WC_GS = {  # growth start (DOY)
    10: 100.0, 20: 110.0, 30: 110.0, 40: 110.0, 50: 110.0, 60: 120.0,
    70: 0.0, 80: 0.0, 90: 100.0, 95: 0.0, 100: 0.0
}
WC_GE = {  # growth end (DOY)
    10: 300.0, 20: 290.0, 30: 290.0, 40: 290.0, 50: 290.0, 60: 280.0,
    70: 0.0, 80: 0.0, 90: 300.0, 95: 0.0, 100: 0.0
}
WC_KSAT = {
    10: 10.0, 20: 5.0, 30: 5.0, 40: 5.0, 50: 5.0, 60: 2.0,
    70: 0.0, 80: 0.0, 90: 1.0, 95: 0.0, 100: 0.0
}


#%% Data structures
@dataclass(frozen=True)
class RasterRef:
    """Reference grid definition for reprojection and consistent extents."""
    crs: object
    transform: object
    height: int
    width: int

#%% Titles and units
def titles_units_for(stem): #Tuple[Dict[int, str], Dict[int, str], bool, bool]
    s = stem.lower()
    if "hydroprops" in s or "hihydro" in s:
        return (
            {1: "Porosity", 2: "Ksat", 3: "Field capacity", 4: "Wilting point"},
            {1: "m³/m³", 2: "cm/s", 3: "m³/m³", 4: "m³/m³"},
            True,
            False,
        )
    if "doy" in s:
        return ({1: "Growth start", 2: "Growth end"}, {1: "Julian day", 2: "Julian day"}, False, True)
    if "lai" in s:
        return ({1: "LAI"}, {1: "[-]"}, False, False)
    if "ezd" in s:
        return ({1: "Evaporative zone depth"}, {1: "cm"}, False, False)
    if "ksat" in s:
        return ({1: "Ksat"}, {1: "cm/d"}, False, False)
    if "cn" in s:
        return ({1: "Curve Number"}, {1: "[-]"}, False, False)
    if "dem" in s or "elev" in s:
        return ({1: "Elevation"}, {1: "m"}, False, False)
    if "slope" in s:
        return ({1: "Slope"}, {1: "%"}, False, False)
    if "depth" in s:
        return ({1: "Depth"}, {1: "cm"}, False, False)

    return ({}, {}, False, False)



#%% Geo helpers
def read_border(watershed_shp):
    if not watershed_shp:
        return None
    p = Path(watershed_shp)
    if not p.exists():
        return None
    return gpd.read_file(p)


def read_glaciers(glacier_shp, clip_shp):
    if glacier_shp is None:
        return None
    p = Path(glacier_shp)
    if not p.exists():
        return None

    try:
        glaciers = gpd.read_file(p)
        if glaciers.empty:
            return None

        clip_gdf = gpd.read_file(Path(clip_shp))
        if glaciers.crs is not None and clip_gdf.crs is not None and glaciers.crs != clip_gdf.crs:
            clip_gdf = clip_gdf.to_crs(glaciers.crs)

        glaciers = gpd.clip(glaciers, clip_gdf)
        if glaciers.empty:
            return None
        return glaciers
    except Exception:
        logger.exception("Failed reading/clipping glaciers from %s", p)
        return None


def geoms_for_clip(clip_shp, dst_crs):
    g = gpd.read_file(Path(clip_shp))
    if g.crs is None:
        raise ValueError(f"clip_shp has no CRS: {clip_shp}")
    if g.crs != dst_crs:
        g = g.to_crs(dst_crs)
    return [x.__geo_interface__ for x in g.geometry if x is not None and not x.is_empty]


#%% Raster helpers
def clip_raster(path, clip_shp) :
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Missing raster: {p}")

    with rasterio.open(p) as src:
        d_masked, tr = mask(src, geoms_for_clip(clip_shp, src.crs), crop=True, filled=False)
        data = d_masked.astype(np.float32).filled(np.nan)
        return data, src.crs, tr, src.nodata


def warp_stack_to_ref(data_stack, src_crs, src_transform, ref, resampling):
    """
    Reproject a (bands, H, W) stack to ref grid.
    """
    out = np.full((data_stack.shape[0], ref.height, ref.width), np.nan, np.float32)
    for b in range(data_stack.shape[0]):
        reproject(
            data_stack[b],
            out[b],
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=ref.transform,
            dst_crs=ref.crs,
            resampling=resampling,
        )
    return out

def extent_from_transform(transform, h, w):
    x0, y0 = transform.c, transform.f
    x1 = x0 + transform.a * w
    y1 = y0 + transform.e * h
    return [x0, x1, y1, y0]

def extent_for_ref(ref: RasterRef) -> list:
    return extent_from_transform(ref.transform, ref.height, ref.width)

def reproject_2d_to_crs(arr2d, src_crs, src_transform, dst_crs):
    """
    Reproject a 2D array into dst_crs.
    """
    if src_crs == dst_crs:
        return arr2d, src_transform

    h, w = arr2d.shape
    left = src_transform.c
    top = src_transform.f
    right = left + src_transform.a * w
    bottom = top + src_transform.e * h

    dst_transform, dst_w, dst_h = calculate_default_transform(
        src_crs, dst_crs, w, h, left=left, bottom=bottom, right=right, top=top
    )
    dst = np.full((dst_h, dst_w), np.nan, np.float32)
    reproject(
        arr2d,
        dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.bilinear,
    )
    return dst, dst_transform


def fill_missing_with_mean(arr2d):
    a = arr2d.astype(np.float32, copy=True)
    if not np.isnan(a).any():
        return a
    m = np.nanmean(a)
    if np.isnan(m):
        return a
    return np.where(np.isnan(a), m, a)


def wc_lookup_map(wc, lut):
    out = np.full(wc.shape, np.nan, np.float32)
    for k, v in lut.items():
        out[wc == int(k)] = float(v)
    return out



#%% Geometry processing

def _ring_to_vertices_codes(coords):
    coords = list(coords)
    if len(coords) < 4:
        return [], []
    verts = [(coords[0][0], coords[0][1])]
    codes = [MplPath.MOVETO]
    for x, y in coords[1:]:
        verts.append((x, y))
        codes.append(MplPath.LINETO)
    codes[-1] = MplPath.CLOSEPOLY
    return verts, codes


def geom_to_path(geom):
    if geom is None or geom.is_empty:
        return None
    try:
        if geom.geom_type == "Polygon":
            verts, codes = [], []
            v, c = _ring_to_vertices_codes(geom.exterior.coords)
            verts += v
            codes += c
            for ring in geom.interiors:
                v, c = _ring_to_vertices_codes(ring.coords)
                verts += v
                codes += c
            if not verts:
                return None
            return MplPath(verts, codes)

        if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
            all_verts, all_codes = [], []
            for g in geom.geoms:
                p = geom_to_path(g)
                if p is None:
                    continue
                all_verts.extend(p.vertices.tolist())
                all_codes.extend(p.codes.tolist())
            if not all_verts:
                return None
            return MplPath(all_verts, all_codes)

        return None
    except Exception:
        return None

#%% Hillshade
def compute_hillshade(dem_path, clip_shp, ref, azdeg: float = 135.0, altdeg: float = 45.0, vert_exag: float = 2.0, smooth_sigma: float = 1.0,
):
    dem_stack, crs_dem, tr_dem, _ = clip_raster(dem_path, clip_shp)
    dem = dem_stack[0].astype(np.float32, copy=True)

    if np.isnan(dem).any():
        m = np.nanmean(dem)
        if not np.isnan(m):
            dem = np.where(np.isnan(dem), m, dem)

    if smooth_sigma and smooth_sigma > 0:
        dem = gaussian_filter(dem, sigma=float(smooth_sigma))

    ls = LightSource(azdeg=azdeg, altdeg=altdeg)
    hs_native = ls.hillshade(dem, vert_exag=vert_exag, dx=1, dy=1).astype(np.float32)

    hs_show, hs_transform = reproject_2d_to_crs(hs_native, crs_dem, tr_dem, ref.crs)
    return hs_show, hs_transform


#%% Ploting & exporting processes

def save_stack_pngs(out_dir, stem, stack, ref, border = None, glaciers = None, hillshade = None,
    hillshade_transform = None,
    hillshade_alpha: float = 1.0,
    overlay_alpha: float = 0.75,
    glaciers_alpha: float = 1.0,
):

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    titles, units, is_hydro, is_doy = titles_units_for(stem)
    ext_ref = extent_for_ref(ref)

    # Align vectors CRS to ref
    b2 = border
    if b2 is not None and b2.crs is not None and b2.crs != ref.crs:
        try:
            b2 = b2.to_crs(ref.crs)
        except Exception:
            b2 = None

    ggl = glaciers
    if ggl is not None and not ggl.empty:
        try:
            if ggl.crs is not None and ggl.crs != ref.crs:
                ggl = ggl.to_crs(ref.crs)
        except Exception:
            ggl = None

    # Band selection:
    bands = range(1, stack.shape[0] + 1)
    if stack.shape[0] > 1 and not (is_hydro or is_doy):
        bands = [1]

    for b in bands:
        arr = stack[b - 1].astype(np.float32, copy=True)
        if is_hydro:
            arr[arr <= -9990] = np.nan
        arr = fill_missing_with_mean(arr)

        fig = plt.figure(figsize=(5, 7))
        ax = fig.add_axes([0.06, 0.06, 0.72, 0.88])

        # Hillshade background
        if hillshade is not None:
            if hillshade_transform is None:
                hs_ext = ext_ref
            else:
                hs_ext = extent_from_transform(hillshade_transform, hillshade.shape[0], hillshade.shape[1])
            ax.imshow(hillshade, cmap="Greys", extent=hs_ext, origin="upper", alpha=hillshade_alpha, zorder=1)

        # Overlay raster
        if is_doy:
            im = ax.imshow(
                arr, origin="upper", cmap="viridis", extent=ext_ref, vmin=0, vmax=365,
                alpha=overlay_alpha, zorder=10
            )
        else:
            im = ax.imshow(
                arr, origin="upper", cmap="viridis", extent=ext_ref,
                alpha=overlay_alpha, zorder=10
            )

        # Glaciers
        if ggl is not None and not ggl.empty:
            try:
                plt.rcParams["hatch.linewidth"] = 1.0
            except Exception:
                pass

            for geom in ggl.geometry:
                pth = geom_to_path(geom)
                if pth is None:
                    continue

                # veil
                ax.add_patch(
                    PathPatch(
                        pth, facecolor=(0.0, 1.0, 1.0, 0.10), edgecolor="none",
                        linewidth=0.0, zorder=90
                    )
                )
                # hatch + outline
                ax.add_patch(
                    PathPatch(
                        pth, facecolor="none", edgecolor="cyan", linewidth=1.4,
                        hatch="///", alpha=glaciers_alpha, zorder=95
                    )
                )

        # Watershed boundary foreground + zoom to bounds
        if b2 is not None:
            try:
                b2.boundary.plot(ax=ax, color="red", linewidth=2.6, zorder=130)
                xmin, ymin, xmax, ymax = b2.total_bounds
                dx, dy = xmax - xmin, ymax - ymin
                m = 0.12
                ax.set_xlim(xmin - m * dx, xmax + m * dx)
                ax.set_ylim(ymin - m * dy, ymax + m * dy)
            except Exception:
                pass

        ax.set_axis_off()
        ax.set_title(titles.get(b, f"{stem} - band {b}"), pad=6)

        # Colorbar aligned
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="4.5%", pad=0.06)
        cb = fig.colorbar(im, cax=cax)
        if b in units:
            cb.set_label(units[b])

        # Legend 
        legend_items = []
        if ggl is not None and not ggl.empty:
            legend_items.append(
                Patch(facecolor=(0.0, 1.0, 1.0, 0.10), edgecolor="cyan", hatch="///", label="Glacier")
            )
        if b2 is not None:
            legend_items.append(Line2D([0], [0], color="red", lw=2.6, label="Boundaries"))

        if legend_items:
            leg = ax.legend(handles=legend_items, loc="lower left", frameon=True, framealpha=1.0, facecolor="white", edgecolor="black", fontsize=6)
            if leg is not None:
                fr = leg.get_frame()
                fr.set_facecolor((1, 1, 1, 1))
                fr.set_edgecolor("black")
                fr.set_alpha(1.0)
                fr.set_linewidth(1.2)
                leg.set_zorder(1000)
            for txt in leg.get_texts():
                txt.set_color("black")

        fig.savefig(Path(out_dir) / f"{stem}_b{b}.png", dpi=300)
        plt.close(fig)


#%% Public functions
def export_param_maps(out_dir, clip_shp, watershed_shp, dem_250m, hillshade_dem, cn, slope, soil_depth, hydroprops, worldcover,
    glacier_shp = r"Z:\HDPY_database_forModelling\PyHELP_rasters\rgi_clip.shp",
):
    
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Overlays
    border = read_border(watershed_shp)
    glaciers = read_glaciers(glacier_shp, clip_shp)

    # Reference grid from hydroprops
    hp, crs_ref, tr_ref, _ = clip_raster(hydroprops, clip_shp)
    ref = RasterRef(crs=crs_ref, transform=tr_ref, height=hp.shape[1], width=hp.shape[2])

    # Clip other layers
    cn_stack, cn_crs, cn_tr, _ = clip_raster(cn, clip_shp)
    slope_stack, sl_crs, sl_tr, _ = clip_raster(slope, clip_shp)
    depth_stack, d_crs, d_tr, _ = clip_raster(soil_depth, clip_shp)
    wc_stack, wc_crs, wc_tr, _ = clip_raster(worldcover, clip_shp)
    dem_stack, dem_crs, dem_tr, _ = clip_raster(dem_250m, clip_shp)

    # DEM map rendered on ref grid
    dem_ref = warp_stack_to_ref(dem_stack, dem_crs, dem_tr, ref, Resampling.bilinear)

    # Hillshade computed at native hillshade DEM then reprojected for display
    hs_source = hillshade_dem if hillshade_dem is not None else dem_250m
    hillshade_show, hillshade_transform = compute_hillshade(hs_source, clip_shp, ref)

    # Save stacks
    save_stack_pngs(out_dir, "Hydroprops", hp, ref, border, glaciers, hillshade_show, hillshade_transform)
    save_stack_pngs(out_dir, "DEM", dem_ref, ref, border, glaciers, hillshade_show, hillshade_transform)

    save_stack_pngs(out_dir, "CN", warp_stack_to_ref(cn_stack, cn_crs, cn_tr, ref, Resampling.nearest),
                    ref, border, glaciers, hillshade_show, hillshade_transform)
    save_stack_pngs(out_dir, "Slope", warp_stack_to_ref(slope_stack, sl_crs, sl_tr, ref, Resampling.bilinear),
                    ref, border, glaciers, hillshade_show, hillshade_transform)
    save_stack_pngs(out_dir, "soil_depth", warp_stack_to_ref(depth_stack, d_crs, d_tr, ref, Resampling.bilinear),
                    ref, border, glaciers, hillshade_show, hillshade_transform)

    # WorldCover -> parameters 
    wc_ref = warp_stack_to_ref(wc_stack, wc_crs, wc_tr, ref, Resampling.nearest)[0].astype(np.int32)

    save_stack_pngs(out_dir, "LAI", wc_lookup_map(wc_ref, WC_LAI)[None, ...],
                    ref, border, glaciers, hillshade_show, hillshade_transform)
    save_stack_pngs(out_dir, "EZD", wc_lookup_map(wc_ref, WC_EZD)[None, ...],
                    ref, border, glaciers, hillshade_show, hillshade_transform)
    save_stack_pngs(out_dir, "DOY", np.stack([wc_lookup_map(wc_ref, WC_GS), wc_lookup_map(wc_ref, WC_GE)], axis=0),
                    ref, border, glaciers, hillshade_show, hillshade_transform)
    save_stack_pngs(out_dir, "KSAT", wc_lookup_map(wc_ref, WC_KSAT)[None, ...],
                    ref, border, glaciers, hillshade_show, hillshade_transform)

    return out_dir


def plot_param_boxplots(csv_path, save_dir = None, column_positions_1based = None, whis = (5, 95)):
    
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing file: {csv_path}")

    df = pd.read_csv(csv_path)

    if column_positions_1based is None:
        positions = list(range(4, 11)) + list(range(12, 15)) + list(range(16, 21)) + [22]
    else:
        positions = list(column_positions_1based)

    cols_0based = [p - 1 for p in positions if 1 <= p <= df.shape[1]]
    if not cols_0based:
        raise ValueError("No valid column positions provided (or CSV has fewer columns).")

    data = df.iloc[:, cols_0based]

    out_dir = None
    if save_dir is not None:
        out_dir = Path(save_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    for col in data.columns:
        values = pd.to_numeric(data[col], errors="coerce").dropna()
        if values.empty:
            continue

        plt.figure(figsize=(4, 6))
        plt.boxplot(values, whis=list(whis), showfliers=True)
        plt.title(f"Boxplot ({whis[0]}–{whis[1]}) – {col}")
        plt.ylabel("Value")
        plt.grid(True, axis="y", alpha=0.3)

        if out_dir is None:
            plt.show()
        else:
            out_png = out_dir / f"box_{str(col).replace('/', '_')}.png"
            plt.savefig(out_png, dpi=150, bbox_inches="tight")
            plt.close()

    return out_dir
